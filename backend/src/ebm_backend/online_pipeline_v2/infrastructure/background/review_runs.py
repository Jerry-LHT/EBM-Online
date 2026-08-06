"""Single-process background execution adapter for Review Runs."""

from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Callable


class ThreadReviewRunDispatcher:
    def __init__(self, run: Callable[[str], object]) -> None:
        self._run = run
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="ebm-review-run",
        )
        self._active: set[str] = set()
        self._lock = Lock()

    def submit(self, run_id: str) -> bool:
        with self._lock:
            if run_id in self._active:
                return False
            self._active.add(run_id)
        future = self._executor.submit(self._run, run_id)
        future.add_done_callback(lambda _: self._finished(run_id))
        return True

    def _finished(self, run_id: str) -> None:
        with self._lock:
            self._active.discard(run_id)
