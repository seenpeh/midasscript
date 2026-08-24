"""
timeframes.py
=============
Two jobs, both about the *time axis* of the 5-minute series:

1. `find_breaks()` — locate holes in the data.

   The feed is a 5-minute grid, but it is not continuous: the market closes
   every weekend and on holidays, and the vendor's history also has stretches
   where bars are simply MISSING (e.g. 2025-09-12 -> 2025-10-15, 32 days, with
   gold 14.7% higher on the other side).

   A normal closure is not an error — a real trader holds through a weekend and
   eats the Monday gap. A *hole* is different: for those days the backtest has
   no prices at all, so any position "held" across one is fiction, and the bar
   after the hole looks like a single 14.7% candle to every indicator that
   touches it. `find_breaks()` separates the two by gap length: anything longer
   than `hole_hours` (default 96h = 4 days, longer than any Christmas /
   Thanksgiving / Easter closure in this feed) is a hole.

2. `resample()` — aggregate 5m bars into 15m / 1h / 4h / 1D.

   Buckets are aligned to the epoch (00:00 UTC boundaries for 1D/4h/1h), built
   only from bars that actually exist (no synthetic filling), and never allowed
   to span a hole — so a 1D bar cannot silently merge the last day before a
   32-day hole with the first day after it.

CLI:
    python3 timeframes.py --data 5m_candles.json            # gap report
    python3 timeframes.py --data 5m_candles.json --tf 1h    # + resample check
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone

import numpy as np

BASE_SECONDS = 300                      # the source grid

TF_SECONDS = {
    "5m":  300,
    "15m": 900,
    "1h":  3600,
    "4h":  14400,
    "1D":  86400,
}
TF_ORDER = ["5m", "15m", "1h", "4h", "1D"]

# Longer than this and a gap is missing data, not a market closure.
# The longest genuine closure in the XAU feed is ~86h (Thanksgiving / Christmas
# stretched over a weekend), so 96h clears every real one.
HOLE_HOURS = 96.0

# Gaps this long but shorter than a hole are normal closures worth reporting.
CLOSURE_HOURS = 4.0


def _ts(e) -> str:
    return datetime.fromtimestamp(int(e), timezone.utc).strftime("%Y-%m-%d %H:%M")


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
    d = np.diff(epoch)
    holes, closures = [], []
    hole_s = int(hole_hours * 3600)
    clos_s = int(closure_hours * 3600)
    for i in np.where(d > clos_s)[0]:
        rec = {"i": int(i), "start": int(epoch[i]), "end": int(epoch[i + 1]),
               "hours": round(float(d[i]) / 3600.0, 2)}
        (holes if d[i] > hole_s else closures).append(rec)
    return holes, closures


def integrity_report(epoch, o, h, l, c, hole_hours: float = HOLE_HOURS):
    """Structural checks on a loaded series. Returns a dict; `ok` is False when
    something is wrong that resampling / backtesting cannot silently absorb."""
    epoch = np.asarray(epoch, dtype=np.int64)
    d = np.diff(epoch)
    holes, closures = find_breaks(epoch, hole_hours)
    rep = {
        "bars": int(epoch.size),
        "from": _ts(epoch[0]), "to": _ts(epoch[-1]),
        "duplicate_timestamps": int((d == 0).sum()),
        "out_of_order": int((d < 0).sum()),
        "off_grid": int((d % BASE_SECONDS != 0).sum()),
        "ohlc_violations": int(((h < l) | (h < np.maximum(o, c))
                                | (l > np.minimum(o, c))).sum()),
        "nonpositive_prices": int(((o <= 0) | (h <= 0) | (l <= 0) | (c <= 0)).sum()),
        "closures": len(closures),
        "holes": [{"from": _ts(x["start"]), "to": _ts(x["end"]),
                   "days": round(x["hours"] / 24.0, 2)} for x in holes],
    }
    rep["ok"] = (rep["duplicate_timestamps"] == 0 and rep["out_of_order"] == 0
                 and rep["off_grid"] == 0 and rep["ohlc_violations"] == 0
                 and rep["nonpositive_prices"] == 0)
    return rep


def print_report(rep):
    print(f"  bars                 {rep['bars']:,}  ({rep['from']} -> {rep['to']})")
    for k in ("duplicate_timestamps", "out_of_order", "off_grid",
              "ohlc_violations", "nonpositive_prices"):
        n = rep[k]
        print(f"  {k:<20} {n:,}" + ("" if n == 0 else "   <-- PROBLEM"))
    print(f"  market closures      {rep['closures']:,}  (weekends / holidays — expected)")
    if rep["holes"]:
        print(f"  DATA HOLES           {len(rep['holes'])}  (missing bars — trading is "
              f"suspended across these)")
        for x in rep["holes"]:
            print(f"      {x['from']}  ->  {x['to']}   {x['days']} days")
    else:
        print("  data holes           0")


# ---------------------------------------------------------------------------
def bucket_starts(epoch, tf_seconds: int, hole_idx=None):
    """Bucket id per bar: the epoch of the timeframe bucket the bar opens in.

    `hole_idx` is a set/array of indices i such that bar i+1 starts a new
    contiguous run; a bucket never spans one of those, so the bar after a hole
    always opens a fresh higher-timeframe candle.
    """
    epoch = np.asarray(epoch, dtype=np.int64)
    if tf_seconds <= BASE_SECONDS:
        return epoch.copy()
    b = (epoch // tf_seconds) * tf_seconds
    if hole_idx is not None and len(hole_idx):
        # The first bar after a hole must open a fresh higher-timeframe candle.
        # Its natural bucket id may equal the bucket the pre-hole bars sit in
        # (or, on a 1D chart, the bucket its own later bars sit in) — so give
        # that leading partial bucket its own id: the bar's own epoch.
        for i in np.asarray(sorted(hole_idx), dtype=np.int64) + 1:
            if i >= epoch.size:
                continue
            bid = b[i]
            j = i
            while j < epoch.size and b[j] == bid:
                j += 1
            b[i:j] = epoch[i]                        # partial bucket opens here
    return b


def resample(epoch, o, h, l, c, v, tf: str, holes=None):
    """Aggregate the 5m series to `tf`. Returns (t, o, h, l, c, v) arrays.

    t is the bucket's own boundary epoch (or the bar's epoch when the bucket is
    a partial one that opens right after a data hole).
    """
    if tf not in TF_SECONDS:
        raise ValueError(f"unknown timeframe {tf!r} (have {list(TF_SECONDS)})")
    sec = TF_SECONDS[tf]
    epoch = np.asarray(epoch, dtype=np.int64)
    if sec <= BASE_SECONDS:
        return (epoch, np.asarray(o), np.asarray(h), np.asarray(l),
                np.asarray(c), np.asarray(v))

    hole_idx = [x["i"] for x in (holes or [])]
    b = bucket_starts(epoch, sec, hole_idx)
    # bucket boundaries: where the bucket id changes
    new = np.empty(b.size, dtype=bool)
    new[0] = True
    new[1:] = b[1:] != b[:-1]
    starts = np.where(new)[0]
    ends = np.append(starts[1:], b.size)             # exclusive

    t = b[starts]
    oo = np.asarray(o)[starts]
    cc = np.asarray(c)[ends - 1]
    hh = np.maximum.reduceat(np.asarray(h), starts)
    ll = np.minimum.reduceat(np.asarray(l), starts)
    vv = np.add.reduceat(np.asarray(v), starts)
    return t, oo, hh, ll, cc, vv


def resample_line(epoch, y, tf: str, holes=None):
    """Sample a per-5m-bar indicator (an EMA, say) at each higher-timeframe
    bucket's CLOSE — the value that bar closed on. Returns (t, y)."""
    sec = TF_SECONDS[tf]
    epoch = np.asarray(epoch, dtype=np.int64)
    if sec <= BASE_SECONDS:
        return epoch, np.asarray(y)
    b = bucket_starts(epoch, sec, [x["i"] for x in (holes or [])])
    new = np.empty(b.size, dtype=bool)
    new[0] = True
    new[1:] = b[1:] != b[:-1]
    starts = np.where(new)[0]
    ends = np.append(starts[1:], b.size)
    return b[starts], np.asarray(y)[ends - 1]


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Data-integrity report + resampling check.")
    ap.add_argument("--data", default="5m_candles.json")
    ap.add_argument("--tf", default=None, choices=TF_ORDER,
                    help="also resample to this timeframe and print a summary")
    ap.add_argument("--hole-hours", type=float, default=HOLE_HOURS)
    args = ap.parse_args()

    with open(args.data) as f:
        doc = json.load(f)
    arr = np.asarray(doc["candles"], dtype=np.float64)
    epoch = arr[:, 0].astype(np.int64)
    o, h, l, c, v = arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4], arr[:, 5]

    print(f"Integrity report for {args.data}:")
    rep = integrity_report(epoch, o, h, l, c, args.hole_hours)
    print_report(rep)
    print("  =>", "OK" if rep["ok"] else "PROBLEMS FOUND")

    if args.tf:
        holes, _ = find_breaks(epoch, args.hole_hours)
        t, ro, rh, rl, rc, rv = resample(epoch, o, h, l, c, v, args.tf, holes)
        print(f"\nResampled to {args.tf}: {len(t):,} bars "
              f"({_ts(t[0])} -> {_ts(t[-1])})")
        bad = int((rh < rl).sum())
        print(f"  high<low after aggregation: {bad}")
        print(f"  volume preserved: {rv.sum():.0f} vs {v.sum():.0f}")


if __name__ == "__main__":
    main()
