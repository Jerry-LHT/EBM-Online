#!/usr/bin/env python3
"""Initialize, update, and validate the Evidence Synthesis document."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from jsonschema import Draft202012Validator

from synthesis_contract import validate_synthesis_ledger


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "references/evidence-synthesis-document.v3.schema.json"


def _read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(path)


def initialize(binding_path: Path, output: Path) -> None:
    _write(
        output,
        {
            "schema_version": "evidence-synthesis-document.v3",
            "binding": _read(binding_path),
            "status": "incomplete",
            "review_process": {
                "human_independent_synthesis_satisfied": False,
                "methodology_authorities": [],
                "method_decisions": [],
            },
            "analyses": [],
            "issues": [],
        },
    )


def upsert_analysis(
    ledger_path: Path,
    analysis_path: Path,
    output: Path,
) -> None:
    ledger = _read(ledger_path)
    analysis = _read(analysis_path)
    analysis_id = str(analysis.get("analysis_id", "")).strip()
    if not analysis_id:
        raise ValueError("analysis update requires analysis_id")
    analyses = ledger.get("analyses")
    if not isinstance(analyses, list):
        raise ValueError("ledger analyses must be a list")
    ledger["analyses"] = [
        item
        for item in analyses
        if not (isinstance(item, dict) and item.get("analysis_id") == analysis_id)
    ] + [analysis]
    _write(output, ledger)


def set_status(
    ledger_path: Path,
    binding_path: Path,
    status: str,
    output: Path,
) -> None:
    ledger = _read(ledger_path)
    ledger["status"] = status
    _write(output, ledger)
    validate(output, binding_path, status == "completed")


def validate(
    ledger_path: Path,
    binding_path: Path,
    completed: bool,
) -> None:
    ledger = _read(ledger_path)
    schema = _read(SCHEMA_PATH)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(ledger),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if errors:
        location = "/" + "/".join(str(part) for part in errors[0].absolute_path)
        raise ValueError(
            "Synthesis document violates v2 schema at "
            f"{location}: {errors[0].message}"
        )
    validate_synthesis_ledger(
        ledger,
        expected_binding=_read(binding_path),
        require_completed=completed,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    init = subparsers.add_parser("init")
    init.add_argument("--binding", type=Path, required=True)
    init.add_argument("--output", type=Path, required=True)

    upsert = subparsers.add_parser("upsert-analysis")
    upsert.add_argument("--ledger", type=Path, required=True)
    upsert.add_argument("--analysis", type=Path, required=True)
    upsert.add_argument("--output", type=Path, required=True)

    status = subparsers.add_parser("set-status")
    status.add_argument("--ledger", type=Path, required=True)
    status.add_argument("--binding", type=Path, required=True)
    status.add_argument(
        "--status",
        choices=("incomplete", "blocked", "completed"),
        required=True,
    )
    status.add_argument("--output", type=Path, required=True)

    check = subparsers.add_parser("validate")
    check.add_argument("--ledger", type=Path, required=True)
    check.add_argument("--binding", type=Path, required=True)
    check.add_argument("--completed", action="store_true")

    arguments = parser.parse_args()
    if arguments.command == "init":
        initialize(arguments.binding, arguments.output)
    elif arguments.command == "upsert-analysis":
        upsert_analysis(arguments.ledger, arguments.analysis, arguments.output)
    elif arguments.command == "set-status":
        set_status(
            arguments.ledger,
            arguments.binding,
            arguments.status,
            arguments.output,
        )
    else:
        validate(arguments.ledger, arguments.binding, arguments.completed)


if __name__ == "__main__":
    main()
