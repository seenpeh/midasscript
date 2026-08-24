"""`CandleSeries` — the OHLCV series as one object instead of six loose arrays.

Every function in the old code took `(epoch, o, h, l, c, v, holes)` and passed
the whole tuple down again; adding a column meant editing a dozen signatures,
and callers reached into positions by index. The series is now a value object
that knows how to slice itself and where its windows begin and end, so callers
ask it a question instead of taking it apart.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace

import numpy as np

from . import timeframes as tf


class DataError(Exception):
    """The candle file cannot be trusted for a backtest."""


@dataclass(frozen=True)
class CandleSeries:
    epoch: np.ndarray          # int64 bar-open epoch seconds, strictly increasing
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    holes: list = field(default_factory=list)

    # -- size and shape ----------------------------------------------------
    def __len__(self) -> int:
        return int(self.epoch.shape[0])

    @property
    def start(self) -> int:
        return int(self.epoch[0])

    @property
    def end(self) -> int:
        return int(self.epoch[-1])

    @property
    def ohlcv(self) -> tuple:
        """The five price arrays, for the numeric kernels that want them raw."""
        return self.open, self.high, self.low, self.close, self.volume

    # -- locating time -----------------------------------------------------
    def index_at(self, timestamp, *, side: str = "left") -> int:
        return int(np.searchsorted(self.epoch, timestamp, side=side))

    def window(self, start_ts=None, end_ts=None) -> tuple:
        """(first, last_exclusive) bar indices for a [start, end] time window.

        Always at least one bar wide so a caller can index `last - 1` safely.
        """
        first = self.index_at(start_ts) if start_ts else 0
        last = self.index_at(end_ts, side="right") if end_ts else len(self)
        return first, max(last, first + 1)

    # -- deriving ----------------------------------------------------------
    def slice(self, start: int, stop: int | None = None) -> "CandleSeries":
        """A sub-series with its data holes re-indexed onto the new offset."""
        stop = len(self) if stop is None else stop
        cut = slice(start, stop)
        return replace(
            self,
            epoch=self.epoch[cut], open=self.open[cut], high=self.high[cut],
            low=self.low[cut], close=self.close[cut], volume=self.volume[cut],
            holes=tf.reindex_holes(self.holes, start, stop),
        )

    def resample(self, timeframe: str) -> tuple:
        return tf.resample(self.epoch, *self.ohlcv, timeframe, self.holes)

    # -- integrity ---------------------------------------------------------
    def strictly_increasing(self) -> bool:
        return bool((np.diff(self.epoch) > 0).all())

    def integrity_report(self, hole_hours: float = tf.HOLE_HOURS) -> dict:
        return tf.integrity_report(self.epoch, self.open, self.high, self.low,
                                   self.close, hole_hours)

    # -- construction ------------------------------------------------------
    @classmethod
    def from_columns(cls, epoch, o, h, l, c, v, holes=None) -> "CandleSeries":
        return cls(np.asarray(epoch, dtype=np.int64), o, h, l, c, v, list(holes or []))

    @classmethod
    def from_json(cls, path: str, hole_hours: float = tf.HOLE_HOURS) -> "CandleSeries":
        """Load `5m_candles.json`.

        A backtest is only as honest as its time axis, so a series that is out of
        order or has duplicate bars is refused outright rather than quietly
        producing numbers. Holes recorded by `convert_csv` are reused unless the
        caller asked for a different threshold, in which case they are recomputed.
        """
        with open(path) as fh:
            doc = json.load(fh)
        rows = np.asarray(doc["candles"], dtype=np.float64)
        epoch = rows[:, 0].astype(np.int64)
        recorded_holes = doc.get("holes")
        series = cls.from_columns(epoch, rows[:, 1], rows[:, 2], rows[:, 3],
                                  rows[:, 4], rows[:, 5], recorded_holes)
        if not series.strictly_increasing():
            raise DataError(
                f"{path}: timestamps are not strictly increasing (duplicate or "
                f"out-of-order bars). Re-run `python3 convert_csv.py`, which "
                f"sorts and de-duplicates the source CSV.")
        if recorded_holes is None or hole_hours != tf.HOLE_HOURS:
            holes, _ = tf.find_breaks(epoch, hole_hours)
            series = replace(series, holes=holes)
        return series
