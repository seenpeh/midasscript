"""Rolling walk-forward optimisation.

Optimise on an in-sample (IS) window, validate on the next out-of-sample (OOS)
window, step forward, and stitch the OOS results together with compounding
capital. The stitched OOS curve — not the full-window fit — is the honest,
overfit-resistant estimate of performance.

Folds are ANCHORED: fold j tunes on every part before part j and validates on
part j, so the in-sample window grows and training data never comes from after
the slice being validated.
"""

from __future__ import annotations

import time as _time
from dataclasses import dataclass

import numpy as np

from ..config.params import Params
from ..engine.statistics import compute_statistics
from ..util.sampling import downsample
from ..util.timeutil import format_day, parse_day
from .config import WARMUP_BARS, WalkForwardConfig
from .objective import Evaluator, Objective
from .space import TRIGGER_GROUPS, build_params, suggest_values

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
except ImportError:                                   # pragma: no cover
    optuna = None

EQUITY_CURVE_POINTS = 1500


# ---------------------------------------------------------------------------
# Data preparation
# ---------------------------------------------------------------------------
def prepare_series(series, base_start_ts, base_end_ts=None,
                   warmup_bars: int = WARMUP_BARS):
    """Trim to [base_start - warmup, base_end].

    Trading starts at base_start, but the EMAs need history, so a warm-up buffer
    is kept in front of it. Indicators are backward-looking, so trimming the tail
    beyond the tuning end is safe — and computing signals on a short slice is
    roughly ten times faster with identical results.
    """
    first = max(0, series.index_at(base_start_ts) - warmup_bars)
    last = None
    if base_end_ts:
        last = min(len(series), series.index_at(base_end_ts, side="right") + 2)
    return series.slice(first, last)


def make_folds(base_ts: int, end_ts: int, n_parts: int) -> list:
    """Split [base_ts, end_ts] into n equal-time parts -> n-1 anchored folds."""
    parts = int(n_parts)
    if parts < 2:
        raise RuntimeError("parts (n) must be >= 2")
    total = end_ts - base_ts
    if total <= 0:
        raise RuntimeError("empty date range (base_end <= base_start)")
    edges = [base_ts + (total * k) // parts for k in range(parts + 1)]
    return [{"is": (edges[0], edges[j]), "oos": (edges[j], edges[j + 1])}
            for j in range(1, parts)]


def resolve_end(config: WalkForwardConfig, series) -> int:
    """End of the tuning window: base_end, else an explicit end_ts, else the data."""
    if config.base_end:
        return parse_day(config.base_end)
    if config.end_ts:
        return int(config.end_ts)
    return series.end


# ---------------------------------------------------------------------------
# The study
# ---------------------------------------------------------------------------
class WalkForwardOptimizer:
    """Owns one optimisation run: the folds, the sampler, and the report."""

    def __init__(self, series, config: WalkForwardConfig, progress=None):
        if optuna is None:
            raise RuntimeError("optuna not installed")
        self.series = series
        self.config = config
        self.progress = progress or (lambda update: None)
        self.evaluator = Evaluator(series, config.capital, config.ruin_floor)
        self.base_ts = parse_day(config.base_start)
        self.end_ts = resolve_end(config, series)
        self.folds = make_folds(self.base_ts, self.end_ts, config.n_parts)
        self._trials_done = 0
        self._trials_total = len(self.folds) * config.trials + config.final_trials

    # -- public ------------------------------------------------------------
    def run(self) -> dict:
        fold_reports, stitched = self._walk_folds()
        recommended, final_score, final_stats = self._final_fit()
        return self._report(fold_reports, stitched, recommended, final_score, final_stats)

    def estimate_seconds(self) -> dict:
        """Time one evaluation, then multiply by the number the run will need."""
        is_start, is_end = self.folds[0]["is"]
        params = Params()
        self.evaluator.run(params, is_start, is_end)          # warm up
        samples = []
        for _ in range(2):
            started = _time.time()
            self.evaluator.run(params, is_start, is_end)
            samples.append(_time.time() - started)
        per_eval = float(np.median(samples))
        # + the per-fold IS/OOS confirmation runs (2 per fold) and the final one
        total_evals = self._trials_total + 2 * len(self.folds) + 1
        return {"per_eval_s": round(per_eval, 3), "n_folds": len(self.folds),
                "total_evals": int(total_evals),
                "est_seconds": round(per_eval * total_evals, 1)}

    # -- steps -------------------------------------------------------------
    def _walk_folds(self):
        reports = []
        capital = self.config.capital
        trades, equity_points = [], []
        oos_span = None

        for index, fold in enumerate(self.folds):
            is_start, is_end = fold["is"]
            oos_start, oos_end = fold["oos"]
            self.progress({"phase": "fold", "fold": index + 1, "folds": len(self.folds),
                           "msg": f"optimising fold {index+1}/{len(self.folds)}"})

            best_values, best_score = self._optimise(
                is_start, is_end, self.config.min_trades_fold, self.config.trials,
                self.config.seed + index)
            params = self._params_from(best_values)

            is_stats, _ = self.evaluator.run(params, is_start, is_end)
            oos_stats, oos_result = self.evaluator.run(params, oos_start, oos_end,
                                                       capital=capital)
            trades.extend(oos_result.trades)
            equity_points.extend(oos_result.equity_points)
            oos_span = [oos_start, oos_end] if oos_span is None else [oos_span[0], oos_end]
            capital = oos_result.final_equity

            reports.append(self._fold_report(index, fold, best_values, best_score,
                                             is_stats, oos_stats))

        stitched = {"trades": trades, "equity_points": equity_points,
                    "span": oos_span, "final_capital": capital}
        return reports, stitched

    def _final_fit(self):
        """The deployable fit: one more optimisation over the WHOLE window."""
        self.progress({"phase": "final", "msg": "final fit on full window"})
        best_values, score = self._optimise(
            self.base_ts, self.end_ts, self.config.min_trades_final,
            self.config.final_trials, self.config.seed + 999)
        params = self._params_from(best_values)
        stats, _ = self.evaluator.run(params, self.base_ts, self.end_ts)
        return {"values": best_values, "params": params}, score, stats

    def _optimise(self, start_ts, end_ts, min_trades, trials, seed):
        objective = Objective(min_trades, self.config.max_dd_pct,
                              self.config.objective_metric)
        sampler = optuna.samplers.TPESampler(seed=seed,
                                             n_startup_trials=min(15, trials))
        study = optuna.create_study(direction="maximize", sampler=sampler)

        def run_trial(trial):
            values = suggest_values(trial, self.config.groups)
            stats, _ = self.evaluator.run(self._params_from(values), start_ts, end_ts)
            trial.set_user_attr("ret", round(stats.get("return_pct", 0.0), 2))
            trial.set_user_attr("dd", round(stats.get("max_drawdown_pct", 0.0), 2))
            trial.set_user_attr("trades", stats.get("total_trades", 0))
            self._tick()
            return objective.score(stats)

        study.optimize(run_trial, n_trials=trials, show_progress_bar=False)
        return study.best_params, study.best_value

    def _params_from(self, values) -> Params:
        # A fresh copy of the base parameters every time, so a trial's mutations
        # can never leak into the next one.
        base = Params.from_dict(self.config.base_params)
        return build_params(values, base=base, groups=self.config.groups)

    def _tick(self):
        self._trials_done += 1
        self.progress({"phase": "running", "trials_done": self._trials_done,
                       "trials_total": self._trials_total,
                       "pct": round(100 * self._trials_done / self._trials_total, 1)})

    # -- reporting ---------------------------------------------------------
    def _fold_report(self, index, fold, values, score, is_stats, oos_stats) -> dict:
        is_start, is_end = fold["is"]
        oos_start, oos_end = fold["oos"]
        loose = Objective(0, self.config.max_dd_pct, self.config.objective_metric)
        return {
            "fold": index + 1,
            "is_start": format_day(is_start), "is_end": format_day(is_end),
            "oos_start": format_day(oos_start), "oos_end": format_day(oos_end),
            "params": values,
            "is_score": round(score, 4),
            "is_return_pct": is_stats.get("return_pct"),
            "is_dd_pct": is_stats.get("max_drawdown_pct"),
            "is_trades": is_stats.get("total_trades"),
            "oos_return_pct": oos_stats.get("return_pct"),
            "oos_dd_pct": oos_stats.get("max_drawdown_pct"),
            "oos_trades": oos_stats.get("total_trades"),
            "oos_ruined": bool(oos_stats.get("ruined")),
            "oos_score": round(loose.score(oos_stats), 4),
            "oos_sharpe": oos_stats.get("sharpe"),
            "oos_sortino": oos_stats.get("sortino"),
            "oos_calmar": oos_stats.get("calmar"),
        }

    def _report(self, fold_reports, stitched, recommended, final_score, final_stats) -> dict:
        config = self.config
        span = stitched["span"]
        first = self.series.index_at(span[0])
        last = self.series.index_at(span[1], side="right")
        oos_stats = compute_statistics(
            stitched["trades"], stitched["equity_points"], config.capital,
            stitched["final_capital"] - config.capital, self.series.epoch,
            first, max(last, first + 1))

        curve = [[int(self.series.epoch[first]), round(config.capital, 2)]]
        curve += [[int(t), round(equity, 2)] for t, equity in stitched["equity_points"]]

        return {
            "config": self._config_block(),
            "folds": fold_reports,
            "wf_oos": {
                "start": format_day(span[0]), "end": format_day(span[1]),
                **{key: oos_stats.get(key) for key in
                   ("return_pct", "cagr_pct", "max_drawdown_pct", "profit_factor",
                    "win_rate", "sharpe", "sortino", "calmar", "total_trades",
                    "final_equity")},
                "equity_curve": downsample(curve, EQUITY_CURVE_POINTS),
            },
            "wf_efficiency": _efficiency(fold_reports),
            "recommended": {
                "params": recommended["params"].as_dict(),
                "optimised_values": recommended["values"],
                "score": round(final_score, 4),
                "in_sample_full": {
                    **{key: final_stats.get(key) for key in
                       ("return_pct", "cagr_pct", "max_drawdown_pct",
                        "profit_factor", "win_rate", "total_trades")},
                    "ruined": bool(final_stats.get("ruined")),
                },
            },
        }

    def _config_block(self) -> dict:
        config = self.config
        objective = Objective(config.min_trades_final, config.max_dd_pct,
                              config.objective_metric)
        return {
            **{key: getattr(config, key) for key in
               ("groups", "trials", "final_trials", "n_parts", "base_start",
                "capital", "ruin_floor", "min_trades_fold", "min_trades_final",
                "max_dd_pct", "objective_metric")},
            "objective": objective.describe(config.min_trades_final),
            "base_end": config.base_end or "(data end)",
            "data_end": format_day(self.end_ts),
            "n_folds": len(self.folds),
            "non_tuned_from": "edit settings" if config.base_params else "strategy defaults",
            "active_triggers": [t.upper() for t in TRIGGER_GROUPS
                                if t in config.groups] or ["T1", "T2", "T3"],
        }


def _efficiency(fold_reports):
    """Median OOS/IS return ratio — how much of the fit survived validation."""
    ratios = [f["oos_return_pct"] / f["is_return_pct"] for f in fold_reports
              if f["is_return_pct"] and f["is_return_pct"] > 0]
    return round(float(np.median(ratios)), 3) if ratios else None
