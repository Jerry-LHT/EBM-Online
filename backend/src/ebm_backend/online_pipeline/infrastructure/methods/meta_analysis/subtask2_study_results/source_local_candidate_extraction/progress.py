"""Progress logging for targeted extraction runs."""

from __future__ import annotations

import sys
from typing import Any


class ProgressLogger:
    def __init__(self, *, enabled: bool = True) -> None:
        self.enabled = enabled

    def log(self, message: str, **fields: Any) -> None:
        if not self.enabled:
            return
        suffix = ""
        if fields:
            suffix = " " + " ".join(f"{key}={value}" for key, value in fields.items())
        print(f"[subtask2-targeted] {message}{suffix}", file=sys.stderr, flush=True)
