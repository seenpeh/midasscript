"""The crisp EMA trend filter — Sections 1 and 1.5 of the Pine script.

Fast EMA above slow EMA: longs are allowed. Below: shorts. The bar where that
relationship flips is a trend change, which closes open positions.

This is a *regime*: a hard yes/no per direction. The fuzzy detector alongside
it answers a different question — not "which side may I trade" but "how strong
is the trend" — and the two are meant to coexist.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .. import indicators as ind


@dataclass(frozen=True)
class EmaRegime:
    """The two EMAs and the direction masks derived from them."""
    fast: np.ndarray
    slow: np.ndarray

    @classmethod
    def compute(cls, close: np.ndarray, params) -> "EmaRegime":
        return cls(fast=ind.ema(close, params.ema_fast_len),
                   slow=ind.ema(close, params.ema_slow_len))

    @property
    def long_allowed(self) -> np.ndarray:
        return self.fast > self.slow

    @property
    def short_allowed(self) -> np.ndarray:
        return self.fast < self.slow

    def changed(self) -> np.ndarray:
        """Bars where the EMA relationship flipped (Section 1.5)."""
        current = np.where(self.long_allowed, 1,
                           np.where(self.short_allowed, -1, 0)).astype(np.int8)
        previous = ind.shift(current, 1, 0)
        return (current != previous) & (previous != 0)
