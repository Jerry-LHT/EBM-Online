"""Debug artifact helpers for targeted extraction runs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def debug_dir_for(context_id: str) -> Path | None:
    root = os.environ.get("SUBTASK2_TARGETED_DEBUG_DIR")
    if not root:
        return None
    safe_id = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in context_id)[:180]
    return Path(root) / safe_id


def write_debug_artifact(*, path: Path | None, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.mkdir(parents=True, exist_ok=True)
    (path / "state.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False), encoding="utf-8")


def write_named_debug_artifact(*, path: Path | None, filename: str, payload: dict[str, Any]) -> None:
    if path is None:
        return
    path.mkdir(parents=True, exist_ok=True)
    (path / filename).write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False), encoding="utf-8")
