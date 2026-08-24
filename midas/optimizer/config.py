"""Walk-forward configuration — the knobs of the *search*, not of the strategy."""

from __future__ import annotations

from dataclasses import dataclass, field

from .objective import DEFAULT_METRIC, normalise_metric

WARMUP_BARS = 30000          # bars kept before base_start for EMA warm-up


@dataclass(frozen=True)
class WalkForwardConfig:
    groups: list = field(default_factory=lambda: ["t1", "t2", "t3", "exposure"])
    trials: int = 80
    final_trials: int = 120
    n_parts: int = 5
    base_start: str = "2024-01-01"
    base_end: str | None = None
    end_ts: int | None = None
    capital: float = 10000.0
    ruin_floor: float = 0.01
    min_trades_fold: int = 15
    min_trades_final: int = 60
    max_dd_pct: float = 30.0
    objective_metric: str = DEFAULT_METRIC
    base_params: dict | None = None   # UI edit settings -> the non-tuned fields
    seed: int = 42

    def __post_init__(self):
        object.__setattr__(self, "objective_metric",
                           normalise_metric(self.objective_metric))

    @classmethod
    def from_request(cls, body: dict) -> "WalkForwardConfig":
        """Build from an HTTP body, coercing the fields the browser can send."""
        body = body or {}
        return cls(
            groups=body.get("groups") or ["t1", "t2", "t3", "exposure"],
            trials=int(body.get("trials", 80)),
            final_trials=int(body.get("final_trials", 120)),
            n_parts=int(body.get("n_parts", 5)),
            base_start=body.get("base_start", "2024-01-01"),
            base_end=body.get("base_end") or None,
            capital=float(body.get("capital", 10000.0)),
            max_dd_pct=float(body.get("max_dd_pct", 30.0)),
            objective_metric=body.get("objective_metric", DEFAULT_METRIC),
            base_params=body.get("params") or None,
        )
