"""Unit tests for the trend-label store and its API.

    python3 -m unittest discover tests

Everything runs against an in-memory sqlite database, so no file is touched.
"""

import json
import unittest

from midas.labels.api import LabelApi
from midas.labels.store import DAILY_QUOTA, LabelError, LabelStore


def body(response):
    return json.loads(response.body)


class LabelStoreTest(unittest.TestCase):
    def setUp(self):
        self.store = LabelStore(":memory:")

    def test_round_trip_keeps_every_field(self):
        label = self.store.add("1h", 1000, 1300, 2, "up")
        self.assertEqual(
            {k: label[k] for k in ("tf", "start_ts", "end_ts", "bars", "trend")},
            {"tf": "1h", "start_ts": 1000, "end_ts": 1300, "bars": 2, "trend": "up"})
        self.assertEqual(self.store.all(), [label])

    def test_overlapping_labels_are_refused(self):
        self.store.add("1h", 1000, 2000, 4, "up")
        for start, end in [(1500, 2500), (500, 1200), (1200, 1400), (900, 2100)]:
            with self.assertRaises(LabelError):
                self.store.add("1h", start, end, 2, "down")
        # touching but not overlapping is fine
        self.store.add("1h", 2300, 2600, 2, "down")
        self.assertEqual(len(self.store.all()), 2)

    def test_timeframes_do_not_collide(self):
        self.store.add("1h", 1000, 2000, 4, "up")
        self.store.add("4h", 1000, 2000, 1, "down")      # same candles, other tf
        self.assertEqual(len(self.store.all()), 2)

    def test_bad_fields_are_refused(self):
        for bad in [("5m", 1, 2, 1, "up"),             # no quota, not labellable
                    ("1h", 1, 2, 1, "flat"),
                    ("1h", 9, 2, 1, "up"),              # ends before it starts
                    ("1h", 1, 2, 0, "up"),
                    ("1h", "x", 2, 1, "up")]:
            with self.assertRaises(LabelError):
                self.store.add(*bad)
        self.assertEqual(self.store.all(), [])

    def test_delete_reports_whether_a_row_went(self):
        label = self.store.add("4h", 1000, 2000, 2, "side")
        self.assertTrue(self.store.delete(label["id"]))
        self.assertFalse(self.store.delete(label["id"]))
        self.assertEqual(self.store.all(), [])


class LabelApiTest(unittest.TestCase):
    def setUp(self):
        self.api = LabelApi(LabelStore(":memory:"))

    def post(self, path, payload):
        return self.api.handle("POST", path, payload)

    def test_unknown_route_is_not_ours(self):
        self.assertIsNone(self.api.handle("GET", "/label.html", {}))

    def test_list_carries_the_quota(self):
        payload = body(self.api.handle("GET", "/api/labels", {}))
        self.assertEqual(payload["quota"], DAILY_QUOTA)
        self.assertEqual(payload["labels"], [])

    def test_add_then_delete(self):
        label = body(self.post("/api/labels", {
            "tf": "4h", "start_ts": 10, "end_ts": 20, "bars": 2, "trend": "down"}))["label"]
        self.assertEqual(
            len(body(self.api.handle("GET", "/api/labels", {}))["labels"]), 1)
        self.assertEqual(self.post("/api/labels/delete", {"id": label["id"]}).status, 200)
        self.assertEqual(self.post("/api/labels/delete", {"id": label["id"]}).status, 404)

    def test_a_refused_label_answers_400_not_a_crash(self):
        response = self.post("/api/labels", {"tf": "1h", "trend": "up"})
        self.assertEqual(response.status, 400)
        self.assertFalse(body(response)["ok"])


if __name__ == "__main__":
    unittest.main()
