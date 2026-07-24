"""Runtime storage configuration."""

from __future__ import annotations

import os
from pathlib import Path


DEFAULT_RUNTIME_DIR = ".runtime/online_pipeline"


def get_runtime_root() -> Path:
    """Resolve the non-secret local runtime directory without creating it."""

    configured = os.getenv("EBM_RUNTIME_DIR", DEFAULT_RUNTIME_DIR).strip()
    path = Path(configured or DEFAULT_RUNTIME_DIR)
    return path if path.is_absolute() else Path.cwd() / path
