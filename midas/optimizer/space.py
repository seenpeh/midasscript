"""The search space: which knobs Optuna may turn, and how a trial becomes Params.

Each TRIGGER (t1/t2/t3) is tuned independently — its own thresholds, lookback,
risk:reward and risk%. `exposure` (pyramiding, daily-loss limit), `trend` (the
EMAs) and `dynsl` (the dynamic stop) are global.

Every suggested name is a `Params` field name, except the two EMA lengths, so
building the parameter object is a rename plus `Params.from_dict` rather than a
hand-written assignment per knob.
"""

from __future__ import annotations

from ..config.params import Params

GROUPS = ["t1", "t2", "t3", "exposure", "trend", "dynsl"]
TRIGGER_GROUPS = ["t1", "t2", "t3"]

# Optuna knob name -> Params field, where the two differ.
FIELD_ALIASES = {"ema_fast": "ema_fast_len", "ema_slow": "ema_slow_len"}


def suggest_values(trial, groups) -> dict:
    """One Optuna trial -> a flat dict of proposed values."""
    values = {}
    if "exposure" in groups:
        values["pyramiding"] = trial.suggest_int("pyramiding", 1, 25)
        values["dll_loss_pct"] = trial.suggest_float("dll_loss_pct", 2.0, 12.0, step=0.5)
    if "dynsl" in groups:
        # Cap the stop distance at max_size_candle*avg_body, then tighten
        # oversized stops by min_stop_loss_ratio percent. The enable flag itself
        # is NOT tuned — it stays wherever the base parameters put it.
        values["max_size_candle"] = trial.suggest_float("max_size_candle", 1.0, 8.0, step=0.5)
        values["min_stop_loss_ratio"] = trial.suggest_float("min_stop_loss_ratio", 5.0, 60.0, step=5.0)
    for trigger in TRIGGER_GROUPS:
        if trigger not in groups:
            continue
        values[f"{trigger}_n"] = trial.suggest_float(f"{trigger}_n", 1.0, 4.0, step=0.1)
        values[f"{trigger}_tr_mult"] = trial.suggest_float(f"{trigger}_tr_mult", 0.0, 1.5, step=0.1)
        values[f"{trigger}_m"] = trial.suggest_int(f"{trigger}_m", 2, 10)
        values[f"{trigger}_rr_pri"] = trial.suggest_float(f"{trigger}_rr_pri", 1.0, 4.0, step=0.25)
        values[f"{trigger}_rr_alt"] = trial.suggest_float(f"{trigger}_rr_alt", 1.0, 5.0, step=0.25)
        values[f"{trigger}_risk"] = trial.suggest_float(f"{trigger}_risk", 0.25, 2.5, step=0.25)
        if trigger == "t2":
            values["t2_c"] = trial.suggest_int("t2_c", 2, 6)
    if "trend" in groups:
        fast = trial.suggest_int("ema_fast", 100, 600)
        values["ema_fast"] = fast
        values["ema_slow"] = trial.suggest_int("ema_slow", fast + 150, 2600)
    return values


def build_params(values: dict, base: Params | None = None, groups=None) -> Params:
    """A trial's values on top of `base`, with trigger isolation applied.

    If `groups` names any trigger group, ONLY those triggers stay enabled, so
    each trigger is optimised on its own rather than through the noise of the
    other two.
    """
    renamed = {FIELD_ALIASES.get(key, key): value for key, value in (values or {}).items()}
    params = Params.from_dict(renamed, base=base)
    selected = [g for g in TRIGGER_GROUPS if g in (groups or [])]
    if selected:
        params.t1_en = "t1" in selected
        params.t2_en = "t2" in selected
        params.t3_en = "t3" in selected
    return params
