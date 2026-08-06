#!/usr/bin/env python3
"""Validate source-result.v2 files and build the Agent search artifacts."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

from jsonschema import Draft202012Validator


_SCHEMA_PATH = (
    Path(__file__).resolve().parents[1]
    / "references/source-result.v2.schema.json"
)

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sources-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()

    source_paths = sorted(args.sources_dir.glob("*.json"))
    if not source_paths:
        raise SystemExit("no source-result files were found")
    runs: list[dict[str, object]] = []
    records: list[dict[str, object]] = []
    observations: list[dict[str, object]] = []
    for path in source_paths:
        value = json.loads(path.read_text(encoding="utf-8"))
        _validate_source_result(value, path)
        runs.append(value["search_run"])
        records.extend(value["records"])
        observations.append(
            {
                "path": path.name,
                "sha256": _digest(path.read_bytes()),
                "tool_observation": value.get("tool_observation", {}),
            }
        )

    _validate_identity(runs, records)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    runs_path = args.output_dir / "search-runs.jsonl"
    records_path = args.output_dir / "records.jsonl"
    _write_jsonl(runs_path, runs)
    _write_jsonl(records_path, records)
    summary = {
        "run_count": len(runs),
        "source_count": len({str(run["source_name"]) for run in runs}),
        "record_count": len(records),
    }
    manifest = {
        "schema_version": "agent-search-output.v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "summary": summary,
        "collections": {
            "search_runs": {
                "path": "search-runs.jsonl",
                "sha256": _digest(runs_path.read_bytes()),
                "record_count": len(runs),
            },
            "records": {
                "path": "records.jsonl",
                "sha256": _digest(records_path.read_bytes()),
                "record_count": len(records),
            },
        },
        "source_observations": observations,
    }
    _write_json(args.output_dir / "manifest.json", manifest)
    return 0


def _validate_source_result(value: object, path: Path) -> None:
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
    if error is not None:
        location = "/" + "/".join(str(part) for part in error.absolute_path)
        raise ValueError(
            f"{path}: source result violates the checked contract at "
            f"{location or '/'}: {_schema_error_message(error)}"
        )
    assert isinstance(value, dict)
    run = value.get("search_run")
    records = value.get("records")
    assert isinstance(run, dict) and isinstance(records, list)
    if run["status"] in {"failed", "unavailable"} and records:
        raise ValueError(f"{path}: failed sources must not contain Records")


def _schema_error_message(error: object) -> str:
    validator = getattr(error, "validator", None)
    if validator in {"required", "additionalProperties"}:
        return str(getattr(error, "message"))
    if validator == "type":
        expected = getattr(error, "validator_value", "declared")
        return f"expected JSON type {expected!r}"
    return f"failed JSON Schema constraint {validator!r}"


def _validate_identity(
    runs: list[dict[str, object]],
    records: list[dict[str, object]],
) -> None:
    run_ids = [str(run["search_run_id"]) for run in runs]
    if len(run_ids) != len(set(run_ids)):
        raise ValueError("search run IDs must be unique")
    record_ids = [str(record.get("record_id") or "") for record in records]
    if not all(record_ids) or len(record_ids) != len(set(record_ids)):
        raise ValueError("record IDs must be present and unique")
    runs_by_id = {str(run["search_run_id"]): run for run in runs}
    known_runs = set(runs_by_id)
    for record in records:
        for field in (
            "source_name",
            "platform",
            "source_record_id",
        ):
            if not isinstance(record.get(field), str) or not str(record[field]).strip():
                raise ValueError(f"every Record requires {field}")
        linked = record.get("search_run_ids")
        if not isinstance(linked, list) or not linked:
            raise ValueError("every Record must reference a Search Run")
        if not set(map(str, linked)) <= known_runs:
            raise ValueError("a Record references an unknown Search Run")
        if any(
            record["source_name"] != runs_by_id[str(run_id)]["source_name"]
            or record["platform"] != runs_by_id[str(run_id)]["platform"]
            for run_id in linked
        ):
            raise ValueError("a Record source and platform must match its Search Runs")
        provenance = record.get("provenance")
        if not isinstance(provenance, list) or not provenance:
            raise ValueError("every Record requires provenance")


def _write_jsonl(path: Path, values: list[dict[str, object]]) -> None:
    lines = [json.dumps(value, ensure_ascii=False, sort_keys=True) for value in values]
    _atomic_write(path, "\n".join(lines) + ("\n" if lines else ""))


def _write_json(path: Path, value: object) -> None:
    _atomic_write(
        path,
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )


def _atomic_write(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    temporary.replace(path)


def _digest(value: bytes) -> str:
    return f"sha256:{sha256(value).hexdigest()}"


if __name__ == "__main__":
    raise SystemExit(main())
