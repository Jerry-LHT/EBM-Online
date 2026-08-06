#!/usr/bin/env python3
"""Record one failed or unavailable source without inventing Records."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--query-file", required=True, type=Path)
    parser.add_argument("--narrative-file", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-name", required=True)
    parser.add_argument("--platform", required=True)
    parser.add_argument(
        "--status",
        required=True,
        choices=("failed", "unavailable"),
    )
    parser.add_argument("--reason", required=True)
    parser.add_argument("--locator", default="agent-tool:source-status")
    args = parser.parse_args()

    query = args.query_file.read_text(encoding="utf-8").strip()
    narrative = (
        args.narrative_file.read_text(encoding="utf-8").strip()
        if args.narrative_file
        else f"Source was recorded as {args.status}: {args.reason.strip()}"
    )
    if not query:
        raise SystemExit("query file is empty")
    if not narrative:
        raise SystemExit("narrative file is empty")
    reason = args.reason.strip()
    if not reason:
        raise SystemExit("reason must not be empty")
    value = {
        "schema_version": "source-result.v2",
        "search_run": {
            "search_run_id": args.run_id,
            "source_name": args.source_name,
            "platform": args.platform,
            "query": query,
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "status": args.status,
            "result_count": 0,
            "retrieved_count": 0,
            "status_reason": reason,
            "search_narrative": narrative,
            "provenance": [
                {
                    "source_id": _source_id(args.source_name),
                    "source_type": f"search_source:{args.platform}",
                    "locator": args.locator,
                    "excerpt": reason,
                }
            ],
        },
        "records": [],
        "tool_observation": {
            "tool": "source-status",
            "reason": reason,
        },
    }
    _write_json(args.output, value)
    return 0


def _source_id(value: str) -> str:
    normalized = "".join(
        character.lower() if character.isalnum() else "-"
        for character in value
    )
    return "-".join(part for part in normalized.split("-") if part)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


if __name__ == "__main__":
    raise SystemExit(main())
