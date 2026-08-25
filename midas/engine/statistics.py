"""Performance statistics for a finished run.

Everything here reads *booked* PnL — the figure rounded to the cent that the
trade record carries — so the summary, the JSON file and the browser can never
disagree about a total by a fraction of a cent.
"""

from __future__ import annotations

import numpy as np

from ..util.timeutil import to_utc

SECONDS_PER_YEAR = 365.25 * 86400
MONTHS_PER_YEAR = 12
MIN_DRAWDOWN_FOR_CALMAR = 1.0     # floor DD at 1% so a fluke cannot blow Calmar up


def compute_statistics(trades, equity_points, initial, realized, epoch,
                       first_bar: int = 0, last_bar: int | None = None) -> dict:
    """The stats block shared by the terminal summary, results.json and the UI."""
    last_bar = len(epoch) if last_bar is None else last_bar
    if not trades:
        return {"total_trades": 0, "note": "no trades generated"}

    records = [t.as_dict() if hasattr(t, "as_dict") else t for t in trades]
    pnl = np.array([r["pnl"] for r in records], dtype=np.float64)
    wins, losses = pnl[pnl > 0], pnl[pnl < 0]
    gross_profit, gross_loss = float(wins.sum()), float(-losses.sum())

    max_dd, max_dd_pct = _drawdown(equity_points, initial)
    win_streak, loss_streak = _streaks(pnl)

    span_years = max((epoch[last_bar - 1] - epoch[first_bar]) / SECONDS_PER_YEAR, 1e-9)
    final_equity = initial + realized
    cagr = ((final_equity / initial) ** (1 / span_years) - 1) * 100 \
        if final_equity > 0 else -100.0

    sharpe, sortino = _risk_adjusted(
        _monthly_returns(equity_points, initial, epoch[first_bar], epoch[last_bar - 1]))

    longs = [r for r in records if r["direction"] == "long"]
    shorts = [r for r in records if r["direction"] == "short"]

    return {
        "initial_capital": round(initial, 2),
        "final_equity": round(final_equity, 2),
        "net_profit": round(realized, 2),
        "return_pct": round(realized / initial * 100, 2),
        "cagr_pct": round(cagr, 2),
        "total_trades": len(records),
        "wins": int((pnl > 0).sum()),
        "losses": int((pnl < 0).sum()),
        "breakeven": int((pnl == 0).sum()),
        "win_rate": round(float((pnl > 0).sum()) / len(records) * 100, 2),
        "profit_factor": round(gross_profit / gross_loss, 3) if gross_loss > 0 else None,
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "avg_trade": round(float(pnl.mean()), 2),
        "avg_win": round(float(wins.mean()), 2) if len(wins) else 0.0,
        "avg_loss": round(float(losses.mean()), 2) if len(losses) else 0.0,
        "expectancy": round(float(pnl.mean()), 2),
        "largest_win": round(float(pnl.max()), 2),
        "largest_loss": round(float(pnl.min()), 2),
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd_pct, 2),
        "sharpe": round(sharpe, 3),
        "sortino": round(sortino, 3),
        "calmar": round(cagr / max(max_dd_pct, MIN_DRAWDOWN_FOR_CALMAR), 3),
        "max_consec_wins": win_streak,
        "max_consec_losses": loss_streak,
        "avg_bars_held": round(float(np.mean([r["bars_held"] for r in records])), 1),
        "long_trades": len(longs),
        "short_trades": len(shorts),
        "long_win_rate": win_rate(longs),
        "short_win_rate": win_rate(shorts),
        "by_trigger": _group(records, "reason",
                             lambda g: {"trades": len(g), "win_rate": win_rate(g),
                                        "net_pnl": _net(g)}),
        "by_exit": _group(records, "exit_reason",
                          lambda g: {"count": len(g), "net_pnl": _net(g)}),
    }


def statistics_for(result, epoch) -> dict:
    """Convenience wrapper for a `BacktestResult`."""
    return compute_statistics(result.trades, result.equity_points, result.initial,
                              result.realized, epoch, result.first_bar, result.last_bar)


# ---------------------------------------------------------------------------
# Pieces
# ---------------------------------------------------------------------------
def win_rate(records) -> float:
    if not records:
        return 0.0
    return round(sum(1 for r in records if r["pnl"] > 0) / len(records) * 100, 2)


def _net(records) -> float:
    return round(sum(r["pnl"] for r in records), 2)


def _group(records, key, summarise) -> dict:
    """Group by a field, keeping first-seen order so reports are reproducible."""
    return {value: summarise([r for r in records if r[key] == value])
            for value in dict.fromkeys(r[key] for r in records)}


def _drawdown(equity_points, initial):
    """Peak-to-trough on the realised (closed-trade) equity curve."""
    equity = np.array([initial] + [e for _, e in equity_points], dtype=np.float64)
    peak = np.maximum.accumulate(equity)
    drop = peak - equity
    pct = np.where(peak > 0, drop / peak * 100, 0)
    return float(drop.max()), float(pct.max())


def _streaks(pnl):
    longest_win = longest_loss = current_win = current_loss = 0
    for value in pnl:
        if value > 0:
            current_win, current_loss = current_win + 1, 0
        elif value < 0:
            current_loss, current_win = current_loss + 1, 0
        longest_win = max(longest_win, current_win)
        longest_loss = max(longest_loss, current_loss)
    return longest_win, longest_loss


def _month_index(timestamp) -> int:
    moment = to_utc(timestamp)
    return moment.year * 12 + (moment.month - 1)


def _monthly_returns(equity_points, initial, start_ts, end_ts) -> np.ndarray:
    """Forward-filled month-end equity over [start, end] -> fractional monthly
    returns. Flat months count as 0%, which correctly lowers Sharpe."""
    if end_ts < start_ts:
        return np.array([], dtype=float)
    month_end = {}
    for timestamp, equity in equity_points:      # points are time-ascending
        month_end[_month_index(timestamp)] = equity   # last close in the month wins
    returns, previous, current = [], initial, initial
    for month in range(_month_index(start_ts), _month_index(end_ts) + 1):
        current = month_end.get(month, current)
        if previous > 0:
            returns.append(current / previous - 1.0)
        previous = current
    return np.array(returns, dtype=float)


def _risk_adjusted(monthly):
    """Annualised Sharpe and Sortino from monthly returns."""
    if monthly.size < 2:
        return 0.0, 0.0
    mean = float(monthly.mean())
    stdev = float(monthly.std(ddof=1))
    sharpe = mean / stdev * np.sqrt(MONTHS_PER_YEAR) if stdev > 0 else 0.0
    downside = float(np.sqrt(np.mean(np.minimum(monthly, 0.0) ** 2)))
    if downside > 0:
        sortino = mean / downside * np.sqrt(MONTHS_PER_YEAR)
    else:
        sortino = sharpe if mean > 0 else 0.0   # no losing months -> fall back
    return sharpe, sortino
