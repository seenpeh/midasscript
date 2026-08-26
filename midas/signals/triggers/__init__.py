"""Trigger detection: WHEN to enter, given that the trend already allows it.

The trend side (`midas.signals.trend`) decides which directions are open; this
package decides which bars actually fire an entry, and where the stop sits.
"""

from .big_candle import Trigger, baseline_masks, big_candle_masks
from .features import (BarFeatures, Detection, REASON_NAMES, REASON_NONE,
                       REASON_T1, REASON_T2, REASON_T3, TriggerContext,
                       bar_features)
from .rules import (ConsecutiveCandles, EngulfingBigCandle, SingleBigCandle,
                    triggers_from_params)

__all__ = [
    "BarFeatures", "ConsecutiveCandles", "Detection", "EngulfingBigCandle",
    "REASON_NAMES", "REASON_NONE", "REASON_T1", "REASON_T2", "REASON_T3",
    "SingleBigCandle", "Trigger", "TriggerContext", "bar_features",
    "baseline_masks", "big_candle_masks", "triggers_from_params",
]
