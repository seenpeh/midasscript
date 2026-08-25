"""Read the raw vendor CSV, clean it, and write `5m_candles.json`.

Input  : Date;Open;High;Low;Close;Volume, with dates like "2004.06.11 07:15"
Output : {"columns": [...], "count": n, "holes": [...], "candles": [[t,o,h,l,c,v], ...]}

`time` is bar-open epoch SECONDS (UTC assumed) — both Lightweight-Charts and
numpy consume that directly. Rows are stored as arrays rather than objects,
which keeps the file about three times smaller.

The conversion also CLEANS and CHECKS the series, because a raw vendor export is
what makes a backtest lie: malformed rows are dropped, bars are sorted and
de-duplicated (last revision wins), impossible OHLC is removed, off-grid
timestamps are reported, and the data holes are recorded so the backtester and
the chart can both refuse to trade or aggregate across them.
"""

from __future__ import annotations

import json
import os
import time as _time
from dataclasses import dataclass

import numpy as np

from . import timeframes as tf

COLUMN_COUNT = 6
SOURCE_CANDIDATES = ["data.csv", "XAU_5m_data.csv",
                     os.path.expanduser("~/XAU_5m_data.csv")]
DEFAULT_DESTINATION = "5m_candles.json"


def default_source() -> str:
    for path in SOURCE_CANDIDATES:
        if os.path.exists(path):
            return path
    return SOURCE_CANDIDATES[0]


@dataclass
class Columns:
    """The six raw columns, before they become a `CandleSeries`."""
    epoch: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray

    def __iter__(self):
        return iter((self.epoch, self.open, self.high, self.low, self.close,
                     self.volume))

    def __len__(self) -> int:
        return int(self.epoch.size)

    def take(self, mask) -> "Columns":
        return Columns(*(column[mask] for column in self))


# ---------------------------------------------------------------------------
def read_csv(path: str, announce=print) -> Columns:
    started = _time.time()
    announce(f"Reading {path} ...")
    with open(path, "r") as fh:
        fh.readline()                        # header
        lines = fh.read().splitlines()
    announce(f"  {len(lines):,} rows read in {_time.time()-started:.1f}s")

    started = _time.time()
    rows = [line.split(";") for line in lines]
    malformed = sum(1 for row in rows if len(row) < COLUMN_COUNT)
    if malformed:
        announce(f"  dropping {malformed:,} malformed rows "
                 f"(fewer than {COLUMN_COUNT} fields)")
        rows = [row for row in rows if len(row) >= COLUMN_COUNT]
    cells = np.array([row[:COLUMN_COUNT] for row in rows], dtype="U24")
    announce(f"  split in {_time.time()-started:.1f}s")

    started = _time.time()
    # "2004.06.11 07:15" -> "2004-06-11T07:15"
    stamps = np.char.replace(np.char.replace(cells[:, 0], ".", "-"), " ", "T")
    columns = Columns(
        epoch=stamps.astype("datetime64[s]").astype("int64"),
        open=cells[:, 1].astype(np.float64), high=cells[:, 2].astype(np.float64),
        low=cells[:, 3].astype(np.float64), close=cells[:, 4].astype(np.float64),
        volume=cells[:, 5].astype(np.float64))
    announce(f"  parsed numbers + timestamps in {_time.time()-started:.1f}s")
    return columns


def clean(columns: Columns, announce=print) -> Columns:
    """Sort, de-duplicate and sanity-check. Rows that cannot be trusted are cut."""
    original_count = len(columns)

    # 1) sort by time (stable, so a duplicate keeps its file order)
    if not (np.diff(columns.epoch) > 0).all():
        order = np.argsort(columns.epoch, kind="stable")
        if not np.array_equal(order, np.arange(original_count)):
            announce("  rows were out of chronological order -> sorted")
        columns = columns.take(order)

    # 2) collapse duplicate timestamps, keeping the LAST row for a timestamp —
    #    the vendor's latest revision of that bar
    duplicate = np.zeros(len(columns), dtype=bool)
    duplicate[:-1] = columns.epoch[:-1] == columns.epoch[1:]
    if duplicate.any():
        announce(f"  dropping {int(duplicate.sum()):,} duplicate timestamps (kept last)")
        columns = columns.take(~duplicate)

    # 3) drop unusable bars
    usable = (np.isfinite(columns.open) & np.isfinite(columns.high)
              & np.isfinite(columns.low) & np.isfinite(columns.close)
              & (columns.open > 0) & (columns.high > 0) & (columns.low > 0)
              & (columns.close > 0)
              & (columns.high >= columns.low)
              & (columns.high >= np.maximum(columns.open, columns.close))
              & (columns.low <= np.minimum(columns.open, columns.close)))
    if not usable.all():
        announce(f"  dropping {int((~usable).sum()):,} bars with impossible OHLC "
                 f"(non-finite / non-positive / high<low)")
        columns = columns.take(usable)

    columns.volume = np.where(np.isfinite(columns.volume) & (columns.volume >= 0),
                              columns.volume, 0.0)

    # 4) report what is left that we do NOT silently fix
    off_grid = int((np.diff(columns.epoch) % tf.BASE_SECONDS != 0).sum())
    if off_grid:
        announce(f"  WARNING: {off_grid:,} timestamps are off the "
                 f"{tf.BASE_SECONDS}s grid")
    if len(columns) != original_count:
        announce(f"  {original_count:,} rows in -> {len(columns):,} bars out")
    return columns


# ---------------------------------------------------------------------------
def write_json(path: str, columns: Columns, holes, source: str) -> float:
    """Serialise vectorised — building the row strings in numpy is far faster
    than `json.dump` on a million-row list, and gives exact price formatting."""
    body = "[" + ",".join(_row_strings(columns).tolist()) + "]"
    header = (
        '{"columns":["time","open","high","low","close","volume"],'
        '"tz":"UTC (assumed)",'
        f'"source":{json.dumps(os.path.basename(source))},'
        f'"count":{len(columns)},'
        f'"holes":{json.dumps(holes, separators=(",", ":"))},'
        '"candles":'
    )
    with open(path, "w") as fh:
        fh.write(header)
        fh.write(body)
        fh.write("}")
    return os.path.getsize(path) / 1e6


def _row_strings(columns: Columns) -> np.ndarray:
    rendered = [np.char.mod("%d", columns.epoch)]
    rendered += [_price_strings(c) for c in
                 (columns.open, columns.high, columns.low, columns.close)]
    rendered.append(np.char.mod("%d", np.round(columns.volume).astype(np.int64)))
    rows = np.char.add("[", rendered[0])
    for column in rendered[1:]:
        rows = np.char.add(np.char.add(rows, ","), column)
    return np.char.add(rows, "]")


def _price_strings(values: np.ndarray) -> np.ndarray:
    """Round to 2 decimals and format, trimming a trailing '.00' to an integer
    and a trailing '0' (384.00 -> 384, 384.10 -> 384.1).

    The source carries float noise (e.g. 878.3099999999999) but true price
    precision is two decimals, so rounding here also shrinks the file.
    """
    text = np.char.mod("%.2f", np.round(values, 2))
    integer_part = np.char.partition(text, ".")[:, 0]
    text = np.where(np.char.endswith(text, ".00"), integer_part, text)
    return np.where(np.char.endswith(text, "0") & (np.char.find(text, ".") > 0),
                    np.char.rstrip(text, "0"), text)
