"""Vectorised indicator primitives.

Pure numpy in, pure numpy out: no parameters object, no strategy knowledge, no
I/O. Each function matches the Pine built-in named in its docstring so the port
can be checked line by line against MidasScript.pine.
"""

from __future__ import annotations

import numpy as np


def ema(values: np.ndarray, length: int) -> np.ndarray:
    """Recursive EMA matching Pine's ta.ema (alpha = 2/(len+1), seeded with the
    first source value). The seed effect washes out long before any trades."""
    alpha = 2.0 / (length + 1.0)
    out = np.empty_like(values, dtype=np.float64)
    acc = values[0]
    out[0] = acc
    for i in range(1, values.shape[0]):
        acc = alpha * values[i] + (1.0 - alpha) * acc
        out[i] = acc
    return out


def true_range(high, low, close) -> np.ndarray:
    """ta.tr(true): first bar = high-low, otherwise the standard true range."""
    prev_close = np.empty_like(close)
    prev_close[0] = np.nan
    prev_close[1:] = close[:-1]
    tr = np.maximum(high - low,
                    np.maximum(np.abs(high - prev_close), np.abs(low - prev_close)))
    tr[0] = high[0] - low[0]   # handle_na = true
    return tr


def rolling_mean_prev(values: np.ndarray, window: int) -> np.ndarray:
    """ta.sma(values, m)[1] — rolling mean over `window` bars, shifted back one
    bar. Bars without a full window (or without a previous value) are NaN."""
    n = values.shape[0]
    cumulative = np.cumsum(np.insert(values, 0, 0.0))
    rolled = np.full(n, np.nan, dtype=np.float64)
    rolled[window - 1:] = (cumulative[window:] - cumulative[:-window]) / window
    out = np.full(n, np.nan, dtype=np.float64)
    out[1:] = rolled[:-1]      # the [1] shift
    return out


def shift(values: np.ndarray, bars: int, fill):
    """`values[bars]` in Pine terms: the value `bars` bars ago."""
    if bars == 0:
        return values.copy()
    out = np.empty_like(values)
    out[:bars] = fill
    out[bars:] = values[:-bars]
    return out


def clock(epoch_utc: np.ndarray, offset_hours: float = 0.0):
    """(hour, minute, shifted_seconds) for bar-open timestamps, UTC."""
    seconds = (epoch_utc + int(round(offset_hours * 3600))).astype(np.int64)
    hour = ((seconds // 3600) % 24).astype(np.int32)
    minute = ((seconds // 60) % 60).astype(np.int32)
    return hour, minute, seconds


def day_of_month(epoch_seconds: np.ndarray) -> np.ndarray:
    """Day-of-month for epoch seconds, vectorised, UTC (Pine's dayofmonth)."""
    days = (epoch_seconds // 86400).astype(np.int64).astype("datetime64[D]")
    month_start = days.astype("datetime64[M]").astype("datetime64[D]")
    return ((days - month_start).astype(np.int64) + 1).astype(np.int64)
