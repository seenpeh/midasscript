"""
serve.py
========
Static file server + a small POST /api/run endpoint that re-runs the backtest
with whatever parameters the UI sends. The 5m_candles.json (~67 MB) is loaded
once at startup and kept in memory so each rerun is fast.

    python3 serve.py             # port 8765
    python3 serve.py --port 9000

Endpoints:
    GET  /                       -> redirects to /index.html
    GET  /<any file>             -> static
    POST /api/run   body JSON    -> {"ok":true, "stats":{...}, "took":<sec>}
        body fields (all optional, fall back to current defaults):
            start: "YYYY-MM-DD" or "YYYY-MM-DD HH:MM"
            end:   "YYYY-MM-DD" or "YYYY-MM-DD HH:MM"
            capital: float
            chart_days: float
            params: {<strategy.Params field>: value, ...}
"""

import argparse
import json
import os
import sys
import threading
import time as _time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import backtest as B
import strategy as S
import optimize as OPT


# ---------------------------------------------------------------------------
# Global state: candles loaded once, plus a run-lock so two clicks can't
# clobber each other.
# ---------------------------------------------------------------------------
class State:
    epoch = o = h = l = c = v = None
    capital = 10000.0
    chart_days = 730.0
    lock = threading.Lock()
    last_stats = None


def load_data(path: str):
    State.epoch, State.o, State.h, State.l, State.c, State.v = B.load_candles(path)


class OptState:
    """Background walk-forward optimisation job."""
    thread = None
    running = False
    progress = {}
    result = None
    error = None
    lock = threading.Lock()


def _cfg_from_body(body):
    obj = body.get("objective_metric", "calmar")
    if obj not in OPT.OBJECTIVES:
        obj = "calmar"
    return OPT.default_cfg(
        groups=body.get("groups") or ["t1", "t2", "t3", "exposure"],
        trials=int(body.get("trials", 80)),
        final_trials=int(body.get("final_trials", 120)),
        n_parts=int(body.get("n_parts", 5)),
        base_start=body.get("base_start", "2024-01-01"),
        base_end=(body.get("base_end") or None),
        capital=float(body.get("capital", 10000.0)),
        max_dd_pct=float(body.get("max_dd_pct", 30.0)),
        objective_metric=obj,
        base_params=(body.get("params") or None),   # UI edit settings -> non-tuned params
    )


# ---------------------------------------------------------------------------
# HTTP handler
# ---------------------------------------------------------------------------
ROOT = os.path.dirname(os.path.abspath(__file__))
MIME = {".html":"text/html",".js":"application/javascript",".css":"text/css",
        ".json":"application/json",".svg":"image/svg+xml",".ico":"image/x-icon",
        ".png":"image/png",".jpg":"image/jpeg"}


class Handler(BaseHTTPRequestHandler):
    # quieter access log
    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

    def _send(self, code, body=b"", ctype="text/plain", extra=None):
        if isinstance(body, str): body = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra:
            for k, v in extra.items(): self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD": self.wfile.write(body)

    # --- static ---
    def do_GET(self):
        url = urlparse(self.path)
        path = url.path
        if path == "/": path = "/index.html"
        if path == "/api/last":
            body = json.dumps(State.last_stats or {}).encode()
            return self._send(200, body, "application/json")
        if path == "/api/defaults":
            # strategy.py code defaults, for the "Reset to defaults" button
            return self._send(200, json.dumps({"params": vars(S.Params())}),
                              "application/json")
        if path == "/api/optimize/status":
            return self._send(200, json.dumps({
                "running": OptState.running,
                "progress": OptState.progress,
                "error": OptState.error,
                "done": OptState.result is not None and not OptState.running,
                "result": OptState.result,
            }), "application/json")
        # disallow path traversal
        safe = os.path.normpath(path.lstrip("/"))
        if safe.startswith("..") or os.path.isabs(safe):
            return self._send(403, "forbidden")
        fp = os.path.join(ROOT, safe)
        if not os.path.isfile(fp):
            return self._send(404, f"not found: {path}")
        ext = os.path.splitext(fp)[1].lower()
        with open(fp, "rb") as f: data = f.read()
        return self._send(200, data, MIME.get(ext, "application/octet-stream"))

    # --- run ---
    def do_POST(self):
        route = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw or b"{}")
        except json.JSONDecodeError as e:
            return self._send(400, json.dumps({"ok": False, "error": f"bad json: {e}"}),
                              "application/json")

        if route == "/api/optimize/estimate":
            return self._optimize_estimate(body)
        if route == "/api/optimize/start":
            return self._optimize_start(body)
        if route != "/api/run":
            return self._send(404, "unknown endpoint")

        if not State.lock.acquire(blocking=False):
            return self._send(409, json.dumps({"ok": False,
                "error": "a backtest is already running, try again in a moment"}),
                "application/json")
        try:
            t0 = _time.time()
            params = S.Params()                       # defaults
            for k, val in (body.get("params") or {}).items():
                if hasattr(params, k):
                    # cast bools/ints/floats to the field's existing type
                    cur = getattr(params, k)
                    try:
                        if isinstance(cur, bool):    val = bool(val)
                        elif isinstance(cur, int):   val = int(val)
                        elif isinstance(cur, float): val = float(val)
                    except (TypeError, ValueError):
                        return self._send(400, json.dumps({"ok": False,
                            "error": f"bad value for {k}: {val!r}"}), "application/json")
                    setattr(params, k, val)

            capital = float(body.get("capital", State.capital))
            chart_days = float(body.get("chart_days", State.chart_days))
            try:
                start_ts = B.parse_dt(body.get("start"))
                end_ts = B.parse_dt(body.get("end"))
            except ValueError as e:
                return self._send(400, json.dumps({"ok": False, "error": str(e)}),
                                  "application/json")

            print(f"\n>>> /api/run  capital={capital} start={body.get('start')} "
                  f"end={body.get('end')} params={body.get('params') or {}}",
                  flush=True)
            stats = B.run_once(
                State.epoch, State.o, State.h, State.l, State.c, State.v,
                capital=capital, params=params,
                start_ts=start_ts, end_ts=end_ts,
                chart_days=chart_days, quiet=True,
            )
            State.last_stats = stats
            took = _time.time() - t0
            print(f"<<< /api/run done in {took:.1f}s\n", flush=True)
            return self._send(200, json.dumps(
                {"ok": True, "took": round(took, 2), "stats": stats}),
                "application/json")
        except Exception as e:
            import traceback; traceback.print_exc()
            return self._send(500, json.dumps({"ok": False, "error": str(e)}),
                              "application/json")
        finally:
            State.lock.release()

    # --- optimization: estimate time ---
    def _optimize_estimate(self, body):
        try:
            cfg = _cfg_from_body(body)
            arrays = OPT.prepare_arrays(
                (State.epoch, State.o, State.h, State.l, State.c, State.v),
                OPT.to_ts(cfg["base_start"]),
                OPT.to_ts(cfg["base_end"]) if cfg.get("base_end") else None)
            est = OPT.estimate_seconds(arrays, cfg)
            if "error" in est:
                return self._send(400, json.dumps({"ok": False, "error": est["error"]}),
                                  "application/json")
            return self._send(200, json.dumps({"ok": True, **est}), "application/json")
        except Exception as e:
            import traceback; traceback.print_exc()
            return self._send(500, json.dumps({"ok": False, "error": str(e)}),
                              "application/json")

    # --- optimization: start background walk-forward ---
    def _optimize_start(self, body):
        with OptState.lock:
            if OptState.running:
                return self._send(409, json.dumps({"ok": False,
                    "error": "an optimization is already running"}), "application/json")
            try:
                cfg = _cfg_from_body(body)
            except Exception as e:
                return self._send(400, json.dumps({"ok": False, "error": str(e)}),
                                  "application/json")
            OptState.running = True
            OptState.result = None
            OptState.error = None
            OptState.progress = {"phase": "starting", "pct": 0}

        def worker():
            try:
                arrays = OPT.prepare_arrays(
                    (State.epoch, State.o, State.h, State.l, State.c, State.v),
                    OPT.to_ts(cfg["base_start"]),
                    OPT.to_ts(cfg["base_end"]) if cfg.get("base_end") else None)

                def on_prog(d):
                    cur = dict(OptState.progress)
                    cur.update(d)
                    OptState.progress = cur

                print(f"\n>>> /api/optimize/start groups={cfg['groups']} "
                      f"trials={cfg['trials']} max_dd={cfg['max_dd_pct']}", flush=True)
                t0 = _time.time()
                res = OPT.run_walkforward(arrays, cfg, progress=on_prog)
                res["elapsed_s"] = round(_time.time() - t0, 1)
                with open(os.path.join(ROOT, "opt_results.json"), "w") as f:
                    json.dump(res, f)
                OptState.result = res
                OptState.progress = {"phase": "done", "pct": 100}
                print(f"<<< /api/optimize done in {res['elapsed_s']}s", flush=True)
            except Exception as e:
                import traceback; traceback.print_exc()
                OptState.error = str(e)
                OptState.progress = {"phase": "error"}
            finally:
                OptState.running = False

        OptState.thread = threading.Thread(target=worker, daemon=True)
        OptState.thread.start()
        return self._send(200, json.dumps({"ok": True, "started": True}),
                          "application/json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="5m_candles.json")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    print(f"Loading candles ({args.data}) ...", flush=True)
    load_data(args.data)
    print(f"Serving http://localhost:{args.port}/  (Ctrl-C to stop)", flush=True)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
        srv.shutdown()


if __name__ == "__main__":
    main()
