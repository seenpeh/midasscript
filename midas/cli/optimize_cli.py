"""`python3 optimize.py` — walk-forward optimisation from the command line."""

from __future__ import annotations

import argparse
import json
import time as _time

from ..app.loading import load_series
from ..optimizer.config import WalkForwardConfig
from ..optimizer.objective import OBJECTIVES
from ..optimizer.space import GROUPS
from ..optimizer.walkforward import (WalkForwardOptimizer, prepare_series,
                                     optuna)
from ..util.timeutil import parse_day

DEFAULT_GROUPS = ["t1", "t2", "t3", "exposure"]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Walk-forward Optuna optimisation.")
    parser.add_argument("--data", default="5m_candles.json")
    parser.add_argument("--groups", nargs="+", default=DEFAULT_GROUPS, choices=GROUPS,
                        help="t1/t2/t3 optimise each trigger independently (others "
                             "disabled in isolation); exposure=pyramiding+DLL; trend=EMAs")
    parser.add_argument("--trials", type=int, default=80)
    parser.add_argument("--final-trials", type=int, default=120)
    parser.add_argument("--parts", type=int, default=5,
                        help="split the tuning range into n equal parts; anchored "
                             "walk-forward gives n-1 OOS folds")
    parser.add_argument("--base-start", default="2024-01-01")
    parser.add_argument("--base-end", default=None,
                        help="end of tuning window (YYYY-MM-DD); empty = no end (data end)")
    parser.add_argument("--objective", default="calmar", choices=list(OBJECTIVES),
                        help="risk-adjusted metric to maximise")
    parser.add_argument("--capital", type=float, default=10000.0)
    parser.add_argument("--max-dd", type=float, default=30.0,
                        help="hard max-drawdown%% cap; configs above it are infeasible")
    parser.add_argument("--out", default="opt_results.json")
    parser.add_argument("--estimate-only", action="store_true")
    return parser


def config_from_args(args) -> WalkForwardConfig:
    return WalkForwardConfig(
        groups=args.groups, trials=args.trials, final_trials=args.final_trials,
        n_parts=args.parts, base_start=args.base_start, base_end=args.base_end,
        capital=args.capital, max_dd_pct=args.max_dd,
        objective_metric=args.objective)


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    if optuna is None:
        raise SystemExit("optuna is not installed (pip install optuna).")

    config = config_from_args(args)
    series = prepare_series(
        load_series(args.data), parse_day(args.base_start),
        parse_day(args.base_end) if args.base_end else None)

    optimizer = WalkForwardOptimizer(series, config, progress=_print_phase)
    estimate = optimizer.estimate_seconds()
    print(f"Estimate: {estimate}")
    if args.estimate_only:
        return

    print(f"Optimising groups={args.groups} ... (~{estimate['est_seconds']/60:.1f} min)")
    started = _time.time()
    report = optimizer.run()
    report["elapsed_s"] = round(_time.time() - started, 1)
    with open(args.out, "w") as fh:
        json.dump(report, fh, indent=2)
    print(f"\nDone in {report['elapsed_s']}s -> {args.out}")
    _print_report(report)


def _print_phase(update) -> None:
    if update.get("phase") in ("fold", "final"):
        print("  ", update)


def _print_report(report) -> None:
    oos = report["wf_oos"]
    print("\n=== WALK-FORWARD OOS (the honest estimate) ===")
    print(f"  period   {oos['start']} -> {oos['end']}")
    print(f"  return   {oos['return_pct']}%   CAGR {oos['cagr_pct']}%")
    print(f"  max DD   {oos['max_drawdown_pct']}%   PF {oos['profit_factor']}   "
          f"trades {oos['total_trades']}   WF-eff {report['wf_efficiency']}")
    recommended = report["recommended"]
    print("\n=== RECOMMENDED (full-window fit) ===")
    print(f"  score {recommended['score']}  {recommended['optimised_values']}")
    print(f"  in-sample full: {recommended['in_sample_full']}")
