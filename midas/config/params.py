"""Strategy parameters — one dataclass, one place that turns untrusted input
into a valid instance of it.

The HTTP layer and the optimizer both receive parameter dictionaries from
outside the process (a browser form, a JSON config). They used to each carry
their own copy of the "cast this value to the field's type" loop; both now call
`Params.from_dict`, so a new field or a change in coercion rules is a one-line
edit rather than a hunt.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace


class ParamError(ValueError):
    """A supplied parameter value cannot be cast to the field's type."""


@dataclass
class Params:
    # --- Section 1: Trend filters ---
    ema_fast_len: int = 288
    ema_slow_len: int = 1380

    # --- Section 1.5: Trend change closure ---
    trend_close_enable: bool = True

    # --- Trigger 1 (Single Big Candle) ---
    t1_en: bool = True
    t1_n: float = 2.0
    t1_tr_mult: float = 0.5
    t1_m: int = 4
    t1_rr_pri: float = 2.0
    t1_rr_alt: float = 3.0
    t1_risk: float = 1.0

    # --- Trigger 2 (Consecutive Candles) ---
    t2_en: bool = True
    t2_c: int = 3
    t2_n: float = 2.0
    t2_tr_mult: float = 0.5
    t2_m: int = 4
    t2_rr_pri: float = 2.0
    t2_rr_alt: float = 3.0
    t2_risk: float = 1.0

    # --- Trigger 3 (Engulfing SBC) ---
    t3_en: bool = True
    t3_n: float = 2.0
    t3_tr_mult: float = 0.5
    t3_m: int = 4
    t3_rr_pri: float = 2.0
    t3_rr_alt: float = 3.0
    t3_risk: float = 1.0

    # --- Section 3.5: Dynamic stop loss ---
    dyn_sl_enable: bool = True
    max_size_candle: float = 3.0
    min_stop_loss_ratio: float = 20.0   # percent

    # --- Section 6: Time restrictions (UTC) ---
    # Restricted window 23:30 -> 01:05 (spans midnight: mid hour = 00).
    res_start_hr: int = 23
    res_start_min: int = 30
    res_mid_hr: int = 0
    res_end_hr: int = 1
    res_end_min: int = 5
    close_hr: int = 23
    close_min: int = 50

    # --- Section 6b: Trading-session filter (UTC) ---
    # When enabled, new entries may only be opened while the bar's UTC hour is
    # inside [sess_start_hr, sess_end_hr). Default is the New York session
    # 17:00 -> 23:00 UTC. Handles overnight windows (start > end) too. This only
    # gates *entries*; exits/stops still work outside the window.
    session_filter_enable: bool = False
    sess_start_hr: int = 17
    sess_end_hr: int = 23

    # --- Section 6.5: Daily loss limit ---
    dll_enable: bool = True
    dll_loss_pct: float = 4.0
    dll_reset_hr: int = 22
    dll_reset_min: int = 0

    # --- Account / sizing ---
    pyramiding: int = 100

    # --- Execution costs: bid/ask spread ---
    # Candle prices are treated as the mid. Each fill (entry AND exit) is moved
    # half the spread against the trade, so a round-turn costs one full spread.
    # `spread` is the full bid/ask spread in price units (dollars), default $0.2.
    spread: float = 0.2

    # --- Data timezone handling ---
    tz_offset_hours: float = 0.0   # add this to convert CSV time -> UTC

    # -- construction from untrusted input ---------------------------------
    @classmethod
    def field_names(cls) -> tuple:
        return tuple(f.name for f in fields(cls))

    @classmethod
    def from_dict(cls, values: dict | None, *, base: "Params" | None = None,
                  strict: bool = False) -> "Params":
        """Copy `base` (defaults if omitted) with `values` applied on top.

        Each value is cast to the type the field already holds. Unknown keys are
        ignored — the UI posts its whole form and only some of it is strategy
        input. With strict=True an uncastable value raises ParamError; otherwise
        it is skipped, which is what a long-running optimizer wants.
        """
        params = replace(base) if base is not None else cls()
        for key, value in (values or {}).items():
            if not hasattr(params, key):
                continue
            try:
                setattr(params, key, _cast_like(getattr(params, key), value))
            except (TypeError, ValueError) as exc:
                if strict:
                    raise ParamError(f"bad value for {key}: {value!r}") from exc
        return params

    def as_dict(self) -> dict:
        return {name: getattr(self, name) for name in self.field_names()}

    def copy(self) -> "Params":
        return replace(self)


def _cast_like(current, value):
    """Cast `value` to the type of `current`. bool first — bool is an int."""
    if isinstance(current, bool):
        return bool(value)
    if isinstance(current, int):
        return int(value)
    if isinstance(current, float):
        return float(value)
    return value
