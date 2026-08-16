"""
optimize.py
===========
Walk-forward Bayesian (Optuna/TPE) optimisation of the UltScript strategy.

Design (expert-quant defaults):
  * Trade only from --base-start (default 2024-01-01). The past is ignored for
    trading, but signals/EMAs are warmed up on a ~30k-bar buffer before it, so
    we can compute on a short slice (~10x faster) with identical results.
  * Objective = STABILISED MAR:  CAGR% / (MaxDD% + 5), with HARD REJECTS for
    ruin, < min trades, and non-positive return. This rewards growth while
    punishing the drawdown that geometric sizing + pyramiding create.
  * Rolling WALK-FORWARD: optimise on an in-sample (IS) window, validate on the
    next out-of-sample (OOS) window, step forward, stitch the OOS results with
    compounding capital. The stitched OOS curve is the honest, overfit-resistant
    estimate of performance.
  * Triggers T1/T2/T3 share one knob per concept (risk, RR, thresholds) to keep
    the search low-dimensional.

Outputs opt_results.json. Also importable by serve.py for the HTML UI.

CLI:
    python3 optimize.py --groups risk_exposure rr signal --trials 80
"""
from __future__ import annotations

import argparse
import json
import time as _time
from datetime import datetime, timezone

import numpy as np

import backtest as B
import strategy as S

try:
    import optuna
    optuna.logging.set_verbosity(optuna.logging.WARNING)
except ImportError:
    optuna = None


GROUPS = ["t1", "t2", "t3", "exposure", "trend", "dynsl"]
TRIGGER_GROUPS = ["t1", "t2", "t3"]
WARMUP_BARS = 30000          # bars kept before base_start for EMA warm-up
MAR_STABILISER = 5.0         # MaxDD% offset so tiny-DD flukes don't blow up MAR


# ---------------------------------------------------------------------------
# date helpers
# ---------------------------------------------------------------------------
def to_ts(s):
    return int(datetime.strptime(s, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())

def ts_to_str(ts):
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")

def add_months(ts, months):
    d = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    return int(d.replace(year=y, month=m).timestamp())


# ---------------------------------------------------------------------------
# data prep — slice to [base_start - warmup, end]
# ---------------------------------------------------------------------------
def prepare_arrays(full, base_start_ts, base_end_ts=None, warmup_bars=WARMUP_BARS):
    epoch, o, h, l, c, v = full
    i_base = int(np.searchsorted(epoch, base_start_ts))
    i0 = max(0, i_base - warmup_bars)
    # upper slice at base_end (indicators are backward-looking, so trimming the
    # tail beyond the tuning end is safe and speeds up signal computation)
    i1 = None
    if base_end_ts:
        i1 = min(len(epoch), int(np.searchsorted(epoch, base_end_ts, side="right")) + 2)
    sl = slice(i0, i1)
    return (epoch[sl], o[sl], h[sl], l[sl], c[sl], v[sl])


# ---------------------------------------------------------------------------
# parameter space
# ---------------------------------------------------------------------------
def suggest_values(trial, groups):
    """Each TRIGGER (t1/t2/t3) is optimised independently — its own n, TR mult,
    lookback m, RR primary/alt and risk%. 'exposure' (pyramiding, daily-loss-
    limit) and 'trend' (EMAs) are global."""
    v = {}
    if "exposure" in groups:
        v["pyramiding"] = trial.suggest_int("pyramiding", 1, 25)
        v["dll_loss_pct"] = trial.suggest_float("dll_loss_pct", 2.0, 12.0, step=0.5)
    if "dynsl" in groups:
        # dynamic stop loss (kept enabled via Params default when this group is
        # optimised): cap the stop distance at max_size_candle*avg_body, then
        # tighten oversized stops by min_stop_loss_ratio percent. The enable flag
        # itself is NOT tuned — only these two knobs are.
        v["max_size_candle"] = trial.suggest_float("max_size_candle", 1.0, 8.0, step=0.5)
        v["min_stop_loss_ratio"] = trial.suggest_float("min_stop_loss_ratio", 5.0, 60.0, step=5.0)
    for t in TRIGGER_GROUPS:
        if t in groups:
            v[f"{t}_n"] = trial.suggest_float(f"{t}_n", 1.0, 4.0, step=0.1)
            v[f"{t}_tr_mult"] = trial.suggest_float(f"{t}_tr_mult", 0.0, 1.5, step=0.1)
            v[f"{t}_m"] = trial.suggest_int(f"{t}_m", 2, 10)
            v[f"{t}_rr_pri"] = trial.suggest_float(f"{t}_rr_pri", 1.0, 4.0, step=0.25)
            v[f"{t}_rr_alt"] = trial.suggest_float(f"{t}_rr_alt", 1.0, 5.0, step=0.25)
            v[f"{t}_risk"] = trial.suggest_float(f"{t}_risk", 0.25, 2.5, step=0.25)
            if t == "t2":
                v["t2_c"] = trial.suggest_int("t2_c", 2, 6)
    if "trend" in groups:
        ef = trial.suggest_int("ema_fast", 100, 600)
        v["ema_fast"] = ef
        v["ema_slow"] = trial.suggest_int("ema_slow", ef + 150, 2600)
    return v


def params_from_dict(d):
    """Fresh S.Params() seeded from a dict (e.g. the UI's current edit settings),
    casting each value to the field's existing type. Unknown keys ignored."""
    p = S.Params()
    for k, val in (d or {}).items():
        if not hasattr(p, k):
            continue
        cur = getattr(p, k)
        try:
            if isinstance(cur, bool):    val = bool(val)
            elif isinstance(cur, int):   val = int(val)
            elif isinstance(cur, float): val = float(val)
        except (TypeError, ValueError):
            continue
        setattr(p, k, val)
    return p


def apply_named(values, base=None, groups=None):
    """Build a Params from a flat dict of per-trigger optimised values.

    If `groups` includes any trigger group, ONLY those triggers stay enabled so
    each trigger is optimised in isolation (others disabled for the run)."""
    p = base or S.Params()
    if "pyramiding" in values:
        p.pyramiding = int(values["pyramiding"])
    if "dll_loss_pct" in values:
        p.dll_loss_pct = float(values["dll_loss_pct"])
    if "dyn_sl_enable" in values:
        p.dyn_sl_enable = bool(values["dyn_sl_enable"])
    if "max_size_candle" in values:
        p.max_size_candle = float(values["max_size_candle"])
    if "min_stop_loss_ratio" in values:
        p.min_stop_loss_ratio = float(values["min_stop_loss_ratio"])
    for t in TRIGGER_GROUPS:
        for f in ("n", "tr_mult", "rr_pri", "rr_alt", "risk"):
            k = f"{t}_{f}"
            if k in values:
                setattr(p, k, float(values[k]))
        if f"{t}_m" in values:
            setattr(p, f"{t}_m", int(values[f"{t}_m"]))
    if "t2_c" in values:
        p.t2_c = int(values["t2_c"])
    if "ema_fast" in values:
        p.ema_fast_len = int(values["ema_fast"])
    if "ema_slow" in values:
        p.ema_slow_len = int(values["ema_slow"])
    # isolation: enable only the selected triggers (if any were selected)
    if groups is not None:
        tg = [g for g in TRIGGER_GROUPS if g in groups]
        if tg:
            p.t1_en = "t1" in groups
            p.t2_en = "t2" in groups
            p.t3_en = "t3" in groups
    return p


# ---------------------------------------------------------------------------
# evaluation + objective
# ---------------------------------------------------------------------------
def evaluate(arrays, params, capital, start_ts, end_ts, ruin_floor):
    epoch, o, h, l, c, v = arrays
    closed, eqpts, initial, realized, ruin, i0, i1 = B.run(
        epoch, o, h, l, c, v, params, capital,
        quiet=True, log=False, ruin_floor=ruin_floor,
        start_ts=start_ts, end_ts=end_ts)
    stats = B.compute_stats(closed, eqpts, initial, realized, epoch, i0, i1)
    if ruin:
        stats["ruined"] = True
    return stats, closed, eqpts, initial + realized


OBJECTIVES = {"sharpe": "Sharpe ratio", "sortino": "Sortino ratio",
              "calmar": "Calmar ratio (CAGR / MaxDD)"}


def score_from_stats(stats, min_trades, dd_cap, objective="calmar"):
    """Maximise the chosen risk-adjusted ratio under a HARD drawdown cap.

    Why a cap: with geometric sizing + pyramiding, returns compound explosively,
    so even ratio objectives can drift toward near-ruin configs. Constraining
    MaxDD <= dd_cap and maximising the ratio *within* that feasible region is the
    standard risk-controlled approach. Rejected regions return graded values so
    TPE climbs toward feasibility."""
    n = stats.get("total_trades", 0)
    if n == 0:
        return -10.0
    if stats.get("ruined"):
        return -8.0
    if n < min_trades:
        return -5.0 + n / max(min_trades, 1)          # nudge toward more trades
    ret = stats.get("return_pct", 0.0)
    if ret <= 0:
        return -1.0 + ret / 10000.0                   # ranked, but below feasible
    dd = stats.get("max_drawdown_pct", 0.0)
    if dd > dd_cap:
        # over the risk budget -> infeasible, but prefer being closer to the cap
        return -0.5 * (dd / dd_cap)
    val = stats.get(objective)
    if val is None:
        val = stats.get("calmar", 0.0)
    return float(val)


# ---------------------------------------------------------------------------
# walk-forward
# ---------------------------------------------------------------------------
def _resolve_end(cfg, epoch):
    """End of the tuning window: base_end if given, else explicit end_ts, else
    the last bar in the data."""
    if cfg.get("base_end"):
        return to_ts(cfg["base_end"])
    if cfg.get("end_ts"):
        return int(cfg["end_ts"])
    return int(epoch[-1])


def make_folds(base_ts, end_ts, n_parts):
    """Split [base_ts, end_ts] into n equal-time parts and build ANCHORED
    walk-forward folds: fold j tunes on every part BEFORE part j and validates on
    part j (for j = 1 .. n-1, zero-indexed). Anchored = the in-sample window grows
    each fold; strictly time-ordered, so we never train on data that comes after
    the out-of-sample slice (no lookahead). n parts -> n-1 OOS folds."""
    n = int(n_parts)
    if n < 2:
        raise RuntimeError("parts (n) must be >= 2")
    total = end_ts - base_ts
    if total <= 0:
        raise RuntimeError("empty date range (base_end <= base_start)")
    edges = [base_ts + (total * k) // n for k in range(n + 1)]
    return [{"is": (edges[0], edges[j]), "oos": (edges[j], edges[j + 1])}
            for j in range(1, n)]


def _optimise_window(arrays, groups, capital, start_ts, end_ts, ruin_floor,
                     min_trades, dd_cap, objective, trials, seed, on_trial=None,
                     base_params=None):
    sampler = optuna.samplers.TPESampler(seed=seed, n_startup_trials=min(15, trials))
    study = optuna.create_study(direction="maximize", sampler=sampler)

    def obj(trial):
        vals = suggest_values(trial, groups)
        # non-tuned params come from the UI's current edit settings (fresh copy
        # each trial so mutations never leak between trials)
        p = apply_named(vals, base=params_from_dict(base_params), groups=groups)
        stats, *_ = evaluate(arrays, p, capital, start_ts, end_ts, ruin_floor)
        trial.set_user_attr("ret", round(stats.get("return_pct", 0.0), 2))
        trial.set_user_attr("dd", round(stats.get("max_drawdown_pct", 0.0), 2))
        trial.set_user_attr("trades", stats.get("total_trades", 0))
        if on_trial:
            on_trial()
        return score_from_stats(stats, min_trades, dd_cap, objective)

    study.optimize(obj, n_trials=trials, show_progress_bar=False)
    return study.best_params, study.best_value


def run_walkforward(arrays, cfg, progress=None):
    """cfg keys: groups, trials, final_trials, n_parts, base_start, end_ts,
    capital, ruin_floor, min_trades_fold, min_trades_final, seed."""
    if optuna is None:
        raise RuntimeError("optuna not installed")

    epoch = arrays[0]
    base_ts = to_ts(cfg["base_start"])
    end_ts = _resolve_end(cfg, epoch)
    folds = make_folds(base_ts, end_ts, cfg["n_parts"])
    if not folds:
        raise RuntimeError("no walk-forward folds; need parts (n) >= 2")

    capital = cfg["capital"]
    ruin_floor = cfg["ruin_floor"]
    dd_cap = cfg["max_dd_pct"]
    objective = cfg.get("objective_metric", "calmar")
    base_params = cfg.get("base_params")    # UI edit settings; non-tuned params come from here
    trials = cfg["trials"]
    total_trials = len(folds) * trials + cfg["final_trials"]
    done = {"n": 0}

    def tick():
        done["n"] += 1
        if progress:
            progress({"phase": "running", "trials_done": done["n"],
                      "trials_total": total_trials,
                      "pct": round(100 * done["n"] / total_trials, 1)})

    # ---- per-fold optimise on IS, validate on OOS (compounding capital) ----
    fold_reports = []
    run_cap = capital
    wf_closed, wf_eqpts = [], []
    oos_span = None
    for k, fold in enumerate(folds):
        is0, is1 = fold["is"]; oo0, oo1 = fold["oos"]
        if progress:
            progress({"phase": "fold", "fold": k + 1, "folds": len(folds),
                      "msg": f"optimising fold {k+1}/{len(folds)}"})
        best, best_score = _optimise_window(
            arrays, cfg["groups"], capital, is0, is1, ruin_floor,
            cfg["min_trades_fold"], dd_cap, objective, trials,
            cfg["seed"] + k, on_trial=tick, base_params=base_params)
        bp = apply_named(best, base=params_from_dict(base_params), groups=cfg["groups"])
        is_stats, *_ = evaluate(arrays, bp, capital, is0, is1, ruin_floor)
        oos_stats, oos_closed, oos_eqpts, oos_final = evaluate(
            arrays, bp, run_cap, oo0, oo1, ruin_floor)

        wf_closed.extend(oos_closed)
        wf_eqpts.extend(oos_eqpts)
        if oos_span is None:
            oos_span = [oo0, oo1]
        else:
            oos_span[1] = oo1
        run_cap = oos_final

        fold_reports.append({
            "fold": k + 1,
            "is_start": ts_to_str(is0), "is_end": ts_to_str(is1),
            "oos_start": ts_to_str(oo0), "oos_end": ts_to_str(oo1),
            "params": best,
            "is_score": round(best_score, 4),
            "is_return_pct": is_stats.get("return_pct"),
            "is_dd_pct": is_stats.get("max_drawdown_pct"),
            "is_trades": is_stats.get("total_trades"),
            "oos_return_pct": oos_stats.get("return_pct"),
            "oos_dd_pct": oos_stats.get("max_drawdown_pct"),
            "oos_trades": oos_stats.get("total_trades"),
            "oos_ruined": bool(oos_stats.get("ruined")),
            "oos_score": round(score_from_stats(oos_stats, 0, dd_cap, objective), 4),
            "oos_sharpe": oos_stats.get("sharpe"),
            "oos_sortino": oos_stats.get("sortino"),
            "oos_calmar": oos_stats.get("calmar"),
        })

    # ---- stitched OOS aggregate ----
    i0 = int(np.searchsorted(epoch, oos_span[0]))
    i1 = int(np.searchsorted(epoch, oos_span[1], side="right"))
    wf_oos_stats = B.compute_stats(wf_closed, wf_eqpts, capital,
                                   run_cap - capital, epoch, i0, max(i1, i0 + 1))
    wf_equity_curve = _downsample([[int(epoch[i0]), round(capital, 2)]] +
                                  [[int(t), round(e, 2)] for t, e in wf_eqpts], 1500)

    # ---- WF efficiency (OOS vs IS return, median across folds) ----
    effs = [f["oos_return_pct"] / f["is_return_pct"]
            for f in fold_reports
            if f["is_return_pct"] and f["is_return_pct"] > 0]
    wf_eff = round(float(np.median(effs)), 3) if effs else None

    # ---- final deployable fit on the WHOLE tradable window ----
    if progress:
        progress({"phase": "final", "msg": "final fit on full window"})
    final_best, final_score = _optimise_window(
        arrays, cfg["groups"], capital, base_ts, end_ts, ruin_floor,
        cfg["min_trades_final"], dd_cap, objective, cfg["final_trials"],
        cfg["seed"] + 999, on_trial=tick, base_params=base_params)
    final_params_obj = apply_named(final_best, base=params_from_dict(base_params), groups=cfg["groups"])
    final_stats, *_ = evaluate(arrays, final_params_obj, capital, base_ts, end_ts, ruin_floor)

    return {
        "config": {**{k: cfg[k] for k in
                      ("groups", "trials", "final_trials", "n_parts",
                       "base_start", "capital",
                       "ruin_floor", "min_trades_fold", "min_trades_final",
                       "max_dd_pct")},
                   "objective_metric": objective,
                   "objective": f"max {OBJECTIVES.get(objective, objective)} "
                                f"s.t. MaxDD<={cfg['max_dd_pct']}%, no ruin, "
                                f">={cfg['min_trades_final']} trades",
                   "base_end": cfg.get("base_end") or "(data end)",
                   "data_end": ts_to_str(end_ts), "n_folds": len(folds),
                   "non_tuned_from": "edit settings" if base_params else "strategy defaults",
                   "active_triggers": [t.upper() for t in TRIGGER_GROUPS
                                       if t in cfg["groups"]] or ["T1", "T2", "T3"]},
        "folds": fold_reports,
        "wf_oos": {
            "start": ts_to_str(oos_span[0]), "end": ts_to_str(oos_span[1]),
            "return_pct": wf_oos_stats.get("return_pct"),
            "cagr_pct": wf_oos_stats.get("cagr_pct"),
            "max_drawdown_pct": wf_oos_stats.get("max_drawdown_pct"),
            "profit_factor": wf_oos_stats.get("profit_factor"),
            "win_rate": wf_oos_stats.get("win_rate"),
            "sharpe": wf_oos_stats.get("sharpe"),
            "sortino": wf_oos_stats.get("sortino"),
            "calmar": wf_oos_stats.get("calmar"),
            "total_trades": wf_oos_stats.get("total_trades"),
            "final_equity": wf_oos_stats.get("final_equity"),
            "equity_curve": wf_equity_curve,
        },
        "wf_efficiency": wf_eff,
        "recommended": {
            "params": _full_params_dict(final_params_obj),
            "optimised_values": final_best,
            "score": round(final_score, 4),
            "in_sample_full": {
                "return_pct": final_stats.get("return_pct"),
                "cagr_pct": final_stats.get("cagr_pct"),
                "max_drawdown_pct": final_stats.get("max_drawdown_pct"),
                "profit_factor": final_stats.get("profit_factor"),
                "win_rate": final_stats.get("win_rate"),
                "total_trades": final_stats.get("total_trades"),
                "ruined": bool(final_stats.get("ruined")),
            },
        },
    }


def _full_params_dict(p: S.Params):
    return {k: getattr(p, k) for k in vars(p)}


def _downsample(pts, maxn):
    if len(pts) <= maxn:
        return pts
    step = len(pts) / maxn
    idx = sorted(set(int(i * step) for i in range(maxn)) | {len(pts) - 1})
    return [pts[i] for i in idx]


# ---------------------------------------------------------------------------
# time estimate
# ---------------------------------------------------------------------------
def estimate_seconds(arrays, cfg):
    base_ts = to_ts(cfg["base_start"])
    end_ts = _resolve_end(cfg, arrays[0])
    folds = make_folds(base_ts, end_ts, cfg["n_parts"])
    if not folds:
        return {"error": "no folds; need parts (n) >= 2"}
    p = S.Params()
    is0, is1 = folds[0]["is"]
    # one warm-up call (caches nothing, but measure steady state), then median of 2
    evaluate(arrays, p, cfg["capital"], is0, is1, cfg["ruin_floor"])
    samples = []
    for _ in range(2):
        t = _time.time()
        evaluate(arrays, p, cfg["capital"], is0, is1, cfg["ruin_floor"])
        samples.append(_time.time() - t)
    per = float(np.median(samples))
    total = len(folds) * cfg["trials"] + cfg["final_trials"]
    # + per-fold IS/OOS confirm evaluations (2 per fold)
    total_evals = total + 2 * len(folds) + 1
    secs = per * total_evals
    return {"per_eval_s": round(per, 3), "n_folds": len(folds),
            "total_evals": int(total_evals), "est_seconds": round(secs, 1)}


# ---------------------------------------------------------------------------
def default_cfg(**over):
    cfg = dict(groups=["t1", "t2", "t3", "exposure"], trials=80, final_trials=120,
               n_parts=5, base_start="2024-01-01",
               base_end=None, end_ts=None, capital=10000.0, ruin_floor=0.01,
               min_trades_fold=15, min_trades_final=60, max_dd_pct=30.0,
               objective_metric="calmar", base_params=None, seed=42)
    cfg.update(over)
    return cfg


def main():
    ap = argparse.ArgumentParser(description="Walk-forward Optuna optimisation.")
    ap.add_argument("--data", default="5m_candles.json")
    ap.add_argument("--groups", nargs="+", default=["t1", "t2", "t3", "exposure"],
                    choices=GROUPS,
                    help="t1/t2/t3 optimise each trigger independently (others "
                         "disabled in isolation); exposure=pyramiding+DLL; trend=EMAs")
    ap.add_argument("--trials", type=int, default=80)
    ap.add_argument("--final-trials", type=int, default=120)
    ap.add_argument("--parts", type=int, default=5,
                    help="split the tuning range into n equal parts; anchored "
                         "walk-forward gives n-1 OOS folds")
    ap.add_argument("--base-start", default="2024-01-01")
    ap.add_argument("--base-end", default=None,
                    help="end of tuning window (YYYY-MM-DD); empty = no end (data end)")
    ap.add_argument("--objective", default="calmar", choices=list(OBJECTIVES),
                    help="risk-adjusted metric to maximise")
    ap.add_argument("--capital", type=float, default=10000.0)
    ap.add_argument("--max-dd", type=float, default=30.0,
                    help="hard max-drawdown%% cap; configs above it are infeasible")
    ap.add_argument("--out", default="opt_results.json")
    ap.add_argument("--estimate-only", action="store_true")
    args = ap.parse_args()

    if optuna is None:
        raise SystemExit("optuna is not installed (pip install optuna).")

    full = B.load_candles(args.data)
    cfg = default_cfg(groups=args.groups, trials=args.trials,
                      final_trials=args.final_trials, n_parts=args.parts,
                      base_start=args.base_start, base_end=args.base_end,
                      capital=args.capital, max_dd_pct=args.max_dd,
                      objective_metric=args.objective)
    arrays = prepare_arrays(full, to_ts(args.base_start),
                            to_ts(args.base_end) if args.base_end else None)

    est = estimate_seconds(arrays, cfg)
    print(f"Estimate: {est}")
    if args.estimate_only:
        return

    print(f"Optimising groups={args.groups} ... (~{est['est_seconds']/60:.1f} min)")
    t0 = _time.time()
    res = run_walkforward(arrays, cfg,
                          progress=lambda d: print("  ", d) if d.get("phase") in
                          ("fold", "final") else None)
    res["elapsed_s"] = round(_time.time() - t0, 1)
    with open(args.out, "w") as f:
        json.dump(res, f, indent=2)
    print(f"\nDone in {res['elapsed_s']}s -> {args.out}")
    wf = res["wf_oos"]
    print(f"\n=== WALK-FORWARD OOS (the honest estimate) ===")
    print(f"  period   {wf['start']} -> {wf['end']}")
    print(f"  return   {wf['return_pct']}%   CAGR {wf['cagr_pct']}%")
    print(f"  max DD   {wf['max_drawdown_pct']}%   PF {wf['profit_factor']}   "
          f"trades {wf['total_trades']}   WF-eff {res['wf_efficiency']}")
    rec = res["recommended"]
    print(f"\n=== RECOMMENDED (full-window fit) ===")
    print(f"  score {rec['score']}  {rec['optimised_values']}")
    print(f"  in-sample full: {rec['in_sample_full']}")


if __name__ == "__main__":
    main()
