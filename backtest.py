"""
backtest.py
===========
Event-driven backtest of the Ultimate-script strategy on the 5-minute data.

Pipeline:
    1. load 5m_candles.json
    2. compute all price-only signals (strategy.compute_signals)
    3. walk the bars, managing positions / equity / daily-loss-limit
    4. print the trading process to the terminal
    5. write results.json   (stats + every trade + equity curve)
    6. write 5m_candles_chart.json  (recent slice for the HTML chart)

Execution model (matches the Pine script's intent):
    - process_orders_on_close = true  -> entries fill at the signal bar's CLOSE
    - each entry gets its own stop-loss + take-profit (strategy.exit)
    - pyramiding 100 -> up to 100 simultaneous positions
    - stop/take orders are evaluated intrabar on SUBSEQUENT bars
    - if both SL and TP sit inside one bar, the STOP fills first (conservative)
    - a price that GAPS through a level at the open fills at the open
    - strategy.close_all (trend-change / time-exit) closes at that bar's close
    - position size = equity * risk% / |close - stop|, equity includes floating PnL

Usage:
    python3 backtest.py [--capital 10000] [--data 5m_candles.json]
                        [--print-every 1] [--chart-days 730] [--quiet]
"""

from __future__ import annotations

import argparse
import json
import sys
import time as _time
from datetime import datetime, timezone

import numpy as np

import strategy as S


# ---------------------------------------------------------------------------
# Terminal colours
# ---------------------------------------------------------------------------
class C:
    enabled = sys.stdout.isatty()

    @staticmethod
    def _w(code, s):
        return f"\033[{code}m{s}\033[0m" if C.enabled else s

    @staticmethod
    def green(s): return C._w("32", s)
    @staticmethod
    def red(s): return C._w("31", s)
    @staticmethod
    def cyan(s): return C._w("36", s)
    @staticmethod
    def yellow(s): return C._w("33", s)
    @staticmethod
    def grey(s): return C._w("90", s)
    @staticmethod
    def bold(s): return C._w("1", s)


def ts_str(epoch: int) -> str:
    return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%d %H:%M")


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------
def load_candles(path: str):
    t0 = _time.time()
    print(f"Loading {path} ...", flush=True)
    with open(path) as f:
        doc = json.load(f)
    arr = np.asarray(doc["candles"], dtype=np.float64)
    epoch = arr[:, 0].astype(np.int64)
    o, h, l, c, v = arr[:, 1], arr[:, 2], arr[:, 3], arr[:, 4], arr[:, 5]
    print(f"  {len(epoch):,} candles loaded in {_time.time()-t0:.1f}s "
          f"({ts_str(epoch[0])} -> {ts_str(epoch[-1])})", flush=True)
    return epoch, o, h, l, c, v


# ---------------------------------------------------------------------------
# Backtest core
# ---------------------------------------------------------------------------
def run(epoch, o, h, l, c, v, params: S.Params, capital: float,
        print_every: int = 1, quiet: bool = False, ruin_floor: float = 0.01,
        start_ts: int | None = None, end_ts: int | None = None, log: bool = True):
    """
    Run the backtest. If start_ts/end_ts are given (epoch seconds), the trading
    window is restricted to that range — but signals (and therefore EMAs) are
    still computed on the *full* series so the trend filter has correct warmup.

    log=False suppresses ALL framing output (used by the optimizer for fast,
    silent evaluation); quiet=True only suppresses per-trade/per-year lines.
    """
    def _p(*a, **k):
        if log: print(*a, **k)

    n = c.shape[0]
    _p("Computing signals ...", flush=True)
    t0 = _time.time()
    sig = S.compute_signals(o, h, l, c, epoch, params)
    _p(f"  signals ready in {_time.time()-t0:.1f}s "
       f"({int(sig['trade_signal'].sum()):,} raw entry signals)", flush=True)

    # Trading window: bars outside [start_ts, end_ts] don't trade. Open
    # positions at end_ts get a forced exit on the last bar in the window.
    i_start = int(np.searchsorted(epoch, start_ts)) if start_ts else 0
    i_end = int(np.searchsorted(epoch, end_ts, side="right")) if end_ts else n
    i_end = max(i_end, i_start + 1)
    if i_start > 0 or i_end < n:
        _p(f"  trading window: bar {i_start:,} -> {i_end-1:,}  "
           f"({ts_str(epoch[i_start])} -> {ts_str(epoch[i_end-1])})", flush=True)

    trade_signal = sig["trade_signal"]
    direction = sig["direction"]
    sl_arr = sig["sl"]
    tp_arr = sig["tp"]
    rr_arr = sig["rr"]
    risk_arr = sig["risk_pct"]
    reason_arr = sig["reason"]
    trend_changed = sig["trend_changed"]
    is_close_time = sig["is_close_time"]
    is_reset_time = sig["is_reset_time"]

    initial = float(capital)
    realized = 0.0
    # bid/ask spread: candle prices are the mid; each fill is moved half a spread
    # against the trade (round-turn cost = one full spread).
    half_spread = max(0.0, float(getattr(params, "spread", 0.2))) / 2.0
    positions = []          # open positions
    closed = []             # completed trade records
    equity_points = []      # (epoch, realized_equity) after each close
    next_id = 1

    saved_equity = None
    dll_active = False
    bankrupt = False
    ruin_info = None

    _p(C.bold(f"\n=== Backtest start  |  capital {initial:,.2f}  |  {n:,} bars ===\n"),
       flush=True)
    loop_t0 = _time.time()
    last_year = None
    printed_trades = 0

    def fmt_entry(p):
        arrow = "▲ LONG " if p["dir"] == 1 else "▼ SHORT"
        col = C.green if p["dir"] == 1 else C.red
        return (f"{C.grey(ts_str(p['entry_time']))}  {col(arrow)} "
                f"entry @ {p['entry_price']:.2f}  qty {p['qty']:.4f}  "
                f"SL {p['sl']:.2f}  TP {p['tp']:.2f}  "
                f"{C.cyan(S.REASON_NAMES[p['reason']])} RR 1:{p['rr']:.1f}  risk {p['risk']:.1f}%")

    def fmt_exit(p, ex_price, ex_reason, pnl, eq):
        side = "LONG" if p["dir"] == 1 else "SHORT"
        tag = {"SL": C.red("SL"), "TP": C.green("TP"),
               "TrendChange": C.yellow("TREND"), "TimeExit": C.yellow("TIME"),
               "EndOfData": C.grey("EOD")}[ex_reason]
        pnl_s = C.green(f"+{pnl:,.2f}") if pnl >= 0 else C.red(f"{pnl:,.2f}")
        return (f"{C.grey(ts_str(p['exit_time']))}    ✖ exit {side} @ {ex_price:.2f}  "
                f"{tag}  PnL {pnl_s}  eq={eq:,.2f}")

    def close_position(p, exit_time, exit_i, exit_price, exit_reason):
        nonlocal realized
        # exit fills at the adverse side of the spread: a long sells the bid
        # (price - half), a short buys the ask (price + half)
        exit_price = exit_price - p["dir"] * half_spread
        pnl = p["dir"] * (exit_price - p["entry_price"]) * p["qty"]
        realized += pnl
        eq = initial + realized
        rec = {
            "id": p["id"],
            "direction": "long" if p["dir"] == 1 else "short",
            "reason": S.REASON_NAMES[p["reason"]],
            "entry_time": int(p["entry_time"]),
            "entry_dt": ts_str(p["entry_time"]),
            "entry_price": round(p["entry_price"], 2),
            "qty": round(p["qty"], 6),
            "sl": round(p["sl"], 2),
            "tp": round(p["tp"], 2),
            "rr": round(p["rr"], 2),
            "risk_pct": round(p["risk"], 2),
            "exit_time": int(exit_time),
            "exit_dt": ts_str(exit_time),
            "exit_price": round(exit_price, 2),
            "exit_reason": exit_reason,
            "bars_held": int(exit_i - p["entry_i"]),
            "pnl": round(pnl, 2),
            "return_pct": round(pnl / initial * 100, 4),
            "mae": round(p["mae"], 2),   # worst adverse price excursion
            "mfe": round(p["mfe"], 2),   # best favourable price excursion
            "equity_after": round(eq, 2),
        }
        closed.append(rec)
        p["exit_time"] = exit_time
        equity_points.append((int(exit_time), eq))
        if not quiet:
            nonlocal printed_trades
            printed_trades += 1
            if printed_trades % print_every == 0:
                print(fmt_exit(p, exit_price, exit_reason, pnl, eq), flush=True)
        return pnl

    # ---- main bar loop ----
    for i in range(i_start, i_end):
        oi = o[i]; hi = h[i]; li = l[i]; ci = c[i]; ti = epoch[i]

        if not quiet:
            yr = ti // (365 * 86400)
            if yr != last_year:
                last_year = yr
                eq_now = initial + realized
                print(C.bold(C.grey(
                    f"--- {ts_str(ti)[:4]}  |  open {len(positions)}  "
                    f"closed {len(closed):,}  equity {eq_now:,.2f} ---")), flush=True)

        # 1) broker: intrabar stop/take exits for positions opened on earlier bars
        if positions:
            survivors = []
            for p in positions:
                # update excursions
                if p["dir"] == 1:
                    p["mae"] = min(p["mae"], li)
                    p["mfe"] = max(p["mfe"], hi)
                    if oi <= p["sl"]:
                        ex, rsn = oi, "SL"            # gapped through stop at open
                    elif oi >= p["tp"]:
                        ex, rsn = oi, "TP"            # gapped through limit at open
                    elif li <= p["sl"]:
                        ex, rsn = p["sl"], "SL"       # stop first (conservative)
                    elif hi >= p["tp"]:
                        ex, rsn = p["tp"], "TP"
                    else:
                        ex = None
                else:
                    p["mae"] = max(p["mae"], hi)
                    p["mfe"] = min(p["mfe"], li)
                    if oi >= p["sl"]:
                        ex, rsn = oi, "SL"
                    elif oi <= p["tp"]:
                        ex, rsn = oi, "TP"
                    elif hi >= p["sl"]:
                        ex, rsn = p["sl"], "SL"
                    elif li <= p["tp"]:
                        ex, rsn = p["tp"], "TP"
                    else:
                        ex = None

                if ex is None:
                    survivors.append(p)
                else:
                    close_position(p, ti, i, ex, rsn)
            positions = survivors

        # 2) trend-change closure  (Section 1.5) -> close_all at this bar's close
        if positions and trend_changed[i]:
            for p in positions:
                close_position(p, ti, i, ci, "TrendChange")
            positions = []

        # 3) time exit (Section 6) -> close_all at this bar's close
        if positions and is_close_time[i]:
            for p in positions:
                close_position(p, ti, i, ci, "TimeExit")
            positions = []

        # 4) live equity (initial + realized + floating open PnL)
        open_profit = 0.0
        for p in positions:
            open_profit += p["dir"] * (ci - p["entry_price"]) * p["qty"]
        equity = initial + realized + open_profit

        # 4b) ruin halt: risk-% sizing makes a losing account decay geometrically
        # toward (but never reaching) zero, spraying meaningless dust-trades. Once
        # equity falls below `ruin_floor` of the starting capital the account is
        # effectively blown, so we stop. Set --ruin-floor 0 to run to literal dust.
        if equity <= initial * ruin_floor:
            for p in positions:
                close_position(p, ti, i, ci, "EndOfData")
            positions = []
            bankrupt = True
            ruin_info = {"date": ts_str(ti), "trades": len(closed),
                         "equity": round(equity, 2)}
            _p(C.bold(C.red(
                f"\n!!! ACCOUNT EFFECTIVELY RUINED at {ts_str(ti)} after "
                f"{len(closed):,} trades (equity {equity:,.2f} <= "
                f"{ruin_floor*100:.0f}% of start). Halting. !!!\n")), flush=True)
            break

        # 5) daily-loss-limit state machine (Section 6.5)
        if is_reset_time[i]:
            saved_equity = equity
            dll_active = False
        if saved_equity is None:
            saved_equity = equity
        if params.dll_enable and not dll_active:
            if equity <= saved_equity * (1.0 - params.dll_loss_pct / 100.0):
                dll_active = True
        dll_block = params.dll_enable and dll_active

        # 6) entry (Sections 7 + 8) at this bar's close
        if trade_signal[i] and not dll_block and len(positions) < params.pyramiding:
            sl = sl_arr[i]; tp = tp_arr[i]; d = int(direction[i])
            trade_risk = abs(ci - sl)
            if trade_risk > 0:
                qty = equity * (risk_arr[i] / 100.0) / trade_risk
                # entry fills at the adverse side: long pays the ask (close+half),
                # short sells the bid (close-half). Sizing stays on the mid risk.
                entry_fill = ci + d * half_spread
                p = {
                    "id": next_id, "dir": d, "entry_time": ti, "entry_i": i,
                    "entry_price": entry_fill, "qty": qty, "sl": float(sl), "tp": float(tp),
                    "rr": float(rr_arr[i]), "risk": float(risk_arr[i]),
                    "reason": int(reason_arr[i]), "mae": ci, "mfe": ci,
                }
                next_id += 1
                positions.append(p)
                if not quiet and (next_id % print_every == 0):
                    print(fmt_entry(p), flush=True)

    # ---- close any still-open positions at the final window bar ----
    if positions:
        last_i = i_end - 1
        ti = epoch[last_i]; ci = c[last_i]
        for p in positions:
            close_position(p, ti, last_i, ci, "EndOfData")
        positions = []

    _p(C.bold(f"\n=== Backtest done in {_time.time()-loop_t0:.1f}s  |  "
              f"{len(closed):,} trades  |  final equity "
              f"{initial+realized:,.2f} ===\n"), flush=True)

    return closed, equity_points, initial, realized, ruin_info, i_start, i_end


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------
def _month_index(ts):
    d = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    return d.year * 12 + (d.month - 1)


def _monthly_returns(equity_points, initial, ts_start, ts_end):
    """Forward-filled month-end equity over [ts_start, ts_end] -> fractional
    monthly returns (flat months count as 0%, which correctly lowers Sharpe)."""
    if ts_end < ts_start:
        return np.array([], dtype=float)
    eq_by_month = {}
    for ts, e in equity_points:               # points are time-ascending
        eq_by_month[_month_index(ts)] = e     # last close in the month wins
    months = range(_month_index(ts_start), _month_index(ts_end) + 1)
    rets, prev, cur = [], initial, initial
    for m in months:
        if m in eq_by_month:
            cur = eq_by_month[m]
        if prev > 0:
            rets.append(cur / prev - 1.0)
        prev = cur
    return np.array(rets, dtype=float)


def compute_stats(closed, equity_points, initial, realized, epoch, i_start=0, i_end=None):
    if i_end is None: i_end = len(epoch)
    n = len(closed)
    if n == 0:
        return {"total_trades": 0, "note": "no trades generated"}

    pnls = np.array([t["pnl"] for t in closed])
    wins = pnls[pnls > 0]
    losses = pnls[pnls < 0]
    gross_profit = float(wins.sum())
    gross_loss = float(-losses.sum())

    # equity curve & drawdown (on realized closed-trade equity)
    eq = np.array([initial] + [p[1] for p in equity_points], dtype=np.float64)
    peak = np.maximum.accumulate(eq)
    dd = peak - eq
    dd_pct = np.where(peak > 0, dd / peak * 100, 0)
    max_dd = float(dd.max())
    max_dd_pct = float(dd_pct.max())

    # consecutive streaks
    max_win_streak = max_loss_streak = cur_w = cur_l = 0
    for x in pnls:
        if x > 0:
            cur_w += 1; cur_l = 0
        elif x < 0:
            cur_l += 1; cur_w = 0
        max_win_streak = max(max_win_streak, cur_w)
        max_loss_streak = max(max_loss_streak, cur_l)

    longs = [t for t in closed if t["direction"] == "long"]
    shorts = [t for t in closed if t["direction"] == "short"]

    def wr(trades):
        if not trades:
            return 0.0
        w = sum(1 for t in trades if t["pnl"] > 0)
        return round(w / len(trades) * 100, 2)

    # by trigger reason
    by_reason = {}
    for name in set(t["reason"] for t in closed):
        grp = [t for t in closed if t["reason"] == name]
        by_reason[name] = {
            "trades": len(grp),
            "win_rate": wr(grp),
            "net_pnl": round(sum(t["pnl"] for t in grp), 2),
        }

    by_exit = {}
    for r in set(t["exit_reason"] for t in closed):
        grp = [t for t in closed if t["exit_reason"] == r]
        by_exit[r] = {"count": len(grp), "net_pnl": round(sum(t["pnl"] for t in grp), 2)}

    # CAGR (over the actual trading window)
    span_yrs = max((epoch[i_end-1] - epoch[i_start]) / (365.25 * 86400), 1e-9)
    final_eq = initial + realized
    cagr = ((final_eq / initial) ** (1 / span_yrs) - 1) * 100 if final_eq > 0 else -100.0

    # risk-adjusted ratios from monthly returns (annualised)
    mr = _monthly_returns(equity_points, initial, epoch[i_start], epoch[i_end - 1])
    sharpe = sortino = 0.0
    if mr.size >= 2:
        mu = float(mr.mean())
        sd = float(mr.std(ddof=1))
        if sd > 0:
            sharpe = mu / sd * np.sqrt(12)
        neg = np.minimum(mr, 0.0)
        ddev = float(np.sqrt(np.mean(neg ** 2)))
        if ddev > 0:
            sortino = mu / ddev * np.sqrt(12)
        elif mu > 0:
            sortino = sharpe          # no downside months -> fall back to Sharpe
    calmar = cagr / max(max_dd_pct, 1.0)   # floor DD at 1% to avoid blow-ups

    return {
        "initial_capital": round(initial, 2),
        "final_equity": round(final_eq, 2),
        "net_profit": round(realized, 2),
        "return_pct": round(realized / initial * 100, 2),
        "cagr_pct": round(cagr, 2),
        "total_trades": n,
        "wins": int((pnls > 0).sum()),
        "losses": int((pnls < 0).sum()),
        "breakeven": int((pnls == 0).sum()),
        "win_rate": round(float((pnls > 0).sum()) / n * 100, 2),
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss > 0 else None,
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "avg_trade": round(float(pnls.mean()), 2),
        "avg_win": round(float(wins.mean()), 2) if len(wins) else 0.0,
        "avg_loss": round(float(losses.mean()), 2) if len(losses) else 0.0,
        "expectancy": round(float(pnls.mean()), 2),
        "largest_win": round(float(pnls.max()), 2),
        "largest_loss": round(float(pnls.min()), 2),
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "calmar": round(calmar, 3),
        "max_consec_wins": max_win_streak,
        "max_consec_losses": max_loss_streak,
        "avg_bars_held": round(float(np.mean([t["bars_held"] for t in closed])), 1),
        "long_trades": len(longs),
        "short_trades": len(shorts),
        "long_win_rate": wr(longs),
        "short_win_rate": wr(shorts),
        "by_trigger": by_reason,
        "by_exit": by_exit,
    }


def print_summary(stats):
    if stats.get("total_trades", 0) == 0:
        print(C.yellow("No trades were generated."))
        return
    s = stats
    line = "─" * 54
    print(C.bold("\n" + line))
    print(C.bold("  BACKTEST SUMMARY"))
    print(line)
    rows = [
        ("Initial capital", f"{s['initial_capital']:,.2f}"),
        ("Final equity", f"{s['final_equity']:,.2f}"),
        ("Net profit", f"{s['net_profit']:,.2f}  ({s['return_pct']:+.2f}%)"),
        ("CAGR", f"{s['cagr_pct']:+.2f}%"),
        ("Total trades", f"{s['total_trades']:,}"),
        ("Win rate", f"{s['win_rate']:.2f}%  ({s['wins']:,}W / {s['losses']:,}L)"),
        ("Profit factor", f"{s['profit_factor']}"),
        ("Avg win / loss", f"{s['avg_win']:,.2f} / {s['avg_loss']:,.2f}"),
        ("Expectancy/trade", f"{s['expectancy']:,.2f}"),
        ("Largest win/loss", f"{s['largest_win']:,.2f} / {s['largest_loss']:,.2f}"),
        ("Max drawdown", f"{s['max_drawdown']:,.2f}  ({s['max_drawdown_pct']:.2f}%)"),
        ("Max consec W/L", f"{s['max_consec_wins']} / {s['max_consec_losses']}"),
        ("Long / Short", f"{s['long_trades']:,} ({s['long_win_rate']}%) / "
                          f"{s['short_trades']:,} ({s['short_win_rate']}%)"),
        ("Avg bars held", f"{s['avg_bars_held']}"),
    ]
    for k, val in rows:
        print(f"  {k:<18} {C.bold(val)}")
    print("  " + C.grey("by trigger:"))
    for name, d in s["by_trigger"].items():
        print(f"    {name:<28} {d['trades']:>6,} trades  "
              f"WR {d['win_rate']:>5.1f}%  net {d['net_pnl']:>12,.2f}")
    print("  " + C.grey("by exit:"))
    for name, d in s["by_exit"].items():
        print(f"    {name:<28} {d['count']:>6,}  net {d['net_pnl']:>12,.2f}")
    print(line + "\n")


# ---------------------------------------------------------------------------
# Output writers
# ---------------------------------------------------------------------------
def write_results(path, stats, closed, equity_points, params, capital, epoch,
                  ruin_info=None, i_start=0, i_end=None):
    if i_end is None: i_end = len(epoch)
    # downsample equity curve to keep the file light
    pts = [(int(epoch[i_start]), round(capital, 2))] + [[t, round(e, 2)] for t, e in equity_points]
    max_pts = 8000
    if len(pts) > max_pts:
        step = len(pts) / max_pts
        idx = sorted(set(int(i * step) for i in range(max_pts)) | {len(pts) - 1})
        pts = [pts[i] for i in idx]
    pts = [[int(t), float(e)] for t, e in pts]

    doc = {
        "meta": {
            "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
            "data_start": ts_str(epoch[0]),
            "data_end": ts_str(epoch[-1]),
            "window_start": ts_str(epoch[i_start]),
            "window_end": ts_str(epoch[i_end-1]),
            "bars": int(len(epoch)),
            "window_bars": int(i_end - i_start),
            "same_bar_fill": "stop-loss first (conservative)",
            "spread": round(float(getattr(params, "spread", 0.2)), 6),
            "ruined": bool(ruin_info),
            "ruin_date": ruin_info["date"] if ruin_info else None,
            "params": {k: v for k, v in vars(params).items()},
        },
        "stats": stats,
        "equity_curve": pts,
        "trades": closed,
    }
    with open(path, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
    import os
    print(f"  wrote {path} ({os.path.getsize(path)/1e6:.1f} MB, {len(closed):,} trades)")


def write_chart_slice(path, epoch, o, h, l, c, v, chart_days, closed,
                      ema_fast=None, ema_slow=None, max_bars=250000):
    """Export a candle window that actually contains the trades, so the chart
    has positions to draw. Window = [first entry, last exit] padded by ~1 day.
    If that span exceeds `chart_days`, keep the most recent `chart_days`. The
    result is capped at `max_bars` candles (keeping the most recent) for browser
    performance."""
    last = int(epoch[-1])
    pad = 86400  # 1 day padding on each side
    if closed:
        t0 = min(t["entry_time"] for t in closed) - pad
        t1 = max(t["exit_time"] for t in closed) + pad
        if (t1 - t0) > chart_days * 86400:
            t0 = t1 - int(chart_days * 86400)
    else:
        t1 = last
        t0 = last - int(chart_days * 86400)
    start = int(np.searchsorted(epoch, t0))
    stop = int(np.searchsorted(epoch, t1, side="right"))
    if stop - start > max_bars:
        start = stop - max_bars
    sl = slice(start, stop)
    rows = []
    es, os_, hs, ls, cs, vs = epoch[sl], o[sl], h[sl], l[sl], c[sl], v[sl]
    for k in range(len(es)):
        rows.append([int(es[k]), round(float(os_[k]), 2), round(float(hs[k]), 2),
                     round(float(ls[k]), 2), round(float(cs[k]), 2), float(vs[k])])
    ef = [[int(es[k]), round(float(ema_fast[sl][k]), 2)] for k in range(len(es))] \
        if ema_fast is not None else []
    eslo = [[int(es[k]), round(float(ema_slow[sl][k]), 2)] for k in range(len(es))] \
        if ema_slow is not None else []
    doc = {
        "columns": ["time", "open", "high", "low", "close", "volume"],
        "from": ts_str(es[0]), "to": ts_str(es[-1]), "count": len(rows),
        "candles": rows,
        "ema_fast": ef,
        "ema_slow": eslo,
    }
    with open(path, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
    import os
    print(f"  wrote {path} ({os.path.getsize(path)/1e6:.1f} MB, {len(rows):,} candles, "
          f"{ts_str(es[0])} -> {ts_str(es[-1])})")


# ---------------------------------------------------------------------------
def parse_dt(s):
    """Accept 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM' -> epoch seconds UTC."""
    if not s: return None
    s = s.strip()
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return int(datetime.strptime(s, fmt).replace(tzinfo=timezone.utc).timestamp())
        except ValueError:
            continue
    raise ValueError(f"Unparseable date: {s!r}  (use YYYY-MM-DD or 'YYYY-MM-DD HH:MM')")


def run_once(epoch, o, h, l, c, v, *, capital, params, start_ts=None, end_ts=None,
             results_path="results.json", chart_path="5m_candles_chart.json",
             chart_days=730.0, print_every=1, quiet=False, ruin_floor=0.01):
    """Reusable wrapper used by main() and by serve.py. Returns the stats dict."""
    closed, equity_points, initial, realized, ruin_info, i_start, i_end = run(
        epoch, o, h, l, c, v, params, capital,
        print_every=print_every, quiet=quiet, ruin_floor=ruin_floor,
        start_ts=start_ts, end_ts=end_ts)

    stats = compute_stats(closed, equity_points, initial, realized, epoch, i_start, i_end)
    if ruin_info:
        stats["ruined"] = True
        stats["ruin_date"] = ruin_info["date"]
    print_summary(stats)

    print("Writing outputs ...", flush=True)
    write_results(results_path, stats, closed, equity_points, params, initial, epoch,
                  ruin_info, i_start, i_end)
    ema_fast = S.ema(c, params.ema_fast_len)
    ema_slow = S.ema(c, params.ema_slow_len)
    write_chart_slice(chart_path, epoch, o, h, l, c, v, chart_days, closed,
                      ema_fast, ema_slow)
    return stats


def main():
    ap = argparse.ArgumentParser(description="Backtest the Ultimate-script strategy.")
    ap.add_argument("--data", default="5m_candles.json")
    ap.add_argument("--capital", type=float, default=10000.0)
    ap.add_argument("--start", default=None,
                    help="trading window start (YYYY-MM-DD or 'YYYY-MM-DD HH:MM' UTC)")
    ap.add_argument("--end", default=None,
                    help="trading window end (YYYY-MM-DD or 'YYYY-MM-DD HH:MM' UTC)")
    ap.add_argument("--results", default="results.json")
    ap.add_argument("--chart-out", default="5m_candles_chart.json")
    ap.add_argument("--chart-days", type=float, default=730.0,
                    help="how many recent days of candles to export for the HTML chart")
    ap.add_argument("--print-every", type=int, default=1,
                    help="print 1 of every N trades (1 = print all)")
    ap.add_argument("--quiet", action="store_true", help="suppress per-trade output")
    ap.add_argument("--ruin-floor", type=float, default=0.01,
                    help="halt when equity falls below this fraction of starting "
                         "capital (default 0.01 = -99%%); 0 disables the halt")
    ap.add_argument("--tz-offset", type=float, default=0.0,
                    help="hours to add to CSV timestamps to reach UTC")
    ap.add_argument("--ny-session", action="store_true",
                    help="only open entries during the New York session "
                         "(17:00-23:00 UTC)")
    ap.add_argument("--session-start-hr", type=int, default=17,
                    help="entry-window start hour UTC (with --ny-session)")
    ap.add_argument("--session-end-hr", type=int, default=23,
                    help="entry-window end hour UTC, exclusive (with --ny-session)")
    args = ap.parse_args()

    params = S.Params(tz_offset_hours=args.tz_offset,
                      session_filter_enable=args.ny_session,
                      sess_start_hr=args.session_start_hr,
                      sess_end_hr=args.session_end_hr)
    epoch, o, h, l, c, v = load_candles(args.data)
    run_once(epoch, o, h, l, c, v,
             capital=args.capital, params=params,
             start_ts=parse_dt(args.start), end_ts=parse_dt(args.end),
             results_path=args.results, chart_path=args.chart_out,
             chart_days=args.chart_days, print_every=args.print_every,
             quiet=args.quiet, ruin_floor=args.ruin_floor)
    print(C.bold("Done."))


if __name__ == "__main__":
    main()
