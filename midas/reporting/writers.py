"""JSON artefacts the browser viewer reads.

Two files, two shapes, one rule: the writer decides the file format and nothing
else. It does not run backtests and does not print — it returns a `WriteReport`
so the caller can say what happened in its own voice.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

import numpy as np

from ..data import timeframes as tf
from ..util.sampling import downsample
from ..util.timeutil import format_minute, now_utc_text

MAX_EQUITY_POINTS = 8000
MAX_CHART_BARS = 250_000
CHART_PADDING_SECONDS = 86400      # a day of context on each side of the trades
SAME_BAR_FILL_RULE = "stop-loss first (conservative)"


@dataclass(frozen=True)
class WriteReport:
    path: str
    megabytes: float
    count: int
    detail: str = ""

    def __str__(self) -> str:
        tail = f" {self.detail}" if self.detail else ""
        return f"  wrote {self.path} ({self.megabytes:.1f} MB, {self.count:,}{tail})"


def _dump(path: str, doc: dict) -> float:
    with open(path, "w") as fh:
        json.dump(doc, fh, separators=(",", ":"))
    return os.path.getsize(path) / 1e6


def write_results(path: str, result, stats: dict, params, series) -> WriteReport:
    """`results.json`: the stats block, every trade, and a thinned equity curve."""
    curve = [[int(series.epoch[result.first_bar]), round(result.initial, 2)]]
    curve += [[int(t), round(equity, 2)] for t, equity in result.equity_points]
    curve = [[int(t), float(equity)] for t, equity in downsample(curve, MAX_EQUITY_POINTS)]

    megabytes = _dump(path, {
        "meta": {
            "generated": now_utc_text(),
            "data_start": format_minute(series.start),
            "data_end": format_minute(series.end),
            "window_start": format_minute(series.epoch[result.first_bar]),
            "window_end": format_minute(series.epoch[result.last_bar - 1]),
            "bars": len(series),
            "window_bars": int(result.last_bar - result.first_bar),
            "same_bar_fill": SAME_BAR_FILL_RULE,
            "spread": round(float(getattr(params, "spread", 0.2)), 6),
            "ruined": bool(result.ruin),
            "ruin_date": result.ruin.date if result.ruin else None,
            "params": params.as_dict(),
        },
        "stats": stats,
        "equity_curve": curve,
        "trades": result.trade_dicts,
    })
    return WriteReport(path, megabytes, len(result.trades), "trades")


def write_chart_slice(path: str, series, trades, chart_days: float,
                      ema_fast=None, ema_slow=None,
                      max_bars: int = MAX_CHART_BARS) -> WriteReport:
    """`5m_candles_chart.json`: the candle window the viewer draws.

    The window is [first entry, last exit] padded by a day, so the chart always
    contains the trades it is meant to show. If that span exceeds `chart_days`
    the most recent `chart_days` are kept, and the result is capped at
    `max_bars` candles (most recent) for browser performance.
    """
    first, last = _chart_bounds(series, trades, chart_days)
    start = series.index_at(first)
    stop = series.index_at(last, side="right")
    start = max(start, stop - max_bars)
    window = series.slice(start, stop)

    megabytes = _dump(path, {
        "columns": ["time", "open", "high", "low", "close", "volume"],
        "from": format_minute(window.start), "to": format_minute(window.end),
        "count": len(window),
        "candles": _candle_rows(window),
        "ema_fast": _line_rows(window.epoch, ema_fast, start, stop),
        "ema_slow": _line_rows(window.epoch, ema_slow, start, stop),
        # Data holes inside the exported window, re-indexed to the slice. The
        # viewer marks them and never lets a 15m/1h/4h/1D candle span one.
        "holes": window.holes,
        "timeframes": tf.TF_ORDER,
        "base_seconds": tf.BASE_SECONDS,
    })
    return WriteReport(path, megabytes, len(window),
                       f"candles, {format_minute(window.start)} -> "
                       f"{format_minute(window.end)}")


def _chart_bounds(series, trades, chart_days: float):
    span = int(chart_days * 86400)
    if not trades:
        return series.end - span, series.end
    records = [t.as_dict() if hasattr(t, "as_dict") else t for t in trades]
    first = min(r["entry_time"] for r in records) - CHART_PADDING_SECONDS
    last = max(r["exit_time"] for r in records) + CHART_PADDING_SECONDS
    if (last - first) > span:
        first = last - span      # keep the most recent `chart_days` of it
    return first, last


def _candle_rows(window) -> list:
    return [[int(t), round(float(o), 2), round(float(h), 2), round(float(l), 2),
             round(float(c), 2), float(v)]
            for t, o, h, l, c, v in zip(window.epoch, *window.ohlcv)]


def _line_rows(epoch, values, start: int, stop: int) -> list:
    if values is None:
        return []
    sliced = np.asarray(values)[start:stop]
    return [[int(t), round(float(y), 2)] for t, y in zip(epoch, sliced)]
