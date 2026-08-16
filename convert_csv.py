"""
convert_csv.py
==============
Convert the raw semicolon-separated 5-minute CSV into a compact JSON the rest of
the pipeline reads.

Input  : data.csv   (Date;Open;High;Low;Close;Volume ; "2004.06.11 07:15")
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
"""

import json
import sys
import time as _time

import numpy as np

SRC = "data.csv"
DST = "5m_candles.json"


def load_csv(path: str):
    t0 = _time.time()
    print(f"Reading {path} ...", flush=True)
    with open(path, "r") as f:
        header = f.readline()
        lines = f.read().splitlines()
    print(f"  {len(lines):,} rows read in {_time.time()-t0:.1f}s", flush=True)

    t0 = _time.time()
    # split once; build a 2D string array
    cols = np.array([ln.split(";") for ln in lines], dtype="U24")
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
    v = cols[:, 5].astype(np.float64) if cols.shape[1] > 5 else np.zeros(len(lines))
    print(f"  parsed numbers + timestamps in {_time.time()-t0:.1f}s", flush=True)

    return epoch, o, h, l, c, v


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else SRC
    dst = sys.argv[2] if len(sys.argv) > 2 else DST

    epoch, o, h, l, c, v = load_csv(src)

    n = epoch.shape[0]
    print(f"  range: {np.datetime64(int(epoch[0]),'s')}  ->  {np.datetime64(int(epoch[-1]),'s')}")

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
        f'"count":{n},'
        '"candles":'
    )
    with open(dst, "w") as f:
        f.write(header)
        f.write(body)
        f.write("}")
    import os
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
