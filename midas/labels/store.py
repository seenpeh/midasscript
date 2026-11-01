"""The trend labels the trader draws, in one sqlite file.

Each row is one rectangle: a timeframe, the bar-open times of its first and
last candle, and which of the three trends it is. The rectangle's TOP and
BOTTOM are not stored — they are the high and low of that candle range, so the
chart recomputes them from the candle file every time it draws. Storing them
would only be a second copy that can go stale.

`bars` (how many candles the rectangle covers) IS stored, so the daily-homework
count never has to load the candle file.

Times, not bar indices: a regenerated candle file must not silently move a
label onto different candles.

`labels.db` is committed to git — that is how the labels travel from whoever
draws them to whoever trains on them. It is binary, so git cannot merge two
people's edits: one person labels at a time, and everyone else pulls.
"""

from __future__ import annotations

import sqlite3
import threading
import time

TIMEFRAMES = ("1h", "4h")
TRENDS = ("up", "side", "down")

# one day's homework, in candles, per timeframe
DAILY_QUOTA = {"1h": 800, "4h": 200}

SCHEMA = """
CREATE TABLE IF NOT EXISTS labels(
    id         INTEGER PRIMARY KEY,
    tf         TEXT    NOT NULL,
    start_ts   INTEGER NOT NULL,
    end_ts     INTEGER NOT NULL,
    bars       INTEGER NOT NULL,
    trend      TEXT    NOT NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS labels_tf_start ON labels(tf, start_ts);
"""

COLUMNS = "id, tf, start_ts, end_ts, bars, trend, created_at"


class LabelError(ValueError):
    """A label the store refuses: bad field, or it overlaps an existing one."""


class LabelStore:
    """Every read and write of the label table. One sqlite file, one lock —
    the server is threaded, and sqlite will not take concurrent writers."""

    def __init__(self, path: str):
        self.path = path
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.executescript(SCHEMA)
            self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def all(self) -> list[dict]:
        """Every label, every timeframe, oldest candle first. The whole table
        is a few thousand rows after a year of daily homework, so the browser
        takes the lot once and does its own counting and filtering."""
        with self._lock:
            rows = self._db.execute(
                f"SELECT {COLUMNS} FROM labels ORDER BY tf, start_ts").fetchall()
        return [dict(row) for row in rows]

    def add(self, tf, start_ts, end_ts, bars, trend) -> dict:
        tf, trend = _clean(tf, start_ts, end_ts, bars, trend)
        start_ts, end_ts, bars = int(start_ts), int(end_ts), int(bars)
        with self._lock:
            clash = self._db.execute(
                f"SELECT {COLUMNS} FROM labels "
                "WHERE tf = ? AND start_ts <= ? AND end_ts >= ? LIMIT 1",
                (tf, end_ts, start_ts)).fetchone()
            if clash is not None:
                raise LabelError(
                    f"those candles are already labelled {clash['trend']} on {tf}")
            cursor = self._db.execute(
                "INSERT INTO labels(tf, start_ts, end_ts, bars, trend, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (tf, start_ts, end_ts, bars, trend, int(time.time())))
            self._db.commit()
            row = self._db.execute(
                f"SELECT {COLUMNS} FROM labels WHERE id = ?",
                (cursor.lastrowid,)).fetchone()
        return dict(row)

    def delete(self, label_id: int) -> bool:
        """True if a row went away — a mis-drawn rectangle must be removable,
        or one stray click poisons the training set for good."""
        with self._lock:
            cursor = self._db.execute("DELETE FROM labels WHERE id = ?", (int(label_id),))
            self._db.commit()
        return cursor.rowcount > 0


def _clean(tf, start_ts, end_ts, bars, trend) -> tuple[str, str]:
    """Reject anything the browser should never have posted."""
    if tf not in TIMEFRAMES:
        raise LabelError(f"unknown timeframe: {tf!r}")
    if trend not in TRENDS:
        raise LabelError(f"unknown trend: {trend!r}")
    try:
        start_ts, end_ts, bars = int(start_ts), int(end_ts), int(bars)
    except (TypeError, ValueError):
        raise LabelError("start_ts, end_ts and bars must be whole numbers") from None
    if start_ts > end_ts:
        raise LabelError("the label ends before it starts")
    if bars < 1:
        raise LabelError("a label covers at least one candle")
    return tf, trend
