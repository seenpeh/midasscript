"""The three entry rules.

Each is a small class over the shared big-candle test in `big_candle.py`:
T1 fires on one oversized candle, T2 on a run of same-direction candles whose
combined body is oversized, T3 on an oversized candle that reverses the one
before it. Every rule also obeys the trend filter it is handed in the context.

Adding a fourth trigger means adding a class here and listing it in
`triggers_from_params` — no edit to the consolidation logic, the stop/target
maths, or the backtester.
"""

from __future__ import annotations

import numpy as np

from ..indicators import rolling_mean_prev, shift
from .big_candle import Trigger, big_candle_masks
from .features import Detection, REASON_T1, REASON_T2, REASON_T3


class SingleBigCandle(Trigger):
    """T1 — one candle whose body dwarfs the recent average, with the trend."""

    code = REASON_T1

    def _detect(self, context):
        bars = context.bars
        bull, bear, avg_body = big_candle_masks(
            bars, self.setting("n"), self.setting("tr_mult"), self.setting("m"))
        return Detection(bull & context.long_allowed,
                         bear & context.short_allowed,
                         bars.open, avg_body)


class ConsecutiveCandles(Trigger):
    """T2 — a run of same-direction candles with rising lows / falling highs,
    containing no big candle, whose combined body is itself oversized."""

    code = REASON_T2

    @property
    def run_length(self) -> int:
        return int(self.setting("c"))

    def _detect(self, context):
        bars = context.bars
        count = bars.count
        run = self.run_length

        rising = np.ones(count, dtype=bool)
        falling = np.ones(count, dtype=bool)
        without_big_bull = np.ones(count, dtype=bool)
        without_big_bear = np.ones(count, dtype=bool)
        union_max = np.maximum(bars.open, bars.close).copy()
        union_min = np.minimum(bars.open, bars.close).copy()

        for back in range(run):
            open_back = shift(bars.open, back, np.nan)
            close_back = shift(bars.close, back, np.nan)

            rising &= close_back > open_back          # every candle bullish
            falling &= close_back < open_back         # every candle bearish

            if back < run - 1:
                # bull needs strictly rising lows, bear strictly falling highs
                rising &= shift(bars.low, back, np.nan) > shift(bars.low, back + 1, np.nan)
                falling &= shift(bars.high, back, np.nan) < shift(bars.high, back + 1, np.nan)

            without_big_bull &= ~shift(context.baseline_bull, back, False)
            without_big_bear &= ~shift(context.baseline_bear, back, False)

            union_max = np.maximum(union_max, np.maximum(open_back, close_back))
            union_min = np.minimum(union_min, np.minimum(open_back, close_back))

        # the first (run-1) bars have no full lookback
        incomplete = np.arange(count) < (run - 1)
        rising = np.where(incomplete, False, rising)
        falling = np.where(incomplete, False, falling)

        avg_body = rolling_mean_prev(bars.body, self.setting("m"))
        avg_range = rolling_mean_prev(bars.true_range, self.setting("m"))
        oversized = ((union_max - union_min) >= self.setting("n") * avg_body) & \
                    (bars.true_range >= self.setting("tr_mult") * avg_range)
        oversized = np.where(np.isnan(avg_body) | np.isnan(avg_range), False, oversized)

        return Detection(
            rising & without_big_bull & oversized & context.long_allowed,
            falling & without_big_bear & oversized & context.short_allowed,
            shift(bars.open, run - 1, np.nan),   # stop at the open of the run
            avg_body,
        )


class EngulfingBigCandle(Trigger):
    """T3 — a big candle that reverses the big candle before it."""

    code = REASON_T3

    def _detect(self, context):
        bars = context.bars
        bull, bear, avg_body = big_candle_masks(
            bars, self.setting("n"), self.setting("tr_mult"), self.setting("m"))
        return Detection(
            bull & shift(context.baseline_bear, 1, False) & context.long_allowed,
            bear & shift(context.baseline_bull, 1, False) & context.short_allowed,
            bars.open, avg_body)


def triggers_from_params(params) -> list:
    """The triggers in PRIORITY order — the first one to fire on a bar wins."""
    return [
        EngulfingBigCandle(params, "t3"),
        SingleBigCandle(params, "t1"),
        ConsecutiveCandles(params, "t2"),
    ]
