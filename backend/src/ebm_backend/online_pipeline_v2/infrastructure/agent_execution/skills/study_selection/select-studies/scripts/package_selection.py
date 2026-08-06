#!/usr/bin/env python3
"""Validate JSONL collections and build the Agent selection manifest."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from jsonschema import Draft202012Validator


_COLLECTIONS = (
    "record-screening",
    "reports",
    "report-discoveries",
    "record-report-links",
    "report-evidence",
    "studies",
    "study-report-links",
    "study-decisions",
    "conflicts",
)
_PROHIBITED_KEYS = {"full_text", "fulltext", "raw_full_text", "document_content"}
_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "references/selection-collections.v2.schema.json"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw_collections: dict[str, list[dict[str, object]]] = {}
    for stem in _COLLECTIONS:
        source = args.input_dir / f"{stem}.jsonl"
        if not source.is_file():
            raise SystemExit(f"missing required collection: {source}")
        raw_collections[stem.replace("-", "_")] = _read_jsonl(source)
    _validate_contract(raw_collections)

    manifest_collections: dict[str, dict[str, object]] = {}
    for stem in _COLLECTIONS:
        source = args.input_dir / f"{stem}.jsonl"
        values = raw_collections[stem.replace("-", "_")]
        target = args.output_dir / source.name
        _write_jsonl(target, values)
        manifest_collections[stem.replace("-", "_")] = {
            "path": target.name,
            "sha256": _digest(target.read_bytes()),
            "record_count": len(values),
        }

    manifest = {
        "schema_version": "agent-selection-output.v3",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "collections": manifest_collections,
    }
    _atomic_write(
        args.output_dir / "manifest.json",
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return 0


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_number}: invalid JSON") from exc
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number}: item must be an object")
        _reject_full_text(value, path, line_number)
        values.append(value)
    return values


def _validate_contract(value: object) -> None:
    schema = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    error = next(
        iter(
            sorted(
                Draft202012Validator(schema).iter_errors(value),
                key=lambda item: tuple(str(part) for part in item.absolute_path),
            )
        ),
        None,
    )
    if error is None:
        return
    location = "/" + "/".join(str(part) for part in error.absolute_path)
    raise ValueError(
        f"selection collections violate the checked contract at "
        f"{location or '/'}: {_schema_error_message(error)}"
    )


def _schema_error_message(error: object) -> str:
    validator = getattr(error, "validator", None)
    if validator in {"required", "additionalProperties"}:
        return str(getattr(error, "message"))
    if validator == "type":
        expected = getattr(error, "validator_value", "declared")
        return f"expected JSON type {expected!r}"
    return f"failed JSON Schema constraint {validator!r}"


def _reject_full_text(value: object, path: Path, line_number: int) -> None:
    if isinstance(value, dict):
        keys = {str(key).lower() for key in value}
        prohibited = keys & _PROHIBITED_KEYS
        if prohibited:
            raise ValueError(
                f"{path}:{line_number}: prohibited full-text field {sorted(prohibited)}"
            )
        for child in value.values():
            _reject_full_text(child, path, line_number)
    elif isinstance(value, list):
        for child in value:
            _reject_full_text(child, path, line_number)


def _write_jsonl(path: Path, values: list[dict[str, object]]) -> None:
    lines = [
        json.dumps(value, ensure_ascii=False, sort_keys=True)
        for value in values
    ]
    _atomic_write(path, "\n".join(lines) + ("\n" if lines else ""))


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def _digest(value: bytes) -> str:
    return f"sha256:{sha256(value).hexdigest()}"


if __name__ == "__main__":
    raise SystemExit(main())
