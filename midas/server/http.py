"""Minimal HTTP plumbing: a response value object and a static-file server.

Route handlers return `Response` objects and never touch a socket, which is what
lets them be called directly from a test.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

MIME_TYPES = {".html": "text/html", ".js": "application/javascript",
              ".css": "text/css", ".json": "application/json",
              ".svg": "image/svg+xml", ".ico": "image/x-icon",
              ".png": "image/png", ".jpg": "image/jpeg"}
DEFAULT_MIME = "application/octet-stream"


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes = b""
    content_type: str = "text/plain"
    headers: dict = field(default_factory=dict)


def json_response(status: int, payload: dict) -> Response:
    return Response(status, json.dumps(payload).encode(), "application/json")


def ok(payload: dict) -> Response:
    return json_response(200, payload)


def error(status: int, message: str) -> Response:
    return json_response(status, {"ok": False, "error": message})


def text(status: int, message: str) -> Response:
    return Response(status, message.encode(), "text/plain")


class StaticFiles:
    """Serves files from one directory and refuses to leave it."""

    def __init__(self, root: str, index: str = "index.html"):
        self.root = os.path.abspath(root)
        self.index = index

    def serve(self, path: str) -> Response:
        if path == "/":
            path = "/" + self.index
        relative = os.path.normpath(path.lstrip("/"))
        if relative.startswith("..") or os.path.isabs(relative):
            return text(403, "forbidden")
        full = os.path.join(self.root, relative)
        if not os.path.isfile(full):
            return text(404, f"not found: {path}")
        with open(full, "rb") as fh:
            body = fh.read()
        mime = MIME_TYPES.get(os.path.splitext(full)[1].lower(), DEFAULT_MIME)
        return Response(200, body, mime)
