"""The HTTP transport: read a request, hand it to the API, write the response.

Everything this class does is protocol mechanics. Anything that decides *what*
to answer lives in `ViewerApi`, and anything that decides how to backtest lives
below that again.
"""

from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from .api import ViewerApi
from .http import StaticFiles, error
from .state import ViewerState

# <repo>/midas/server/app.py -> <repo>: index.html and the JSON artefacts
# the viewer fetches live next to the package, not inside it.
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def build_handler(api: ViewerApi, static: StaticFiles):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):            # quieter access log
            sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))

        def do_GET(self):
            path = urlparse(self.path).path
            response = api.handle("GET", path, {}) or static.serve(path)
            self._write(response)

        do_HEAD = do_GET

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                body = self._read_json()
            except json.JSONDecodeError as exc:
                return self._write(error(400, f"bad json: {exc}"))
            response = api.handle("POST", path, body)
            self._write(response or error(404, f"unknown endpoint: {path}"))

        # -- plumbing ------------------------------------------------------
        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            return json.loads(raw or b"{}")

        def _write(self, response):
            self.send_response(response.status)
            self.send_header("Content-Type", response.content_type)
            self.send_header("Content-Length", str(len(response.body)))
            self.send_header("Cache-Control", "no-store")
            for key, value in response.headers.items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(response.body)

    return Handler


def create_server(state: ViewerState, port: int, root: str = ROOT):
    api = ViewerApi(state, root)
    return ThreadingHTTPServer(("127.0.0.1", port), build_handler(api, StaticFiles(root)))
