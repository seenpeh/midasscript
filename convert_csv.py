"""
convert_csv.py
==============
Convert the raw semicolon-separated 5-minute CSV into a compact JSON the rest of
the pipeline reads.

Input  : data.csv / XAU_5m_data.csv
         (Date;Open;High;Low;Close;Volume ; "2004.06.11 07:15")
Output : 5m_candles.json

Format (compact: array-of-arrays keeps the file ~3x smaller than objects):
{
  "columns": ["time", "open", "high", "low", "close", "volume"],
  "tz": "UTC (assumed)",
  "count": <int>,
  "candles": [[epoch_seconds, open, high, low, close, volume], ...]
}

`time` is bar-open epoch SECONDS (UTC assumed). Lightweight-Charts and Python
both consume that directly.

The conversion also CLEANS and CHECKS the series, because a raw vendor export
is what makes a backtest lie:
  - rows with the wrong field count / unparseable numbers are dropped
  - rows are sorted by time and duplicate timestamps collapsed (last wins)
  - bars with non-positive prices, or with high < low / high < max(o,c) /
    low > min(o,c), are dropped
  - timestamps off the 5-minute grid are reported
  - gaps are classified into market closures (weekends, holidays) and DATA
    HOLES (missing bars), and the holes are written into the JSON as `holes`
    so the backtester and the chart can both refuse to trade or aggregate
    across them.
"""

import json
import os
import sys
import time as _time

import numpy as np

import timeframes as TF

SRC_CANDIDATES = ["data.csv", "XAU_5m_data.csv",
                  os.path.expanduser("~/XAU_5m_data.csv")]
DST = "5m_candles.json"


def default_src():
    for p in SRC_CANDIDATES:
        if os.path.exists(p):
            return p
    return SRC_CANDIDATES[0]


def load_csv(path: str):
    t0 = _time.time()
    print(f"Reading {path} ...", flush=True)
    with open(path, "r") as f:
        header = f.readline()
        lines = f.read().splitlines()
    print(f"  {len(lines):,} rows read in {_time.time()-t0:.1f}s", flush=True)

    t0 = _time.time()
    parts = [ln.split(";") for ln in lines]
    ncol = 6
    bad_shape = [i for i, p in enumerate(parts) if len(p) < ncol]
    if bad_shape:
        print(f"  dropping {len(bad_shape):,} malformed rows "
              f"(fewer than {ncol} fields)", flush=True)
        parts = [p for p in parts if len(p) >= ncol]
    cols = np.array([p[:ncol] for p in parts], dtype="U24")
    print(f"  split in {_time.time()-t0:.1f}s", flush=True)

    t0 = _time.time()
    # "2004.06.11 07:15" -> "2004-06-11T07:15"
    ts = np.char.replace(cols[:, 0], ".", "-")
    ts = np.char.replace(ts, " ", "T")
    dt = ts.astype("datetime64[s]")
    epoch = dt.astype("int64")

    o = cols[:, 1].astype(np.float64)
    h = cols[:, 2].astype(np.float64)
    l = cols[:, 3].astype(np.float64)
    c = cols[:, 4].astype(np.float64)
    v = cols[:, 5].astype(np.float64)
    print(f"  parsed numbers + timestamps in {_time.time()-t0:.1f}s", flush=True)

    return clean(epoch, o, h, l, c, v)


def clean(epoch, o, h, l, c, v):
    """Sort, de-duplicate and sanity-check the bars. Returns the same six
    arrays, shortened wherever a row could not be trusted."""
    n0 = epoch.size

    # 1) sort by time (stable, so a duplicate keeps its file order) ----------
    if not (np.diff(epoch) > 0).all():
        order = np.argsort(epoch, kind="stable")
        if not np.array_equal(order, np.arange(n0)):
            print(f"  rows were out of chronological order -> sorted", flush=True)
        epoch, o, h, l, c, v = (a[order] for a in (epoch, o, h, l, c, v))

    # 2) collapse duplicate timestamps (keep the LAST row for a timestamp,
    #    which is the vendor's latest revision of that bar) ------------------
    dup = np.zeros(epoch.size, dtype=bool)
    dup[:-1] = epoch[:-1] == epoch[1:]
    if dup.any():
        print(f"  dropping {int(dup.sum()):,} duplicate timestamps (kept last)",
              flush=True)
        keep = ~dup
        epoch, o, h, l, c, v = (a[keep] for a in (epoch, o, h, l, c, v))

    # 3) drop unusable bars --------------------------------------------------
    finite = np.isfinite(o) & np.isfinite(h) & np.isfinite(l) & np.isfinite(c)
    positive = (o > 0) & (h > 0) & (l > 0) & (c > 0)
    consistent = (h >= l) & (h >= np.maximum(o, c)) & (l <= np.minimum(o, c))
    good = finite & positive & consistent
    if not good.all():
        print(f"  dropping {int((~good).sum()):,} bars with impossible OHLC "
              f"(non-finite / non-positive / high<low)", flush=True)
        epoch, o, h, l, c, v = (a[good] for a in (epoch, o, h, l, c, v))

    v = np.where(np.isfinite(v) & (v >= 0), v, 0.0)

    # 4) report anything left that we do NOT silently fix ---------------------
    off = int((np.diff(epoch) % TF.BASE_SECONDS != 0).sum())
    if off:
        print(f"  WARNING: {off:,} timestamps are off the "
              f"{TF.BASE_SECONDS}s grid", flush=True)

    if epoch.size != n0:
        print(f"  {n0:,} rows in -> {epoch.size:,} bars out", flush=True)
    return epoch, o, h, l, c, v


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else default_src()
    dst = sys.argv[2] if len(sys.argv) > 2 else DST

    epoch, o, h, l, c, v = load_csv(src)

    n = epoch.shape[0]
    print(f"  range: {np.datetime64(int(epoch[0]),'s')}  ->  {np.datetime64(int(epoch[-1]),'s')}")

    print("\nIntegrity report:")
    rep = TF.integrity_report(epoch, o, h, l, c)
    TF.print_report(rep)
    holes, _closures = TF.find_breaks(epoch)
    print()

    # The source carries float noise (e.g. 878.3099999999999). True price
    # precision is 2 decimals, so round before serialising.
    t0 = _time.time()
    print("Serialising JSON (vectorised) ...", flush=True)
    epoch_s = np.char.mod("%d", epoch)
    o_s = _fmt_col(o)
    h_s = _fmt_col(h)
    l_s = _fmt_col(l)
    c_s = _fmt_col(c)
    v_s = np.char.mod("%d", np.round(v).astype(np.int64))

    rows = np.char.add("[", epoch_s)
    for col in (o_s, h_s, l_s, c_s, v_s):
        rows = np.char.add(rows, ",")
        rows = np.char.add(rows, col)
    rows = np.char.add(rows, "]")

    body = "[" + ",".join(rows.tolist()) + "]"
    header = (
        '{"columns":["time","open","high","low","close","volume"],'
        '"tz":"UTC (assumed)",'
        f'"source":{json.dumps(os.path.basename(src))},'
        f'"count":{n},'
        f'"holes":{json.dumps(holes, separators=(",", ":"))},'
        '"candles":'
    )
    with open(dst, "w") as f:
        f.write(header)
        f.write(body)
        f.write("}")
    mb = os.path.getsize(dst) / 1e6
    print(f"  wrote {dst} ({_time.time()-t0:.1f}s, {n:,} candles, {mb:.1f} MB)", flush=True)


def _fmt_col(x: np.ndarray) -> np.ndarray:
    """Round to 2 decimals and format, trimming a trailing '.00' to an integer
    and a trailing '0' (e.g. 384.00->384, 384.10->384.1)."""
    s = np.char.mod("%.2f", np.round(x, 2))
    # 384.00 -> 384
    int_part = np.char.partition(s, ".")[:, 0]
    s = np.where(np.char.endswith(s, ".00"), int_part, s)
    # 384.10 -> 384.1  (strip a single trailing zero on a 2-decimal value)
    s = np.where(np.char.endswith(s, "0") & (np.char.find(s, ".") > 0),
                 np.char.rstrip(s, "0"), s)
    return s


if __name__ == "__main__":
    main()
