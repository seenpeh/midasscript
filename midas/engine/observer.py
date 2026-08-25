"""What the engine tells the outside world while it runs.

The bar loop used to print. That made the engine own terminal formatting, made
"quiet" and "print every Nth trade" its problem, and meant the optimizer paid
for string work it threw away. The engine now reports events to a listener it
knows nothing about; `midas.reporting.console` renders them, and the optimizer
passes the null listener and pays nothing.
"""

from __future__ import annotations


class NullObserver:
    """Silence. The default, so nothing in the engine depends on a terminal.

    Any object with this same set of no-argument-return methods can stand in
    as an observer (`ConsoleObserver` is the other one) — duck typing, so
    there is no base class to inherit from.
    """

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
