"""`python3 serve.py` — the local viewer server.

    GET  /                    -> index.html
    GET  /<file>              -> static file from the repo root
    GET  /api/last            -> the last run's stats
    GET  /api/defaults        -> strategy defaults, for "Reset to defaults"
    GET  /api/optimize/status -> progress of the background optimisation
    POST /api/run             -> re-run the backtest with the posted parameters
    POST /api/optimize/estimate | /api/optimize/start

The candle file (~67 MB) is loaded once at startup and kept in memory, so each
re-run is fast.
"""

from __future__ import annotations

import argparse

from ..app.loading import load_series
from ..server.app import create_server
from ..server.state import ViewerState


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the MidasScript viewer.")
    parser.add_argument("--data", default="5m_candles.json")
    parser.add_argument("--port", type=int, default=8765)
    return parser


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    state = ViewerState()
    print(f"Loading candles ({args.data}) ...", flush=True)
    state.load(args.data, load_series)
    server = create_server(state, args.port)
    print(f"Serving http://localhost:{args.port}/  (Ctrl-C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
        server.shutdown()
