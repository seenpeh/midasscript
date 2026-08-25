"""Turn prices into entry signals — a faithful port of "Ultimate script v0.3.7".

This module is *pure signal generation*. It takes a `CandleSeries` and the
strategy parameters and returns, for every bar, everything the backtester needs
to decide what to do. It knows nothing about money, position size or equity:
position sizing and the daily-loss-limit state machine depend on live equity
(including floating PnL) and therefore live in `midas.engine`.

NOTE on timezone: Pine's hour()/minute()/dayofmonth() in this script use UTC.
The CSV carries no timezone, so timestamps are treated as UTC. If your data is
in another timezone, set `Params.tz_offset_hours`.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import indicators as ind
from .triggers import (BarFeatures, REASON_NONE, TriggerContext,
                       big_candle_masks, triggers_from_params)


@dataclass(frozen=True)
class SignalSet:
    """Per-bar arrays, all the same length as the series.

    Attribute access instead of dictionary keys: the backtester reads
    `signals.stop_loss[i]`, so a typo is an AttributeError at the first bar
    rather than a KeyError buried in a branch that runs once a year.
    """
    entry: np.ndarray          # a new entry should be opened at close[i]
    direction: np.ndarray      # +1 long / -1 short
    stop_loss: np.ndarray      # after the dynamic-SL adjustment
    take_profit: np.ndarray    # after RR selection
    risk_reward: np.ndarray
    risk_pct: np.ndarray
    reason: np.ndarray         # trigger code, see triggers.REASON_NAMES
    trend_changed: np.ndarray  # trend flipped on this bar -> close all
    is_close_time: np.ndarray  # time-exit bar          -> close all
    is_reset_time: np.ndarray  # daily-loss-limit reset (new trading day)
    ema_fast: np.ndarray
    ema_slow: np.ndarray

    @property
    def entry_count(self) -> int:
        return int(self.entry.sum())


def compute_signals(series, params) -> SignalSet:
    bars = _bar_features(series)
    ema_fast = ind.ema(bars.close, params.ema_fast_len)
    ema_slow = ind.ema(bars.close, params.ema_slow_len)
    long_allowed = ema_fast > ema_slow
    short_allowed = ema_fast < ema_slow

    context = _trigger_context(bars, params, long_allowed, short_allowed)
    entries = _consolidate(triggers_from_params(params), context)

    stop_loss = _apply_dynamic_stop(bars.close, entries, params)
    risk_reward, take_profit = _targets(bars.close, ema_fast, entries, stop_loss)

    calendar = _calendar(series.epoch, params)
    tradable = entries.fired & ~calendar["restricted"] & calendar["in_session"]

    # A zero-distance stop cannot be sized, so it is not a trade (as in Pine).
    stop_loss = np.where(tradable, stop_loss, np.nan)
    take_profit = np.where(tradable, take_profit, np.nan)
    tradable = tradable & (np.abs(bars.close - stop_loss) > 0)

    return SignalSet(
        entry=tradable,
        direction=entries.direction,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_reward=risk_reward,
        risk_pct=entries.risk_pct,
        reason=entries.reason,
        trend_changed=_trend_changed(long_allowed, short_allowed) & params.trend_close_enable,
        is_close_time=calendar["close_time"],
        is_reset_time=calendar["reset_time"],
        ema_fast=ema_fast,
        ema_slow=ema_slow,
    )


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------
def _bar_features(series) -> BarFeatures:
    return BarFeatures(
        open=series.open, high=series.high, low=series.low, close=series.close,
        body=np.abs(series.close - series.open),
        true_range=ind.true_range(series.high, series.low, series.close),
    )


def _trigger_context(bars, params, long_allowed, short_allowed) -> TriggerContext:
    # Trigger 1's big-candle masks are shared inputs to T2 and T3 (see
    # TriggerContext), so they are computed here rather than inside T1 — and
    # deliberately regardless of whether T1 itself is enabled.
    baseline_bull, baseline_bear, _ = big_candle_masks(
        bars, params.t1_n, params.t1_tr_mult, params.t1_m)
    return TriggerContext(bars=bars, long_allowed=long_allowed,
                          short_allowed=short_allowed,
                          baseline_bull=baseline_bull, baseline_bear=baseline_bear)


@dataclass
class _Entries:
    """The winning trigger per bar, after priority resolution."""
    fired: np.ndarray
    direction: np.ndarray
    reason: np.ndarray
    stop: np.ndarray
    rr_primary: np.ndarray
    rr_alternate: np.ndarray
    risk_pct: np.ndarray
    avg_body: np.ndarray


def _consolidate(triggers, context) -> _Entries:
    """First trigger in priority order to fire on a bar owns that bar."""
    count = context.bars.count
    nan_array = lambda: np.full(count, np.nan, dtype=np.float64)
    entries = _Entries(
        fired=np.zeros(count, dtype=bool),
        direction=np.zeros(count, dtype=np.int8),
        reason=np.zeros(count, dtype=np.int8),
        stop=nan_array(), rr_primary=nan_array(), rr_alternate=nan_array(),
        risk_pct=nan_array(), avg_body=nan_array(),
    )
    for trigger in triggers:
        detection = trigger.detect(context)
        for mask, direction in ((detection.bull, 1), (detection.bear, -1)):
            claim = mask & (entries.reason == REASON_NONE)
            entries.direction[claim] = direction
            entries.reason[claim] = trigger.code
            entries.stop[claim] = detection.stop[claim]
            entries.avg_body[claim] = detection.avg_body[claim]
            entries.rr_primary[claim] = trigger.rr_primary
            entries.rr_alternate[claim] = trigger.rr_alternate
            entries.risk_pct[claim] = trigger.risk_pct
    entries.fired = entries.reason != REASON_NONE
    return entries


def _apply_dynamic_stop(close, entries, params) -> np.ndarray:
    """Section 3.5 — a stop further than `max_size_candle` average bodies away
    is pulled in by `min_stop_loss_ratio` percent."""
    if not params.dyn_sl_enable:
        return entries.stop
    with np.errstate(invalid="ignore"):
        distance = np.abs(close - entries.stop)
        oversized = entries.fired & (distance > params.max_size_candle * entries.avg_body)
        tightened_distance = distance * (1.0 - params.min_stop_loss_ratio / 100.0)
        tightened = np.where(entries.direction == 1,
                             close - tightened_distance,
                             close + tightened_distance)
        return np.where(oversized, tightened, entries.stop)


def _targets(close, ema_fast, entries, stop_loss):
    """Sections 4 & 5 — pick the risk:reward, then place the take-profit.

    The primary RR applies when price sits on the trade's own side of the fast
    EMA (long above / short below); otherwise the alternate RR does.
    """
    distance = np.abs(close - stop_loss)
    above_ema = close > ema_fast
    aligned = (above_ema & (entries.direction == 1)) | (~above_ema & (entries.direction == -1))
    risk_reward = np.where(aligned, entries.rr_primary, entries.rr_alternate)
    take_profit = np.where(entries.direction == 1,
                           close + distance * risk_reward,
                           close - distance * risk_reward)
    return risk_reward, take_profit


def _trend_changed(long_allowed, short_allowed) -> np.ndarray:
    """Section 1.5 — the EMA relationship flipped on this bar."""
    current = np.where(long_allowed, 1, np.where(short_allowed, -1, 0)).astype(np.int8)
    previous = ind.shift(current, 1, 0)
    return (current != previous) & (previous != 0)


def _calendar(epoch, params) -> dict:
    """Sections 6, 6b and 6.5 — the clock-driven masks."""
    hour, minute, seconds = ind.clock(epoch, params.tz_offset_hours)

    restricted = (
        ((hour == params.res_start_hr) & (minute >= params.res_start_min))
        | (hour == params.res_mid_hr)
        | ((hour == params.res_end_hr) & (minute <= params.res_end_min))
    )

    if params.session_filter_enable:
        if params.sess_start_hr <= params.sess_end_hr:
            in_session = (hour >= params.sess_start_hr) & (hour < params.sess_end_hr)
        else:   # overnight window, e.g. 22 -> 03, wraps past midnight
            in_session = (hour >= params.sess_start_hr) | (hour < params.sess_end_hr)
    else:
        in_session = np.ones(hour.shape[0], dtype=bool)

    # A new trading day starts at the daily-loss-limit reset time.
    day = ind.day_of_month(seconds - (params.dll_reset_hr * 3600
                                      + params.dll_reset_min * 60))
    reset_time = day != ind.shift(day, 1, -999)
    reset_time[0] = True

    return {
        "restricted": restricted,
        "in_session": in_session,
        "close_time": (hour == params.close_hr) & (minute == params.close_min),
        "reset_time": reset_time,
    }
