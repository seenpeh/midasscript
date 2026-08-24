"""The time axis of the 5-minute series: where it breaks, and how to aggregate it.

Two concerns live here, and only these two:

1. `find_breaks()` — separate normal market closures from DATA HOLES.

   The feed is a 5-minute grid but it is not continuous. The market closes
   every weekend and on holidays, and the vendor's history also has stretches
   where bars are simply MISSING (e.g. 2025-09-12 -> 2025-10-15, 32 days, with
   gold 14.7% higher on the other side).

   A closure is not an error — a real trader holds through a weekend and eats
   the Monday gap. A hole is: for those days there are no prices at all, so a
   position "held" across one is fiction and the bar after it looks like a
   single 14.7% candle to every indicator. The two are told apart by length:
   longer than `hole_hours` (default 96h, longer than any closure in this feed)
   is a hole.

2. `resample()` — aggregate 5m bars into 15m / 1h / 4h / 1D.

   Buckets are aligned to the epoch, built only from bars that exist (no
   synthetic filling) and never allowed to span a hole, so a 1D bar cannot
   silently merge the last day before a 32-day hole with the first day after.
"""

from __future__ import annotations

import numpy as np

from ..util.timeutil import format_minute

BASE_SECONDS = 300                      # the source grid

TF_SECONDS = {
    "5m":  300,
    "15m": 900,
    "1h":  3600,
    "4h":  14400,
    "1D":  86400,
}
TF_ORDER = ["5m", "15m", "1h", "4h", "1D"]

# Longer than this and a gap is missing data, not a market closure. The longest
# genuine closure in the XAU feed is ~86h (Thanksgiving / Christmas stretched
# over a weekend), so 96h clears every real one.
HOLE_HOURS = 96.0

# Gaps this long but shorter than a hole are normal closures worth reporting.
CLOSURE_HOURS = 4.0


# ---------------------------------------------------------------------------
# Breaks in the series
# ---------------------------------------------------------------------------
def find_breaks(epoch, hole_hours: float = HOLE_HOURS,
                closure_hours: float = CLOSURE_HOURS):
    """Return (holes, closures).

    Each entry is a dict: {"i": index of the bar BEFORE the gap, "start": its
    epoch, "end": epoch of the first bar after the gap, "hours": gap length}.
    `i+1` is therefore the first bar on the far side of the gap.
    """
    epoch = np.asarray(epoch, dtype=np.int64)
    if epoch.size < 2:
        return [], []
    deltas = np.diff(epoch)
    hole_seconds = int(hole_hours * 3600)
    closure_seconds = int(closure_hours * 3600)
    holes, closures = [], []
    for i in np.where(deltas > closure_seconds)[0]:
        record = {"i": int(i), "start": int(epoch[i]), "end": int(epoch[i + 1]),
                  "hours": round(float(deltas[i]) / 3600.0, 2)}
        (holes if deltas[i] > hole_seconds else closures).append(record)
    return holes, closures


def reindex_holes(holes, offset: int, upper: int):
    """Shift hole indices onto a slice that starts at `offset`.

    Both the optimizer (which trims the series for speed) and the chart writer
    (which exports a window) need exactly this; they used to each inline it.
    """
    return [dict(hole, i=int(hole["i"]) - offset) for hole in (holes or [])
            if offset <= int(hole["i"]) < upper - 1]


def integrity_report(epoch, o, h, l, c, hole_hours: float = HOLE_HOURS):
    """Structural checks on a loaded series. Returns a dict; `ok` is False when
    something is wrong that resampling / backtesting cannot silently absorb."""
    epoch = np.asarray(epoch, dtype=np.int64)
    deltas = np.diff(epoch)
    holes, closures = find_breaks(epoch, hole_hours)
    report = {
        "bars": int(epoch.size),
        "from": format_minute(epoch[0]), "to": format_minute(epoch[-1]),
        "duplicate_timestamps": int((deltas == 0).sum()),
        "out_of_order": int((deltas < 0).sum()),
        "off_grid": int((deltas % BASE_SECONDS != 0).sum()),
        "ohlc_violations": int(((h < l) | (h < np.maximum(o, c))
                                | (l > np.minimum(o, c))).sum()),
        "nonpositive_prices": int(((o <= 0) | (h <= 0) | (l <= 0) | (c <= 0)).sum()),
        "closures": len(closures),
        "holes": [{"from": format_minute(x["start"]), "to": format_minute(x["end"]),
                   "days": round(x["hours"] / 24.0, 2)} for x in holes],
    }
    report["ok"] = all(report[k] == 0 for k in
                       ("duplicate_timestamps", "out_of_order", "off_grid",
                        "ohlc_violations", "nonpositive_prices"))
    return report


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------
def bucket_starts(epoch, tf_seconds: int, hole_idx=None):
    """Bucket id per bar: the epoch of the timeframe bucket the bar opens in.

    `hole_idx` holds indices i such that bar i+1 starts a new contiguous run; a
    bucket never spans one of those, so the bar after a hole always opens a
    fresh higher-timeframe candle.
    """
    epoch = np.asarray(epoch, dtype=np.int64)
    if tf_seconds <= BASE_SECONDS:
        return epoch.copy()
    buckets = (epoch // tf_seconds) * tf_seconds
    if hole_idx is None or not len(hole_idx):
        return buckets
    # The first bar after a hole must open a fresh higher-timeframe candle. Its
    # natural bucket id may equal the bucket the pre-hole bars sit in (or, on a
    # 1D chart, the bucket its own later bars sit in) — so give that leading
    # partial bucket its own id: the bar's own epoch.
    for i in np.asarray(sorted(hole_idx), dtype=np.int64) + 1:
        if i >= epoch.size:
            continue
        bucket_id = buckets[i]
        j = i
        while j < epoch.size and buckets[j] == bucket_id:
            j += 1
        buckets[i:j] = epoch[i]
    return buckets


def _bucket_edges(epoch, tf_seconds: int, holes):
    """(bucket_ids, first-bar index per bucket, exclusive last index per bucket).

    Both `resample` and `resample_line` need the same segmentation; computing
    it once here keeps a candle and its indicator line on identical buckets.
    """
    buckets = bucket_starts(epoch, tf_seconds, [x["i"] for x in (holes or [])])
    is_new = np.empty(buckets.size, dtype=bool)
    is_new[0] = True
    is_new[1:] = buckets[1:] != buckets[:-1]
    starts = np.where(is_new)[0]
    ends = np.append(starts[1:], buckets.size)
    return buckets, starts, ends


def timeframe_seconds(tf: str) -> int:
    if tf not in TF_SECONDS:
        raise ValueError(f"unknown timeframe {tf!r} (have {list(TF_SECONDS)})")
    return TF_SECONDS[tf]


def resample(epoch, o, h, l, c, v, tf: str, holes=None):
    """Aggregate the 5m series to `tf`. Returns (t, o, h, l, c, v) arrays.

    t is the bucket's own boundary epoch (or the bar's epoch when the bucket is
    a partial one that opens right after a data hole).
    """
    seconds = timeframe_seconds(tf)
    epoch = np.asarray(epoch, dtype=np.int64)
    if seconds <= BASE_SECONDS:
        return (epoch, np.asarray(o), np.asarray(h), np.asarray(l),
                np.asarray(c), np.asarray(v))
    buckets, starts, ends = _bucket_edges(epoch, seconds, holes)
    return (buckets[starts],
            np.asarray(o)[starts],
            np.maximum.reduceat(np.asarray(h), starts),
            np.minimum.reduceat(np.asarray(l), starts),
            np.asarray(c)[ends - 1],
            np.add.reduceat(np.asarray(v), starts))


def resample_line(epoch, y, tf: str, holes=None):
    """Sample a per-5m-bar indicator (an EMA, say) at each higher-timeframe
    bucket's CLOSE — the value that bar closed on. Returns (t, y)."""
    seconds = timeframe_seconds(tf)
    epoch = np.asarray(epoch, dtype=np.int64)
    if seconds <= BASE_SECONDS:
        return epoch, np.asarray(y)
    buckets, starts, ends = _bucket_edges(epoch, seconds, holes)
    return buckets[starts], np.asarray(y)[ends - 1]
