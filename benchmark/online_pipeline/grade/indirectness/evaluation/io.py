"""I/O helpers for GRADE evaluation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from benchmark.online_pipeline.grade.evaluation_io import load_domain_dataset


def load_dataset(dataset: str | Path) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    return load_domain_dataset(dataset)
