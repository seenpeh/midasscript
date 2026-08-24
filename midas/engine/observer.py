"""What the engine tells the outside world while it runs.

The bar loop used to print. That made the engine own terminal formatting, made
"quiet" and "print every Nth trade" its problem, and meant the optimizer paid
for string work it threw away. The engine now reports events to a listener it
knows nothing about; `midas.reporting.console` renders them, and the optimizer
passes the null listener and pays nothing.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class RunObserver(Protocol):
    """Every hook is optional in spirit — `NullObserver` supplies the no-ops."""

    def signals_started(self) -> None: ...
    def signals_ready(self, entry_count: int, seconds: float) -> None: ...
    def window_selected(self, first: int, last: int, start_ts: int, end_ts: int) -> None: ...
    def gap_policy(self, hole_count: int, warmup_bars: int) -> None: ...
    def run_started(self, capital: float, bars: int) -> None: ...
    def year_started(self, timestamp: int, open_positions: int,
                     closed_trades: int, equity: float) -> None: ...
    def position_opened(self, position) -> None: ...
    def position_closed(self, trade) -> None: ...
    def account_ruined(self, timestamp: int, trades: int, equity: float,
                       floor_fraction: float) -> None: ...
    def run_finished(self, seconds: float, trades: int, equity: float) -> None: ...


class NullObserver:
    """Silence. The default, so nothing in the engine depends on a terminal."""

    def signals_started(self): pass
    def signals_ready(self, entry_count, seconds): pass
    def window_selected(self, first, last, start_ts, end_ts): pass
    def gap_policy(self, hole_count, warmup_bars): pass
    def run_started(self, capital, bars): pass
    def year_started(self, timestamp, open_positions, closed_trades, equity): pass
    def position_opened(self, position): pass
    def position_closed(self, trade): pass
    def account_ruined(self, timestamp, trades, equity, floor_fraction): pass
    def run_finished(self, seconds, trades, equity): pass
