"""Shared safe filesystem primitives for artifact repositories."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Callable, Mapping, Sequence
from uuid import uuid4


def safe_component(value: str) -> str:
    normalized = value.strip()
    if not normalized or normalized in {".", ".."}:
        raise ValueError(
            "artifact path component must not be empty or relative"
        )
    if "/" in normalized or "\\" in normalized:
        raise ValueError(
            "artifact path component must not contain path separators"
        )
    return normalized


def safe_filename(value: str) -> str:
    normalized = safe_component(value)
    if normalized.startswith("."):
        raise ValueError("artifact filename must not be hidden")
    return normalized


def safe_csv_filename(value: str) -> str:
    normalized = safe_filename(value)
    if not normalized.endswith(".csv"):
        raise ValueError("artifact filename must end with .csv")
    return normalized


def safe_relative(root: Path, name: str) -> Path:
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or not relative.parts:
        raise ValueError("unsafe artifact relative path")
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("artifact path escapes root")
    return path


def opaque_component(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def atomic_write_text(path: Path, content: str) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def atomic_write_bytes(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def atomic_write_json(path: Path, value: object) -> None:
    atomic_write_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def write_jsonl(
    path: Path,
    values: Sequence[object],
    *,
    transform: Callable[[object], object] | None = None,
) -> None:
    encode = transform or jsonable
    lines = [
        json.dumps(encode(value), ensure_ascii=False, sort_keys=True)
        for value in values
    ]
    atomic_write_text(path, "\n".join(lines) + ("\n" if lines else ""))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def digest_tag(content: bytes) -> str:
    return f"sha256:{sha256_bytes(content)}"


def validated_member(
    root: Path,
    item: object,
    *,
    label: str,
) -> Path:
    if not isinstance(item, dict):
        raise ValueError(f"{label} member is invalid")
    path = (root / str(item.get("path", ""))).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"{label} member is invalid")
    if sha256_file(path) != item.get("sha256"):
        raise ValueError(f"{label} member digest mismatch")
    return path


def read_json_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def jsonable(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "__dataclass_fields__"):
        return {
            name: jsonable(getattr(value, name))
            for name in value.__dataclass_fields__
        }
    if hasattr(value, "value") and not isinstance(value, (str, bytes)):
        return value.value
    if isinstance(value, tuple | list):
        return [jsonable(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): jsonable(item) for key, item in value.items()}
    return value
