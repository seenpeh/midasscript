"""Trading policy around DATA HOLES.

A hole is a stretch the feed never recorded (see `midas.data.timeframes`). The
next bar may be weeks away at a wildly different price, so a position "held"
across one — and the stop that fires on the reopening bar — is fiction. The
policy is to flatten before the hole and, optionally, stand aside for a while
afterwards until the indicators have re-warmed.
"""

from __future__ import annotations

import numpy as np


class GapPolicy:
    """Answers two questions per bar: flatten here? refuse new entries here?"""

    def __init__(self, bar_count: int, holes, flatten: bool = True,
                 warmup_bars: int = 0):
        self.holes = list(holes or [])
        self.flatten = bool(flatten) and bool(self.holes)
        self.warmup_bars = int(warmup_bars)
        self._flatten_at = np.zeros(bar_count, dtype=bool)
        self._blocked = np.zeros(bar_count, dtype=bool)
        if not self.flatten:
            return
        for hole in self.holes:
            last_tradable = int(hole["i"])
            if 0 <= last_tradable < bar_count:
                self._flatten_at[last_tradable] = True
            resume = last_tradable + 1
            if self.warmup_bars > 0 and resume < bar_count:
                self._blocked[resume:min(bar_count, resume + self.warmup_bars)] = True

    @property
    def hole_count(self) -> int:
        return len(self.holes)

    def flatten_at(self, index: int) -> bool:
        return bool(self._flatten_at[index])

    def blocks_entry(self, index: int) -> bool:
        return bool(self._blocked[index]) or bool(self._flatten_at[index])
