"""Execution: what price a fill gets, and which order fires inside a bar.

Both rules used to be spelled out twice — once for longs and once for shorts —
in the middle of the bar loop. They are written once here in terms of the
position's own direction, which is also why they can be unit-checked without a
backtest.
"""

from __future__ import annotations

from dataclasses import dataclass

from .position import ExitReason, Position


@dataclass(frozen=True, slots=True)
class Bar:
    """One 5-minute bar, as the engine sees it."""
    index: int
    time: int
    open: float
    high: float
    low: float
    close: float

    def adverse(self, direction: int) -> float:
        """The extreme that hurts a position in `direction`."""
        return self.low if direction == 1 else self.high

    def favourable(self, direction: int) -> float:
        return self.high if direction == 1 else self.low


@dataclass(frozen=True, slots=True)
class Fill:
    price: float
    reason: str


class SpreadModel:
    """Candle prices are the mid; every fill moves half a spread against us.

    A round turn therefore costs one full spread, entry and exit alike.
    """

    def __init__(self, spread: float):
        self.half = max(0.0, float(spread)) / 2.0

    def entry_price(self, mid: float, direction: int) -> float:
        """A long pays the ask, a short sells the bid."""
        return mid + direction * self.half

    def exit_price(self, mid: float, direction: int) -> float:
        """A long sells the bid, a short buys the ask."""
        return mid - direction * self.half


class IntrabarBroker:
    """Decides whether a bar takes out a position's stop or target.

    House rules, matching the Pine script's intent:
      - a price that GAPS through a level at the open fills at the open
      - if both levels sit inside one bar the STOP fills first (conservative)
    """

    def resolve(self, position: Position, bar: Bar) -> Fill | None:
        direction = position.direction
        if direction * (bar.open - position.stop_loss) <= 0:
            return Fill(bar.open, ExitReason.STOP_LOSS)      # gapped through the stop
        if direction * (bar.open - position.take_profit) >= 0:
            return Fill(bar.open, ExitReason.TAKE_PROFIT)    # gapped through the target
        if direction * (bar.adverse(direction) - position.stop_loss) <= 0:
            return Fill(position.stop_loss, ExitReason.STOP_LOSS)
        if direction * (bar.favourable(direction) - position.take_profit) >= 0:
            return Fill(position.take_profit, ExitReason.TAKE_PROFIT)
        return None
