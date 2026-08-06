#!/usr/bin/env python3
"""Validate a completed Synthesis ledger and write its public projections."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import tempfile

from jsonschema import Draft202012Validator

from synthesis_contract import (
    project_synthesis_csv,
    validate_synthesis_ledger,
)


ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT / "references/evidence-synthesis-document.v3.schema.json"


def finalize(
    ledger_path: Path,
    binding_path: Path,
    output_directory: Path,
) -> tuple[Path, ...]:
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    if not isinstance(ledger, dict):
        raise ValueError("ledger must be a JSON object")
    binding = json.loads(binding_path.read_text(encoding="utf-8"))
    if not isinstance(binding, dict):
        raise ValueError("binding must be a JSON object")
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
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
        expected_binding=binding,
        require_completed=True,
    )
    output_directory.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for name, content in project_synthesis_csv(ledger).items():
        destination = output_directory / name
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=output_directory,
            prefix=f".{name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            stream.write(content)
            temporary = Path(stream.name)
        temporary.replace(destination)
        paths.append(destination)
    return tuple(paths)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--binding", type=Path, required=True)
    parser.add_argument("--output-directory", type=Path, required=True)
    arguments = parser.parse_args()
    finalize(arguments.ledger, arguments.binding, arguments.output_directory)


if __name__ == "__main__":
    main()
