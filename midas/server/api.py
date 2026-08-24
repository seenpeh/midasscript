"""The viewer's JSON API.

Each endpoint is a plain method: dict in, `Response` out. Nothing here knows
about sockets, and the work itself is delegated to the same application services
the CLI uses — so the browser and the terminal can never drift apart.
"""

from __future__ import annotations

import json
import os
import time as _time

from ..app.backtest_run import OutputSettings, run_backtest
from ..config.params import ParamError, Params
from ..engine.backtester import ExecutionSettings
from ..optimizer.config import WalkForwardConfig
from ..optimizer.walkforward import WalkForwardOptimizer, prepare_series
from ..reporting.console import ConsoleObserver
from ..util.timeutil import parse_day, parse_timestamp
from .http import Response, error, ok
from .state import BackgroundJob, ViewerState

OPT_RESULTS_FILE = "opt_results.json"


class ViewerApi:
    """Routes are declared once, in `self.routes`, so adding one is one line."""

    def __init__(self, state: ViewerState, root: str):
        self.state = state
        self.root = root
        self.optimization = BackgroundJob()
        self.routes = {
            ("GET", "/api/last"): self.last_stats,
            ("GET", "/api/defaults"): self.defaults,
            ("GET", "/api/optimize/status"): self.optimization_status,
            ("POST", "/api/run"): self.run,
            ("POST", "/api/optimize/estimate"): self.estimate_optimization,
            ("POST", "/api/optimize/start"): self.start_optimization,
        }

    def handle(self, method: str, path: str, body: dict) -> Response | None:
        """The response for this route, or None when it is not an API route."""
        handler = self.routes.get((method, path))
        if handler is None:
            return None
        try:
            return handler(body)
        except (ParamError, ValueError) as exc:
            return error(400, str(exc))
        except Exception as exc:                      # pragma: no cover
            import traceback
            traceback.print_exc()
            return error(500, str(exc))

    # -- GET ---------------------------------------------------------------
    def last_stats(self, _body) -> Response:
        return Response(200, json.dumps(self.state.last_stats or {}).encode(),
                        "application/json")

    def defaults(self, _body) -> Response:
        """The code defaults, for the UI's "Reset to defaults" button."""
        return Response(200, json.dumps({"params": Params().as_dict()}).encode(),
                        "application/json")

    def optimization_status(self, _body) -> Response:
        return Response(200, json.dumps(self.optimization.status()).encode(),
                        "application/json")

    # -- POST /api/run -----------------------------------------------------
    def run(self, body: dict) -> Response:
        with self.state.try_run() as acquired:
            if not acquired:
                return error(409, "a backtest is already running, try again in a moment")
            started = _time.time()
            params = Params.from_dict(body.get("params"), strict=True)
            execution = ExecutionSettings(
                capital=float(body.get("capital", self.state.capital)),
                start_ts=parse_timestamp(body.get("start")),
                end_ts=parse_timestamp(body.get("end")))
            chart_days = float(body.get("chart_days", self.state.chart_days))

            print(f"\n>>> /api/run  capital={execution.capital} "
                  f"start={body.get('start')} end={body.get('end')} "
                  f"params={body.get('params') or {}}", flush=True)
            stats = run_backtest(self.state.series, params, execution,
                                 OutputSettings(chart_days=chart_days),
                                 ConsoleObserver(quiet=True))
            self.state.last_stats = stats
            took = _time.time() - started
            print(f"<<< /api/run done in {took:.1f}s\n", flush=True)
            return ok({"ok": True, "took": round(took, 2), "stats": stats})

    # -- POST /api/optimize/* ----------------------------------------------
    def estimate_optimization(self, body: dict) -> Response:
        optimizer = self._optimizer(WalkForwardConfig.from_request(body))
        return ok({"ok": True, **optimizer.estimate_seconds()})

    def start_optimization(self, body: dict) -> Response:
        config = WalkForwardConfig.from_request(body)
        if not self.optimization.start(lambda report: self._optimize(config, report)):
            return error(409, "an optimization is already running")
        return ok({"ok": True, "started": True})

    def _optimize(self, config: WalkForwardConfig, report_progress) -> dict:
        print(f"\n>>> /api/optimize/start groups={config.groups} "
              f"trials={config.trials} max_dd={config.max_dd_pct}", flush=True)
        started = _time.time()
        result = self._optimizer(config, report_progress).run()
        result["elapsed_s"] = round(_time.time() - started, 1)
        with open(os.path.join(self.root, OPT_RESULTS_FILE), "w") as fh:
            json.dump(result, fh)
        print(f"<<< /api/optimize done in {result['elapsed_s']}s", flush=True)
        return result

    def _optimizer(self, config: WalkForwardConfig, progress=None) -> WalkForwardOptimizer:
        series = prepare_series(
            self.state.series, parse_day(config.base_start),
            parse_day(config.base_end) if config.base_end else None)
        return WalkForwardOptimizer(series, config, progress=progress)
