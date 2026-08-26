"""What every trigger reads: the per-bar values, and the shared context.

These types are the boundary between *trend detection* and *trigger
detection*. A trigger asks `BarFeatures` what the candle looked like and asks
`TriggerContext` whether the trend permits its direction; it never computes the
trend itself. See `midas.signals.trend` for the other side of that line.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .. import indicators as ind

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


def bar_features(series) -> BarFeatures:
    """The candle measurements the triggers work from."""
    return BarFeatures(
        open=series.open, high=series.high, low=series.low, close=series.close,
        body=np.abs(series.close - series.open),
        true_range=ind.true_range(series.high, series.low, series.close),
    )


@dataclass(frozen=True)
class TriggerContext:
    """What a trigger needs besides its own settings.

    `long_allowed` / `short_allowed` come from the trend side and are simply
    obeyed here.

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
