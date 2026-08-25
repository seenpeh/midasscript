"""What "better" means, and how a candidate is measured.

Kept apart from the walk-forward loop on purpose: swapping the score (or the
risk budget) should not require touching the fold machinery, and the loop should
not need to know which metric is being maximised.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..engine.backtester import Backtester, ExecutionSettings
from ..engine.statistics import statistics_for

OBJECTIVES = {"sharpe": "Sharpe ratio", "sortino": "Sortino ratio",
              "calmar": "Calmar ratio (CAGR / MaxDD)"}
DEFAULT_METRIC = "calmar"


def normalise_metric(name) -> str:
    return name if name in OBJECTIVES else DEFAULT_METRIC


class Evaluator:
    """Runs the engine over one series with fixed capital and ruin rules."""

    def __init__(self, series, capital: float, ruin_floor: float):
        self.series = series
        self.capital = capital
        self.ruin_floor = ruin_floor

    def run(self, params, start_ts, end_ts, capital: float | None = None):
        """Returns (stats, result). The engine stays silent: no observer."""
        settings = ExecutionSettings(
            capital=self.capital if capital is None else capital,
            start_ts=start_ts, end_ts=end_ts, ruin_floor=self.ruin_floor)
        result = Backtester(params, settings).run(self.series)
        stats = statistics_for(result, self.series.epoch)
        if result.ruin:
            stats["ruined"] = True
        return stats, result


@dataclass(frozen=True)
class Objective:
    """Maximise a risk-adjusted ratio under a HARD drawdown cap.

    Why a cap: with geometric sizing and pyramiding, returns compound
    explosively, so even ratio objectives drift toward near-ruin configurations.
    Constraining MaxDD <= `dd_cap` and maximising the ratio *within* that
    feasible region is the standard risk-controlled approach. Rejected regions
    return graded (not constant) values so the sampler can climb toward
    feasibility instead of seeing a flat wall.
    """
    min_trades: int
    dd_cap: float
    metric: str = DEFAULT_METRIC

    NO_TRADES = -10.0
    RUINED = -8.0
    TOO_FEW_TRADES = -5.0
    UNPROFITABLE = -1.0

    def score(self, stats: dict) -> float:
        trades = stats.get("total_trades", 0)
        if trades == 0:
            return self.NO_TRADES
        if stats.get("ruined"):
            return self.RUINED
        if trades < self.min_trades:
            # nudge toward more trades
            return self.TOO_FEW_TRADES + trades / max(self.min_trades, 1)
        total_return = stats.get("return_pct", 0.0)
        if total_return <= 0:
            # ranked among themselves, but always below anything feasible
            return self.UNPROFITABLE + total_return / 10000.0
        drawdown = stats.get("max_drawdown_pct", 0.0)
        if drawdown > self.dd_cap:
            # over the risk budget -> infeasible, but prefer being closer to it
            return -0.5 * (drawdown / self.dd_cap)
        value = stats.get(self.metric)
        return float(value if value is not None else stats.get(DEFAULT_METRIC, 0.0))

    def describe(self, min_trades_final: int) -> str:
        return (f"max {OBJECTIVES.get(self.metric, self.metric)} "
                f"s.t. MaxDD<={self.dd_cap}%, no ruin, "
                f">={min_trades_final} trades")
