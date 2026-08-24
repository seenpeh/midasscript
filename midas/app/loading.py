"""Loading a candle file, with the narration a human wants while it happens.

`CandleSeries.from_json` is silent by design (the optimizer and tests want it
that way). This wraps it for the CLI and the server, which do want to see how
many bars arrived and where the data holes are.
"""

from __future__ import annotations

import time as _time

from ..data import timeframes as tf
from ..data.series import CandleSeries
from ..util.timeutil import format_minute


def load_series(path: str, hole_hours: float = tf.HOLE_HOURS,
                announce=print) -> CandleSeries:
    started = _time.time()
    announce(f"Loading {path} ...")
    series = CandleSeries.from_json(path, hole_hours)
    announce(f"  {len(series):,} candles loaded in {_time.time()-started:.1f}s "
             f"({format_minute(series.start)} -> {format_minute(series.end)})")
    if series.holes:
        announce(f"  {len(series.holes)} data hole(s) in this series — trading is "
                 f"suspended across them:")
        for hole in series.holes:
            announce(f"      {format_minute(hole['start'])} -> "
                     f"{format_minute(hole['end'])}  ({hole['hours']/24:.2f} days)")
    return series
