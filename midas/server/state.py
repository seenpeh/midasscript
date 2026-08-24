"""Server-side state: the loaded candles, and the one background job slot.

Both are shared across threads, so both guard themselves — a route handler
should never have to remember to take a lock.
"""

from __future__ import annotations

import threading


class ViewerState:
    """The candle series (loaded once, ~67 MB) plus the defaults a run falls
    back to, and a lock so two clicks cannot run two backtests at once."""

    def __init__(self, capital: float = 10000.0, chart_days: float = 730.0):
        self.series = None
        self.capital = capital
        self.chart_days = chart_days
        self.last_stats = None
        self._run_lock = threading.Lock()

    def load(self, path: str, loader) -> None:
        self.series = loader(path)

    def try_run(self):
        """Context manager that yields False when a run is already in flight."""
        return _RunSlot(self._run_lock)


class _RunSlot:
    def __init__(self, lock):
        self._lock = lock
        self.acquired = False

    def __enter__(self) -> bool:
        self.acquired = self._lock.acquire(blocking=False)
        return self.acquired

    def __exit__(self, *exc_info) -> bool:
        if self.acquired:
            self._lock.release()
        return False


class BackgroundJob:
    """One long-running task with progress, a result, and an error slot.

    The optimizer needs to report progress to a polling browser; this keeps that
    bookkeeping out of both the optimizer and the request handler.
    """

    def __init__(self):
        self.thread = None
        self.running = False
        self.progress = {}
        self.result = None
        self.error = None
        self._lock = threading.Lock()

    def start(self, work) -> bool:
        """Begin `work(report_progress)` in a daemon thread. False if busy."""
        with self._lock:
            if self.running:
                return False
            self.running = True
            self.result = None
            self.error = None
            self.progress = {"phase": "starting", "pct": 0}

        def runner():
            try:
                self.result = work(self.report)
                self.progress = {"phase": "done", "pct": 100}
            except Exception as exc:                  # surfaced to the browser
                import traceback
                traceback.print_exc()
                self.error = str(exc)
                self.progress = {"phase": "error"}
            finally:
                self.running = False

        self.thread = threading.Thread(target=runner, daemon=True)
        self.thread.start()
        return True

    def report(self, update: dict) -> None:
        merged = dict(self.progress)
        merged.update(update)
        self.progress = merged

    def status(self) -> dict:
        return {"running": self.running, "progress": self.progress,
                "error": self.error,
                "done": self.result is not None and not self.running,
                "result": self.result}
