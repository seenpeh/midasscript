"""Trend detection: WHICH DIRECTION the market is in.

Two answers live here, and they are deliberately separate from the entry
triggers in `midas.signals.triggers`:

  - `ema_regime` — the crisp filter the strategy trades on today: fast EMA
    above slow EMA means longs are allowed, below means shorts.
  - the fuzzy detector (in progress) — a number in 0..1 describing HOW MUCH of
    an up- or downtrend this is, rather than a yes/no. See `assets/js/trend/`
    for the browser-side implementation being tuned first.
"""

from .ema_regime import EmaRegime

__all__ = ["EmaRegime"]
