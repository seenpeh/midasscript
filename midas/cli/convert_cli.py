"""`python3 convert_csv.py [src] [dst]` — raw CSV -> `5m_candles.json`."""

from __future__ import annotations

import sys
import time as _time

import numpy as np

from ..data import timeframes as tf
from ..data.csv_import import (DEFAULT_DESTINATION, clean, default_source,
                               read_csv, write_json)
from ..reporting.console import print_integrity_report


def main(argv=None) -> None:
    argv = sys.argv[1:] if argv is None else list(argv)
    source = argv[0] if len(argv) > 0 else default_source()
    destination = argv[1] if len(argv) > 1 else DEFAULT_DESTINATION

    columns = clean(read_csv(source))
    print(f"  range: {np.datetime64(int(columns.epoch[0]), 's')}  ->  "
          f"{np.datetime64(int(columns.epoch[-1]), 's')}")

    print("\nIntegrity report:")
    print_integrity_report(tf.integrity_report(
        columns.epoch, columns.open, columns.high, columns.low, columns.close))
    holes, _closures = tf.find_breaks(columns.epoch)
    print()

    started = _time.time()
    print("Serialising JSON (vectorised) ...", flush=True)
    megabytes = write_json(destination, columns, holes, source)
    print(f"  wrote {destination} ({_time.time()-started:.1f}s, "
          f"{len(columns):,} candles, {megabytes:.1f} MB)", flush=True)
