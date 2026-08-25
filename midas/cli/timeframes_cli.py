"""`python3 timeframes.py` — data-integrity report and a resampling check."""

from __future__ import annotations

import argparse

from ..data import timeframes as tf
from ..data.series import CandleSeries
from ..reporting.console import print_integrity_report
from ..util.timeutil import format_minute


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Data-integrity report + resampling check.")
    parser.add_argument("--data", default="5m_candles.json")
    parser.add_argument("--tf", default=None, choices=tf.TF_ORDER,
                        help="also resample to this timeframe and print a summary")
    parser.add_argument("--hole-hours", type=float, default=tf.HOLE_HOURS)
    return parser


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    series = CandleSeries.from_json(args.data, args.hole_hours)

    print(f"Integrity report for {args.data}:")
    report = series.integrity_report(args.hole_hours)
    print_integrity_report(report)
    print("  =>", "OK" if report["ok"] else "PROBLEMS FOUND")

    if not args.tf:
        return
    times, _o, high, low, _c, volume = series.resample(args.tf)
    print(f"\nResampled to {args.tf}: {len(times):,} bars "
          f"({format_minute(times[0])} -> {format_minute(times[-1])})")
    print(f"  high<low after aggregation: {int((high < low).sum())}")
    print(f"  volume preserved: {volume.sum():.0f} vs {series.volume.sum():.0f}")
