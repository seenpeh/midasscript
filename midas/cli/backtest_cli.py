"""`python3 backtest.py` — run one backtest from the command line.

Argument parsing only. The work is `midas.app.backtest_run.run_backtest`, which
the HTTP server calls too, so a flag added here can never change behaviour the
browser sees.
"""

from __future__ import annotations

import argparse

from ..app.backtest_run import OutputSettings, run_backtest
from ..app.loading import load_series
from ..config.params import Params
from ..data import timeframes as tf
from ..engine.backtester import ExecutionSettings
from ..reporting.ansi import Palette
from ..reporting.console import ConsoleObserver
from ..util.timeutil import parse_timestamp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Backtest the Ultimate-script strategy.")
    parser.add_argument("--data", default="5m_candles.json")
    parser.add_argument("--capital", type=float, default=10000.0)
    parser.add_argument("--start", default=None,
                        help="trading window start (YYYY-MM-DD or 'YYYY-MM-DD HH:MM' UTC)")
    parser.add_argument("--end", default=None,
                        help="trading window end (YYYY-MM-DD or 'YYYY-MM-DD HH:MM' UTC)")
    parser.add_argument("--results", default="results.json")
    parser.add_argument("--chart-out", default="5m_candles_chart.json")
    parser.add_argument("--chart-days", type=float, default=730.0,
                        help="how many recent days of candles to export for the HTML chart")
    parser.add_argument("--print-every", type=int, default=1,
                        help="print 1 of every N trades (1 = print all)")
    parser.add_argument("--quiet", action="store_true", help="suppress per-trade output")
    parser.add_argument("--ruin-floor", type=float, default=0.01,
                        help="halt when equity falls below this fraction of starting "
                             "capital (default 0.01 = -99%%); 0 disables the halt")
    parser.add_argument("--tz-offset", type=float, default=0.0,
                        help="hours to add to CSV timestamps to reach UTC")
    parser.add_argument("--ny-session", action="store_true",
                        help="only open entries during the New York session "
                             "(17:00-23:00 UTC)")
    parser.add_argument("--session-start-hr", type=int, default=17,
                        help="entry-window start hour UTC (with --ny-session)")
    parser.add_argument("--session-end-hr", type=int, default=23,
                        help="entry-window end hour UTC, exclusive (with --ny-session)")
    parser.add_argument("--no-gap-flat", action="store_true",
                        help="do NOT flatten positions before a data hole "
                             "(reproduces the old, unrealistic behaviour)")
    parser.add_argument("--gap-warmup", type=int, default=0,
                        help="bars after a data hole during which no new entry is "
                             "taken (indicators are still stale from before it)")
    parser.add_argument("--hole-hours", type=float, default=tf.HOLE_HOURS,
                        help="a gap longer than this many hours is a DATA HOLE, "
                             "not a market closure (default %(default)s)")
    return parser


def params_from_args(args) -> Params:
    return Params(tz_offset_hours=args.tz_offset,
                  session_filter_enable=args.ny_session,
                  sess_start_hr=args.session_start_hr,
                  sess_end_hr=args.session_end_hr)


def execution_from_args(args) -> ExecutionSettings:
    return ExecutionSettings(
        capital=args.capital,
        start_ts=parse_timestamp(args.start),
        end_ts=parse_timestamp(args.end),
        ruin_floor=args.ruin_floor,
        flatten_before_gaps=not args.no_gap_flat,
        gap_warmup_bars=args.gap_warmup,
    )


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    palette = Palette()
    series = load_series(args.data, args.hole_hours)
    run_backtest(
        series,
        params_from_args(args),
        execution_from_args(args),
        OutputSettings(results_path=args.results, chart_path=args.chart_out,
                       chart_days=args.chart_days),
        ConsoleObserver(print_every=args.print_every, quiet=args.quiet,
                        palette=palette),
    )
    print(palette.bold("Done."))
