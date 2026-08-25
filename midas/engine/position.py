"""Open positions and the closed-trade records they become."""

from __future__ import annotations

from dataclasses import dataclass

from ..signals.triggers import REASON_NAMES
from ..util.timeutil import format_minute

LONG, SHORT = 1, -1


class ExitReason:
    """Why a position was closed. Every exit in the engine names one of these."""
    STOP_LOSS = "SL"
    TAKE_PROFIT = "TP"
    TREND_CHANGE = "TrendChange"
    TIME_EXIT = "TimeExit"
    DATA_GAP = "DataGap"
    END_OF_DATA = "EndOfData"


@dataclass(slots=True)
class Position:
    """One open position. Callers ask it questions instead of reading its fields.

    `worst_price`/`best_price` accumulate the maximum adverse and favourable
    excursions while the position is open (MAE / MFE in the trade record).
    """
    id: int
    direction: int
    entry_time: int
    entry_index: int
    entry_price: float
    quantity: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    risk_pct: float
    reason: int
    worst_price: float
    best_price: float

    @property
    def is_long(self) -> bool:
        return self.direction == LONG

    @property
    def side(self) -> str:
        return "long" if self.is_long else "short"

    def unrealized(self, price: float) -> float:
        return self.direction * (price - self.entry_price) * self.quantity

    def track(self, high: float, low: float) -> None:
        """Update the excursions with a new bar's range."""
        if self.is_long:
            self.worst_price = min(self.worst_price, low)
            self.best_price = max(self.best_price, high)
        else:
            self.worst_price = max(self.worst_price, high)
            self.best_price = min(self.best_price, low)

    def close(self, exit_time: int, exit_index: int, exit_price: float,
              exit_reason: str, initial_capital: float, equity_after: float) -> "Trade":
        return Trade(position=self, exit_time=int(exit_time), exit_index=int(exit_index),
                     exit_price=exit_price, exit_reason=exit_reason,
                     pnl=self.direction * (exit_price - self.entry_price) * self.quantity,
                     initial_capital=initial_capital, equity_after=equity_after)


@dataclass(slots=True)
class Trade:
    """A completed round turn. `as_dict()` is the wire/JSON shape."""
    position: Position
    exit_time: int
    exit_index: int
    exit_price: float
    exit_reason: str
    pnl: float
    initial_capital: float
    equity_after: float

    @property
    def direction(self) -> int:
        return self.position.direction

    @property
    def bars_held(self) -> int:
        return self.exit_index - self.position.entry_index

    @property
    def reason_name(self) -> str:
        return REASON_NAMES[self.position.reason]

    def as_dict(self) -> dict:
        p = self.position
        return {
            "id": p.id,
            "direction": p.side,
            "reason": self.reason_name,
            "entry_time": int(p.entry_time),
            "entry_dt": format_minute(p.entry_time),
            "entry_price": round(p.entry_price, 2),
            "qty": round(p.quantity, 6),
            "sl": round(p.stop_loss, 2),
            "tp": round(p.take_profit, 2),
            "rr": round(p.risk_reward, 2),
            "risk_pct": round(p.risk_pct, 2),
            "exit_time": self.exit_time,
            "exit_dt": format_minute(self.exit_time),
            "exit_price": round(self.exit_price, 2),
            "exit_reason": self.exit_reason,
            "bars_held": self.bars_held,
            "pnl": round(self.pnl, 2),
            "return_pct": round(self.pnl / self.initial_capital * 100, 4),
            "mae": round(p.worst_price, 2),   # worst adverse price excursion
            "mfe": round(p.best_price, 2),    # best favourable price excursion
            "equity_after": round(self.equity_after, 2),
        }
