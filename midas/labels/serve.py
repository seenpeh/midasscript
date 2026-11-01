"""`python3 label_serve.py` — the trend-labelling page and its API.

    GET  /                   -> label.html
    GET  /<file>             -> static file from the repo root
    GET  /api/labels         -> every label drawn so far, plus the daily quota
    POST /api/labels         -> store one rectangle
    POST /api/labels/delete  -> remove one by id

No candles are loaded here: the page fetches `5m_candles_chart.json` as a
static file and aggregates the higher timeframes in the browser, so this
server starts instantly and holds nothing but the sqlite handle.
"""

from __future__ import annotations

import argparse
import os
from http.server import ThreadingHTTPServer

from ..server.app import ROOT, build_handler
from ..server.http import StaticFiles
from .api import LabelApi
from .store import LabelStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the MidasScript trend labeller.")
    parser.add_argument("--db", default=os.path.join(ROOT, "labels.db"))
    parser.add_argument("--port", type=int, default=8766)
    return parser


def main(argv=None) -> None:
    args = build_parser().parse_args(argv)
    store = LabelStore(args.db)
    handler = build_handler(LabelApi(store), StaticFiles(ROOT, index="label.html"))
    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)
    print(f"Labels in {args.db}", flush=True)
    print(f"Serving http://localhost:{args.port}/  (Ctrl-C to stop)", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nbye")
        server.shutdown()
