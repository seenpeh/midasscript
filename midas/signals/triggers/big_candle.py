"""The "big candle" test and the trigger base class.

All three triggers ask the same question — is this candle's body large against
its own recent average, and is its range large against its own? — so the test
is written once here and each rule in `rules.py` says how it uses it.
"""

from __future__ import annotations

import numpy as np

from ..indicators import rolling_mean_prev
from .features import (BarFeatures, Detection, REASON_NAMES, REASON_NONE,
                       TriggerContext)


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


def baseline_masks(bars: BarFeatures, params):
    """Trigger 1's big-candle masks, which T2 and T3 also read.

    Computed deliberately regardless of whether T1 itself is enabled: they are
    part of what T2 and T3 mean, not a side effect of T1 running.
    """
    bull, bear, _ = big_candle_masks(bars, params.t1_n, params.t1_tr_mult, params.t1_m)
    return bull, bear


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
