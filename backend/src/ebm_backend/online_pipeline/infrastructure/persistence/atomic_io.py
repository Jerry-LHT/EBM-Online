"""Small atomic filesystem primitives shared by runtime stores."""

from __future__ import annotations

import gzip
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from ebm_backend.online_pipeline.domain.serialization import to_jsonable


def atomic_write_json(path: Path, value: Any) -> None:
    payload = json.dumps(
        to_jsonable(value),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    ) + "\n"
    _atomic_write_bytes(path, payload.encode("utf-8"))


def atomic_write_gzip_text(path: Path, value: str) -> None:
    _atomic_write_bytes(path, gzip.compress(value.encode("utf-8")))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_gzip_text(path: Path) -> str:
    return gzip.decompress(path.read_bytes()).decode("utf-8")


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.",
        suffix=".tmp",
        dir=path.parent,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()
