"""
strategy.py
===========
Faithful Python port of "Ultimate script v0.3.7" (UltScript.pine).

This module is *pure signal generation*. It takes OHLC(V) arrays and the
strategy parameters and returns, for every bar, everything the backtester needs:

    - trade_signal[i]   : a new entry should be opened at close[i]
    - direction[i]      : +1 long / -1 short
    - sl[i]             : stop-loss price (after dynamic-SL adjustment)
    - tp[i]             : take-profit price (after RR selection)
    - rr[i]             : the risk:reward used
    - reason[i]         : trigger code (see REASON_NAMES)
    - trend_changed[i]  : trend flipped on this bar -> close_all
    - is_close_time[i]  : time-exit bar          -> close_all
    - is_reset_time[i]  : daily-loss-limit reset bar (new trading day)

Position sizing and the daily-loss-limit *state machine* depend on live equity
(including open-position floating PnL), so those stay in backtest.py's event
loop. Everything that depends only on price/indicators is vectorised here.

NOTE on timezone: Pine's hour()/minute()/dayofmonth() in this script use "UTC".
The CSV carries no timezone, so we treat the timestamps as UTC. If your data is
in another timezone, set Params.tz_offset_hours accordingly.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
import numpy as np


# Trigger reason codes (priority order in the Pine script is T3 > T1 > T2)
REASON_NONE = 0
REASON_T3 = 1   # Engulfing Single Big Candle
REASON_T1 = 2   # Single Big Candle
REASON_T2 = 3   # Consecutive Candles

REASON_NAMES = {
    REASON_NONE: "",
    REASON_T3: "Engulfing Single Big Candle",
    REASON_T1: "Single Big Candle",
    REASON_T2: "Consecutive Candles",
}


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


# ---------------------------------------------------------------------------
# Indicator helpers
# ---------------------------------------------------------------------------
def ema(values: np.ndarray, length: int) -> np.ndarray:
    """Recursive EMA matching Pine's ta.ema (alpha = 2/(len+1), seeded with the
    first source value). The seed effect washes out long before any trades."""
    alpha = 2.0 / (length + 1.0)
    out = np.empty_like(values, dtype=np.float64)
    acc = values[0]
    out[0] = acc
    for i in range(1, values.shape[0]):
        acc = alpha * values[i] + (1.0 - alpha) * acc
        out[i] = acc
    return out


def true_range(high, low, close) -> np.ndarray:
    """ta.tr(true): first bar = high-low, otherwise the standard true range."""
    prev_close = np.empty_like(close)
    prev_close[0] = np.nan
    prev_close[1:] = close[:-1]
    hl = high - low
    hc = np.abs(high - prev_close)
    lc = np.abs(low - prev_close)
    tr = np.maximum(hl, np.maximum(hc, lc))
    tr[0] = high[0] - low[0]   # handle_na = true
    return tr


def sma_prev(values: np.ndarray, m: int) -> np.ndarray:
    """ta.sma(values, m)[1] -> rolling mean over m bars, then shifted back 1 bar.
    Bars without a full window (or no previous value) are NaN."""
    n = values.shape[0]
    csum = np.cumsum(np.insert(values, 0, 0.0))
    roll = np.full(n, np.nan, dtype=np.float64)
    roll[m - 1:] = (csum[m:] - csum[:-m]) / m
    out = np.full(n, np.nan, dtype=np.float64)
    out[1:] = roll[:-1]   # [1] shift
    return out


def _shift(arr: np.ndarray, k: int, fill):
    """arr[k] in Pine terms: value k bars ago. Positive k shifts forward."""
    out = np.empty_like(arr)
    if k == 0:
        return arr.copy()
    out[:k] = fill
    out[k:] = arr[:-k]
    return out


# ---------------------------------------------------------------------------
# Main signal computation
# ---------------------------------------------------------------------------
def compute_signals(open_, high, low, close, epoch_utc, p: Params):
    """
    open_, high, low, close : float64 arrays
    epoch_utc               : int64 array of bar-open epoch seconds (already UTC)
    Returns a dict of per-bar arrays.
    """
    n = close.shape[0]
    body = np.abs(close - open_)
    tr = true_range(high, low, close)

    ema_fast = ema(close, p.ema_fast_len)
    ema_slow = ema(close, p.ema_slow_len)

    long_allowed = ema_fast > ema_slow
    short_allowed = ema_fast < ema_slow

    # --- Trend change detection (Section 1.5) ---------------------------------
    curr_dir = np.where(long_allowed, 1, np.where(short_allowed, -1, 0)).astype(np.int8)
    prev_dir = _shift(curr_dir, 1, 0)
    trend_changed = (curr_dir != prev_dir) & (prev_dir != 0)

    # --- Trigger 1: Single Big Candle ----------------------------------------
    t1_avg_body = sma_prev(body, p.t1_m)
    t1_avg_tr = sma_prev(tr, p.t1_m)
    is_sbc_bull = (close > open_) & (body >= p.t1_n * t1_avg_body) & (tr >= p.t1_tr_mult * t1_avg_tr)
    is_sbc_bear = (close < open_) & (body >= p.t1_n * t1_avg_body) & (tr >= p.t1_tr_mult * t1_avg_tr)
    # NaN comparisons -> False automatically (warm-up bars), which is what we want
    is_sbc_bull = np.where(np.isnan(t1_avg_body) | np.isnan(t1_avg_tr), False, is_sbc_bull)
    is_sbc_bear = np.where(np.isnan(t1_avg_body) | np.isnan(t1_avg_tr), False, is_sbc_bear)

    t1_bull = p.t1_en & is_sbc_bull & long_allowed
    t1_bear = p.t1_en & is_sbc_bear & short_allowed

    # --- Trigger 2: Consecutive candles --------------------------------------
    t2_avg_body = sma_prev(body, p.t2_m)
    t2_avg_tr = sma_prev(tr, p.t2_m)

    is_consec_bull = np.ones(n, dtype=bool)
    is_consec_bear = np.ones(n, dtype=bool)
    no_sbc_bull = np.ones(n, dtype=bool)
    no_sbc_bear = np.ones(n, dtype=bool)
    union_max = np.maximum(open_, close).copy()
    union_min = np.minimum(open_, close).copy()

    for i in range(p.t2_c):
        o_i = _shift(open_, i, np.nan)
        c_i = _shift(close, i, np.nan)
        l_i = _shift(low, i, np.nan)
        h_i = _shift(high, i, np.nan)
        sbc_bull_i = _shift(is_sbc_bull, i, False)
        sbc_bear_i = _shift(is_sbc_bear, i, False)

        # bull: every candle in the run must be bullish (close > open)
        is_consec_bull &= (c_i > o_i)
        # bear: every candle must be bearish (close < open)
        is_consec_bear &= (c_i < o_i)

        if i < p.t2_c - 1:
            l_next = _shift(low, i + 1, np.nan)
            h_next = _shift(high, i + 1, np.nan)
            # bull requires strictly rising lows (low[i] > low[i+1])
            is_consec_bull &= (l_i > l_next)
            # bear requires strictly falling highs (high[i] < high[i+1])
            is_consec_bear &= (h_i < h_next)

        no_sbc_bull &= ~sbc_bull_i
        no_sbc_bear &= ~sbc_bear_i

        union_max = np.maximum(union_max, np.maximum(o_i, c_i))
        union_min = np.minimum(union_min, np.minimum(o_i, c_i))

    # invalidate the first (t2_c-1) bars that don't have a full lookback
    warm = np.arange(n) < (p.t2_c - 1)
    is_consec_bull = np.where(warm, False, is_consec_bull)
    is_consec_bear = np.where(warm, False, is_consec_bear)

    union_body = union_max - union_min
    valid_union = (union_body >= p.t2_n * t2_avg_body) & (tr >= p.t2_tr_mult * t2_avg_tr)
    valid_union = np.where(np.isnan(t2_avg_body) | np.isnan(t2_avg_tr), False, valid_union)

    t2_bull = p.t2_en & is_consec_bull & no_sbc_bull & valid_union & long_allowed
    t2_bear = p.t2_en & is_consec_bear & no_sbc_bear & valid_union & short_allowed

    # --- Trigger 3: Engulfing SBC --------------------------------------------
    t3_avg_body = sma_prev(body, p.t3_m)
    t3_avg_tr = sma_prev(tr, p.t3_m)
    is_t3_sbc_bull = (close > open_) & (body >= p.t3_n * t3_avg_body) & (tr >= p.t3_tr_mult * t3_avg_tr)
    is_t3_sbc_bear = (close < open_) & (body >= p.t3_n * t3_avg_body) & (tr >= p.t3_tr_mult * t3_avg_tr)
    is_t3_sbc_bull = np.where(np.isnan(t3_avg_body) | np.isnan(t3_avg_tr), False, is_t3_sbc_bull)
    is_t3_sbc_bear = np.where(np.isnan(t3_avg_body) | np.isnan(t3_avg_tr), False, is_t3_sbc_bear)

    sbc_bear_prev = _shift(is_sbc_bear, 1, False)
    sbc_bull_prev = _shift(is_sbc_bull, 1, False)
    t3_bull = p.t3_en & is_t3_sbc_bull & sbc_bear_prev & long_allowed
    t3_bear = p.t3_en & is_t3_sbc_bear & sbc_bull_prev & short_allowed

    # --- Consolidate triggers (priority T3 > T1 > T2) ------------------------
    direction = np.zeros(n, dtype=np.int8)
    reason = np.zeros(n, dtype=np.int8)
    sl = np.full(n, np.nan, dtype=np.float64)
    rr_pri = np.full(n, np.nan, dtype=np.float64)
    rr_alt = np.full(n, np.nan, dtype=np.float64)
    risk_pct = np.full(n, np.nan, dtype=np.float64)
    avg_body = np.full(n, np.nan, dtype=np.float64)

    open_c2 = _shift(open_, p.t2_c - 1, np.nan)   # open[t2_c-1] for T2 stop

    def apply(mask, d, rcode, sl_arr, rp, ra, rk, ab):
        # only set where not already set by a higher-priority trigger
        m = mask & (reason == REASON_NONE)
        direction[m] = d
        reason[m] = rcode
        sl[m] = sl_arr[m]
        rr_pri[m] = rp
        rr_alt[m] = ra
        risk_pct[m] = rk
        avg_body[m] = ab[m]

    apply(t3_bull, 1, REASON_T3, open_, p.t3_rr_pri, p.t3_rr_alt, p.t3_risk, t3_avg_body)
    apply(t3_bear, -1, REASON_T3, open_, p.t3_rr_pri, p.t3_rr_alt, p.t3_risk, t3_avg_body)
    apply(t1_bull, 1, REASON_T1, open_, p.t1_rr_pri, p.t1_rr_alt, p.t1_risk, t1_avg_body)
    apply(t1_bear, -1, REASON_T1, open_, p.t1_rr_pri, p.t1_rr_alt, p.t1_risk, t1_avg_body)
    apply(t2_bull, 1, REASON_T2, open_c2, p.t2_rr_pri, p.t2_rr_alt, p.t2_risk, t2_avg_body)
    apply(t2_bear, -1, REASON_T2, open_c2, p.t2_rr_pri, p.t2_rr_alt, p.t2_risk, t2_avg_body)

    trade_signal = reason != REASON_NONE

    # --- Section 3.5: Dynamic stop loss --------------------------------------
    if p.dyn_sl_enable:
        with np.errstate(invalid="ignore"):
            initial_sl_dist = np.abs(close - sl)
            too_big = trade_signal & (initial_sl_dist > (p.max_size_candle * avg_body))
            new_sl_dist = initial_sl_dist * (1.0 - p.min_stop_loss_ratio / 100.0)
            tightened = np.where(direction == 1, close - new_sl_dist, close + new_sl_dist)
            sl = np.where(too_big, tightened, sl)

    # --- Section 4 & 5: TP calc + RR selection -------------------------------
    sl_dist = np.abs(close - sl)
    price_above_ema = close > ema_fast
    # final RR per the 4-way table
    rr_final = np.where(
        (price_above_ema & (direction == 1)) | (~price_above_ema & (direction == -1)),
        rr_pri, rr_alt,
    )
    tp = np.where(direction == 1, close + sl_dist * rr_final, close - sl_dist * rr_final)

    # --- Section 6: Time restrictions (UTC) ----------------------------------
    secs = (epoch_utc + int(round(p.tz_offset_hours * 3600))).astype(np.int64)
    cur_hour = ((secs // 3600) % 24).astype(np.int32)
    cur_min = ((secs // 60) % 60).astype(np.int32)

    is_restricted = (
        ((cur_hour == p.res_start_hr) & (cur_min >= p.res_start_min))
        | (cur_hour == p.res_mid_hr)
        | ((cur_hour == p.res_end_hr) & (cur_min <= p.res_end_min))
    )
    trade_signal = trade_signal & ~is_restricted

    # --- Section 6b: trading-session filter (entries only) -------------------
    if p.session_filter_enable:
        if p.sess_start_hr <= p.sess_end_hr:
            in_session = (cur_hour >= p.sess_start_hr) & (cur_hour < p.sess_end_hr)
        else:  # overnight window, e.g. 22 -> 03 wraps past midnight
            in_session = (cur_hour >= p.sess_start_hr) | (cur_hour < p.sess_end_hr)
        trade_signal = trade_signal & in_session

    is_close_time = (cur_hour == p.close_hr) & (cur_min == p.close_min)

    # --- Section 6.5: Daily-loss-limit reset bars ----------------------------
    shifted = secs - (p.dll_reset_hr * 3600 + p.dll_reset_min * 60)
    # day-of-month of the shifted timestamp (matches Pine dayofmonth)
    dom = (((shifted // 86400) ) ).astype(np.int64)  # days since epoch
    # convert "days since epoch" -> day-of-month
    dom_of_month = _days_to_dom(shifted)
    prev_dom = _shift(dom_of_month, 1, -999)
    is_reset_time = dom_of_month != prev_dom
    is_reset_time[0] = True

    # zero-out invalid sl/tp where no trade
    sl = np.where(trade_signal, sl, np.nan)
    tp = np.where(trade_signal, tp, np.nan)
    # a zero-distance stop can't be sized -> no trade (Pine sets trade_signal=false)
    valid_dist = np.abs(close - sl) > 0
    trade_signal = trade_signal & valid_dist

    return {
        "trade_signal": trade_signal,
        "direction": direction,
        "sl": sl,
        "tp": tp,
        "rr": rr_final,
        "risk_pct": risk_pct,
        "reason": reason,
        "trend_changed": (trend_changed & p.trend_close_enable),
        "is_close_time": is_close_time,
        "is_reset_time": is_reset_time,
        "ema_fast": ema_fast,
        "ema_slow": ema_slow,
        "cur_hour": cur_hour,
        "cur_min": cur_min,
    }


def _days_to_dom(shifted_secs: np.ndarray) -> np.ndarray:
    """Day-of-month for an array of epoch seconds, vectorised, UTC."""
    days = (shifted_secs // 86400).astype(np.int64)   # days since 1970-01-01
    dt = days.astype("datetime64[D]")
    # day of month = (date - first of its month) + 1
    month_start = dt.astype("datetime64[M]").astype("datetime64[D]")
    return ((dt - month_start).astype(np.int64) + 1).astype(np.int64)
