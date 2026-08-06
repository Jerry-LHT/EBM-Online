"""Export or verify Skill-visible snapshots of Backend artifact contracts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .artifact_contract import VersionedArtifactContract
from .artifact_schemas import (
    RISK_OF_BIAS_DOCUMENT_V4,
    SELECTION_COLLECTIONS_V2,
    SOURCE_RESULT_V2,
    STUDY_DATA_COLLECTION_DOCUMENT_V3,
    EVIDENCE_SYNTHESIS_DOCUMENT_V3,
)
from .tasks.grade_summary_of_findings import grade_output_schema
from .tasks.systematic_review_reporting import systematic_review_output_schema
from .schema import strict_task_output_schema


_SKILLS_ROOT = Path(__file__).with_name("skills")
_EXPORTS: tuple[tuple[VersionedArtifactContract[Any], Path], ...] = (
    (
        SOURCE_RESULT_V2,
        _SKILLS_ROOT
        / "evidence_search/evidence-search/references/source-result.v2.schema.json",
    ),
    (
        SELECTION_COLLECTIONS_V2,
        _SKILLS_ROOT / "study_selection/select-studies/references/"
        "selection-collections.v2.schema.json",
    ),
    (
        STUDY_DATA_COLLECTION_DOCUMENT_V3,
        _SKILLS_ROOT / "study_data_collection/collect-study-data/references/"
        "study-data-collection-document.v3.schema.json",
    ),
    (
        RISK_OF_BIAS_DOCUMENT_V4,
        _SKILLS_ROOT / "risk_of_bias/risk-of-bias/references/"
        "risk-of-bias-document.v4.schema.json",
    ),
    (
        EVIDENCE_SYNTHESIS_DOCUMENT_V3,
        _SKILLS_ROOT / "evidence_synthesis/synthesize-evidence/references/"
        "evidence-synthesis-document.v3.schema.json",
    ),
)

_GRADE_OUTPUT_SCHEMA = (
    _SKILLS_ROOT
    / "grade_summary_of_findings/grade-evidence-and-build-sof/references"
    / "grade-agent-output.v4.schema.json"
)
_SYSTEMATIC_REVIEW_OUTPUT_SCHEMA = (
    _SKILLS_ROOT
    / "systematic_review_reporting/compose-systematic-review/references"
    / "systematic-review-agent-output.v3.schema.json"
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="fail when a checked-in schema differs from its Pydantic contract",
    )
    args = parser.parse_args()

    stale: list[str] = []
    for contract, path in _EXPORTS:
        expected = contract.canonical_schema_json()
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != expected:
                stale.append(str(path))
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(expected, encoding="utf-8")
    grade_schema = strict_task_output_schema(grade_output_schema())
    grade_text = (
        json.dumps(grade_schema, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    )
    if args.check:
        if (
            not _GRADE_OUTPUT_SCHEMA.is_file()
            or _GRADE_OUTPUT_SCHEMA.read_text(encoding="utf-8") != grade_text
        ):
            stale.append(str(_GRADE_OUTPUT_SCHEMA))
    else:
        _GRADE_OUTPUT_SCHEMA.parent.mkdir(parents=True, exist_ok=True)
        _GRADE_OUTPUT_SCHEMA.write_text(grade_text, encoding="utf-8")
    review_schema = strict_task_output_schema(systematic_review_output_schema())
    review_text = (
        json.dumps(review_schema, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    )
    if args.check:
        if (
            not _SYSTEMATIC_REVIEW_OUTPUT_SCHEMA.is_file()
            or _SYSTEMATIC_REVIEW_OUTPUT_SCHEMA.read_text(encoding="utf-8")
            != review_text
        ):
            stale.append(str(_SYSTEMATIC_REVIEW_OUTPUT_SCHEMA))
    else:
        _SYSTEMATIC_REVIEW_OUTPUT_SCHEMA.parent.mkdir(parents=True, exist_ok=True)
        _SYSTEMATIC_REVIEW_OUTPUT_SCHEMA.write_text(review_text, encoding="utf-8")
    if stale:
        raise SystemExit("stale artifact schema snapshots: " + ", ".join(stale))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
