"""Money: realised PnL, the equity curve, and the daily-loss-limit switch."""

from __future__ import annotations

from .position import Position, Trade


class DailyLossLimit:
    """Section 6.5 — stop opening trades once the day is `loss_pct` down.

    The reference equity is re-armed at each reset bar (the strategy's own
    "new trading day"), and the block stays on until the next one.
    """

    def __init__(self, enabled: bool, loss_pct: float):
        self._enabled = bool(enabled)
        self._loss_pct = float(loss_pct)
        self._reference = None
        self._tripped = False

    def start_day(self, equity: float) -> None:
        self._reference = equity
        self._tripped = False

    def observe(self, equity: float) -> None:
        if self._reference is None:
            self._reference = equity
        if self._enabled and not self._tripped:
            self._tripped = equity <= self._reference * (1.0 - self._loss_pct / 100.0)

    @property
    def blocks_entry(self) -> bool:
        return self._enabled and self._tripped


class Account:
    """Starting capital plus everything that has happened to it."""

    def __init__(self, initial: float):
        self.initial = float(initial)
        self.realized = 0.0
        self.trades: list[Trade] = []
        self.equity_points: list[tuple] = []

    @property
    def realized_equity(self) -> float:
        return self.initial + self.realized

    def equity_with(self, open_positions, price: float) -> float:
        """Live equity: realised plus the floating PnL of what is still open."""
        return self.realized_equity + sum(p.unrealized(price) for p in open_positions)

    def book(self, position: Position, exit_time: int, exit_index: int,
             exit_price: float, exit_reason: str) -> Trade:
        pnl = position.direction * (exit_price - position.entry_price) * position.quantity
        self.realized += pnl
        trade = position.close(exit_time, exit_index, exit_price, exit_reason,
                               self.initial, self.realized_equity)
        self.trades.append(trade)
        self.equity_points.append((int(exit_time), self.realized_equity))
        return trade

    def position_size(self, equity: float, risk_pct: float, risk_per_unit: float) -> float:
        """Geometric sizing: risk `risk_pct` of live equity on the stop distance."""
        return equity * (risk_pct / 100.0) / risk_per_unit
