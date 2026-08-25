"""Entry triggers.

Three triggers fire entries in this strategy and they share most of their
machinery: a "big candle" test (body and true range large relative to their own
recent averages) plus the trend filter. That test used to be written out three
times with different variable prefixes; it is one function here, and each
trigger is a small class that says how it uses it.

Adding a fourth trigger means adding a class and listing it in
`triggers_from_params` — no edit to the consolidation logic, the stop/target
maths, or the backtester.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .indicators import rolling_mean_prev, shift

# Trigger reason codes. Priority order in the Pine script is T3 > T1 > T2.
REASON_NONE = 0
REASON_T3 = 1   # Engulfing Single Big Candle
REASON_T1 = 2   # Single Big Candle
REASON_T2 = 3   # Consecutive Candles

REASON_NAMES = {
    REASON_NONE: "",
    REASON_T3: "Engulfing Single Big Candle",
    REASON_T1: "Single Big Candle",
    REASON_T2: "Consecutive Candles",
}


@dataclass(frozen=True)
class BarFeatures:
    """Per-bar values every trigger reads. Computed once per run."""
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    body: np.ndarray
    true_range: np.ndarray

    @property
    def count(self) -> int:
        return int(self.close.shape[0])


@dataclass(frozen=True)
class TriggerContext:
    """What a trigger needs besides its own settings.

    `baseline_bull` / `baseline_bear` are the big-candle masks computed with
    TRIGGER 1's thresholds. T2 uses them to reject runs that contain a big
    candle and T3 to require that the previous bar was one, exactly as the Pine
    script does — so they are an input to those triggers, not a private detail
    of T1.
    """
    bars: BarFeatures
    long_allowed: np.ndarray
    short_allowed: np.ndarray
    baseline_bull: np.ndarray
    baseline_bear: np.ndarray


@dataclass(frozen=True)
class Detection:
    """One trigger's verdict for every bar."""
    bull: np.ndarray
    bear: np.ndarray
    stop: np.ndarray        # price the stop-loss is placed at
    avg_body: np.ndarray    # recent average body, used by the dynamic stop


def big_candle_masks(bars: BarFeatures, n: float, tr_mult: float, window: int):
    """(bullish, bearish, avg_body) for "the body is `n`x its recent average and
    the range is `tr_mult`x its own". Warm-up bars (NaN averages) never fire."""
    avg_body = rolling_mean_prev(bars.body, window)
    avg_range = rolling_mean_prev(bars.true_range, window)
    big = (bars.body >= n * avg_body) & (bars.true_range >= tr_mult * avg_range)
    warming = np.isnan(avg_body) | np.isnan(avg_range)
    bull = np.where(warming, False, (bars.close > bars.open) & big)
    bear = np.where(warming, False, (bars.close < bars.open) & big)
    return bull, bear, avg_body


class Trigger:
    """Base class: settings live on `Params` under a `t1_`/`t2_`/`t3_` prefix.

    Subclasses implement `_detect`; everything shared (reading the prefixed
    settings, exposing risk/RR to the consolidator) stays here.
    """

    code = REASON_NONE

    def __init__(self, params, prefix: str):
        self._params = params
        self._prefix = prefix

    def setting(self, name: str):
        return getattr(self._params, f"{self._prefix}_{name}")

    @property
    def name(self) -> str:
        return REASON_NAMES[self.code]

    @property
    def enabled(self) -> bool:
        return bool(self.setting("en"))

    @property
    def rr_primary(self) -> float:
        return float(self.setting("rr_pri"))

    @property
    def rr_alternate(self) -> float:
        return float(self.setting("rr_alt"))

    @property
    def risk_pct(self) -> float:
        return float(self.setting("risk"))

    def detect(self, context: TriggerContext) -> Detection:
        detection = self._detect(context)
        if self.enabled:
            return detection
        off = np.zeros(context.bars.count, dtype=bool)
        return Detection(off, off, detection.stop, detection.avg_body)

    def _detect(self, context: TriggerContext) -> Detection:
        raise NotImplementedError


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
