#!/usr/bin/env python3
"""Create and structurally validate the Study Data Collection document."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "references/study-data-collection-document.v3.schema.json"


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
        json.dump(
            value,
            stream,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        stream.write("\n")
        temporary = Path(stream.name)
    temporary.replace(path)


def validate(document: dict, binding: dict, completed: bool) -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda item: tuple(str(part) for part in item.absolute_path),
    )
    if errors:
        location = "/" + "/".join(str(part) for part in errors[0].absolute_path)
        raise ValueError(
            "Study Data Collection document violates v3 schema at "
            f"{location}: {errors[0].message}"
        )
    if document["binding"] != binding:
        raise ValueError("Study Data Collection binding does not match work")
    if completed and document["status"] != "completed":
        raise ValueError("Study Data Collection document is not completed")


def initialize(binding_path: Path, output: Path) -> None:
    _write(
        output,
        {
            "schema_version": "study-data-collection-document.v3",
            "binding": _read(binding_path),
            "status": "incomplete",
            "review_process": {
                "human_independent_extraction_satisfied": False,
                "methodology_authorities": [],
                "method_decisions": [],
            },
            "studies": [],
            "issues": [],
        },
    )


def upsert(document_path: Path, study_path: Path, output: Path) -> None:
    document = _read(document_path)
    study = _read(study_path)
    study_id = str(study.get("study_id", "")).strip()
    if not study_id:
        raise ValueError("Study update requires study_id")
    document["studies"] = [
        study if item.get("study_id") == study_id else item
        for item in document.get("studies", [])
    ]
    if not any(item.get("study_id") == study_id for item in document["studies"]):
        document["studies"].append(study)
    _write(output, document)


def main() -> None:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init")
    init.add_argument("--binding", type=Path, required=True)
    init.add_argument("--output", type=Path, required=True)
    update = commands.add_parser("upsert-study")
    update.add_argument("--document", type=Path, required=True)
    update.add_argument("--study", type=Path, required=True)
    update.add_argument("--output", type=Path, required=True)
    check = commands.add_parser("validate")
    check.add_argument("--document", type=Path, required=True)
    check.add_argument("--binding", type=Path, required=True)
    check.add_argument("--completed", action="store_true")
    canonical = commands.add_parser("write-canonical")
    canonical.add_argument("--document", type=Path, required=True)
    canonical.add_argument("--binding", type=Path, required=True)
    canonical.add_argument("--completed", action="store_true")
    canonical.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "init":
        initialize(args.binding, args.output)
    elif args.command == "upsert-study":
        upsert(args.document, args.study, args.output)
    else:
        document = _read(args.document)
        validate(document, _read(args.binding), args.completed)
        if args.command == "write-canonical":
            _write(args.output, document)


if __name__ == "__main__":
    main()
