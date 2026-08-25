"""The event-driven backtest: signals in, trades and an equity curve out.

Execution model (matching the Pine script's intent):
    - process_orders_on_close -> entries fill at the signal bar's CLOSE
    - every entry carries its own stop-loss and take-profit
    - pyramiding allows up to `Params.pyramiding` simultaneous positions
    - stop/take orders are evaluated intrabar on SUBSEQUENT bars (see
      `IntrabarBroker` for the gap and same-bar tie-break rules)
    - close_all (trend change / time exit / data hole) fills at that bar's close
    - size = equity * risk% / stop distance, on equity that includes floating PnL

The loop below is deliberately a list of numbered, one-line-each concerns; the
rules behind each of them live in their own module.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass, field

from ..signals.generator import compute_signals
from .account import Account, DailyLossLimit
from .broker import Bar, IntrabarBroker, SpreadModel
from .gaps import GapPolicy
from .observer import NullObserver
from .position import ExitReason, Position


@dataclass(frozen=True)
class ExecutionSettings:
    """Everything about *how* a run is executed, as one argument.

    `ruin_floor`: risk-% sizing makes a losing account decay geometrically
    toward (but never reaching) zero, spraying meaningless dust-trades. Once
    equity falls below this fraction of the starting capital the account is
    effectively blown and the run stops. Set 0 to run to literal dust.
    """
    capital: float = 10000.0
    start_ts: int | None = None
    end_ts: int | None = None
    ruin_floor: float = 0.01
    flatten_before_gaps: bool = True
    gap_warmup_bars: int = 0


@dataclass(frozen=True)
class RuinInfo:
    date: str
    trades: int
    equity: float

    def as_dict(self) -> dict:
        return {"date": self.date, "trades": self.trades, "equity": round(self.equity, 2)}


@dataclass(frozen=True)
class BacktestResult:
    """One run's output. Named fields, so callers stop unpacking a 7-tuple."""
    trades: list
    equity_points: list
    initial: float
    realized: float
    first_bar: int
    last_bar: int
    ruin: RuinInfo | None = None
    signals: object = field(default=None, repr=False)

    @property
    def final_equity(self) -> float:
        return self.initial + self.realized

    @property
    def trade_dicts(self) -> list:
        return [t.as_dict() for t in self.trades]


class Backtester:
    """Runs one parameter set over one series.

    Construction takes the *policy* (parameters, execution settings, who is
    watching); `run` takes the *data*. The same backtester can therefore be
    reused across slices, and the optimizer can build thousands of them cheaply.
    """

    def __init__(self, params, settings: ExecutionSettings | None = None,
                 observer=None, broker: IntrabarBroker | None = None):
        self.params = params
        self.settings = settings or ExecutionSettings()
        self.observer = observer or NullObserver()
        self.broker = broker or IntrabarBroker()
        self.spread = SpreadModel(getattr(params, "spread", 0.2))

    # -- public ------------------------------------------------------------
    def run(self, series) -> BacktestResult:
        signals = self._compute_signals(series)
        first, last = series.window(self.settings.start_ts, self.settings.end_ts)
        if first > 0 or last < len(series):
            self.observer.window_selected(first, last,
                                          series.epoch[first], series.epoch[last - 1])

        gaps = GapPolicy(len(series), series.holes,
                         self.settings.flatten_before_gaps,
                         self.settings.gap_warmup_bars)
        if gaps.flatten:
            self.observer.gap_policy(gaps.hole_count, gaps.warmup_bars)

        account = Account(self.settings.capital)
        self.observer.run_started(account.initial, len(series))
        started = _time.time()
        ruin = self._walk(series, signals, gaps, account, first, last)
        self.observer.run_finished(_time.time() - started, len(account.trades),
                                   account.realized_equity)
        return BacktestResult(trades=account.trades,
                              equity_points=account.equity_points,
                              initial=account.initial, realized=account.realized,
                              first_bar=first, last_bar=last, ruin=ruin,
                              signals=signals)

    # -- the loop ----------------------------------------------------------
    def _walk(self, series, signals, gaps, account, first, last) -> RuinInfo | None:
        params = self.params
        limit = DailyLossLimit(params.dll_enable, params.dll_loss_pct)
        open_positions: list[Position] = []
        next_id = 1
        year_marker = None
        ruin = None

        for i in range(first, last):
            bar = Bar(i, int(series.epoch[i]), series.open[i], series.high[i],
                      series.low[i], series.close[i])

            year_marker = self._maybe_mark_year(bar, year_marker, open_positions, account)

            # 1) broker: intrabar stop/target exits for positions opened earlier
            open_positions = self._resolve_exits(open_positions, bar, account)

            # 2) close-all events, each at this bar's close
            for triggered, reason in (
                    (signals.trend_changed[i], ExitReason.TREND_CHANGE),
                    (signals.is_close_time[i], ExitReason.TIME_EXIT),
                    (gaps.flatten_at(i), ExitReason.DATA_GAP)):
                if open_positions and triggered:
                    self._close_all(open_positions, bar, account, reason)
                    open_positions = []

            # 3) live equity, including floating PnL
            equity = account.equity_with(open_positions, bar.close)

            # 4) ruin halt
            if equity <= account.initial * self.settings.ruin_floor:
                self._close_all(open_positions, bar, account, ExitReason.END_OF_DATA)
                open_positions = []
                ruin = RuinInfo(_date(bar.time), len(account.trades), equity)
                self.observer.account_ruined(bar.time, ruin.trades, equity,
                                             self.settings.ruin_floor)
                break

            # 5) daily-loss-limit state machine
            if signals.is_reset_time[i]:
                limit.start_day(equity)
            limit.observe(equity)

            # 6) entry at this bar's close
            if self._may_enter(signals, gaps, limit, open_positions, i):
                position = self._open(signals, bar, equity, account, next_id)
                if position is not None:
                    open_positions.append(position)
                    next_id += 1
                    self.observer.position_opened(position)

        # anything still open is closed on the last bar of the window
        if open_positions:
            final = last - 1
            bar = Bar(final, int(series.epoch[final]), series.open[final],
                      series.high[final], series.low[final], series.close[final])
            self._close_all(open_positions, bar, account, ExitReason.END_OF_DATA)
        return ruin

    # -- steps -------------------------------------------------------------
    def _compute_signals(self, series):
        self.observer.signals_started()
        started = _time.time()
        signals = compute_signals(series, self.params)
        self.observer.signals_ready(signals.entry_count, _time.time() - started)
        return signals

    def _maybe_mark_year(self, bar, year_marker, open_positions, account):
        year = bar.time // (365 * 86400)
        if year != year_marker:
            self.observer.year_started(bar.time, len(open_positions),
                                       len(account.trades), account.realized_equity)
        return year

    def _resolve_exits(self, open_positions, bar, account) -> list:
        survivors = []
        for position in open_positions:
            position.track(bar.high, bar.low)
            fill = self.broker.resolve(position, bar)
            if fill is None:
                survivors.append(position)
            else:
                self._book(position, bar, account, fill.price, fill.reason)
        return survivors

    def _close_all(self, open_positions, bar, account, reason) -> None:
        for position in open_positions:
            self._book(position, bar, account, bar.close, reason)

    def _book(self, position, bar, account, mid_price, reason) -> None:
        trade = account.book(position, bar.time, bar.index,
                             self.spread.exit_price(mid_price, position.direction),
                             reason)
        self.observer.position_closed(trade)

    def _may_enter(self, signals, gaps, limit, open_positions, i) -> bool:
        return bool(signals.entry[i]) and not limit.blocks_entry \
            and not gaps.blocks_entry(i) \
            and len(open_positions) < self.params.pyramiding

    def _open(self, signals, bar, equity, account, position_id) -> Position | None:
        stop_loss = float(signals.stop_loss[bar.index])
        risk_per_unit = abs(bar.close - stop_loss)
        if risk_per_unit <= 0:
            return None
        direction = int(signals.direction[bar.index])
        return Position(
            id=position_id,
            direction=direction,
            entry_time=bar.time,
            entry_index=bar.index,
            entry_price=self.spread.entry_price(bar.close, direction),
            quantity=account.position_size(equity, float(signals.risk_pct[bar.index]),
                                           risk_per_unit),
            stop_loss=stop_loss,
            take_profit=float(signals.take_profit[bar.index]),
            risk_reward=float(signals.risk_reward[bar.index]),
            risk_pct=float(signals.risk_pct[bar.index]),
            reason=int(signals.reason[bar.index]),
            worst_price=bar.close,
            best_price=bar.close,
        )


def _date(timestamp) -> str:
    from ..util.timeutil import format_minute
    return format_minute(timestamp)
