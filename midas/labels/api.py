"""The labeller's JSON API: three routes over the label store.

Same shape as the viewer's `ViewerApi` — dict in, `Response` out, nothing here
touches a socket — so `midas/server/app.py` serves it unchanged.

Deleting is a POST, not a DELETE, because the shared request handler speaks
GET and POST and one extra route is cheaper than a new HTTP verb.
"""

from __future__ import annotations

from ..server.http import Response, error, ok
from .store import DAILY_QUOTA, LabelError, LabelStore


class LabelApi:
    def __init__(self, store: LabelStore):
        self.store = store
        self.routes = {
            ("GET", "/api/labels"): self.list_labels,
            ("POST", "/api/labels"): self.add_label,
            ("POST", "/api/labels/delete"): self.delete_label,
        }

    def handle(self, method: str, path: str, body: dict) -> Response | None:
        handler = self.routes.get((method, path))
        if handler is None:
            return None
        try:
            return handler(body)
        except LabelError as exc:
            return error(400, str(exc))
        except Exception as exc:                      # pragma: no cover
            return error(500, f"{type(exc).__name__}: {exc}")

    def list_labels(self, _body: dict) -> Response:
        """Every label plus the daily quota, which is defined once, here."""
        return ok({"ok": True, "quota": DAILY_QUOTA, "labels": self.store.all()})

    def add_label(self, body: dict) -> Response:
        label = self.store.add(body.get("tf"), body.get("start_ts"), body.get("end_ts"),
                               body.get("bars"), body.get("trend"))
        return ok({"ok": True, "label": label})

    def delete_label(self, body: dict) -> Response:
        if not self.store.delete(body.get("id", -1)):
            return error(404, "no such label")
        return ok({"ok": True})
