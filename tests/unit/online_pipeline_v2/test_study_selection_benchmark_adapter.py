from __future__ import annotations

import csv
from dataclasses import asdict
import json
from pathlib import Path

from ebm_backend.online_pipeline_v2.domain.selection import SelectionPackageRef
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.contracts import (
    TaskOutputError,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.packages import (
    FileSelectionPackageStore,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime.errors import (
    AgentOutputError,
)

from benchmark.online_pipeline_v2.StudySelection.adapter.materialize import (
    build_candidate_search_artifact,
    build_study_selection_protocol,
)
from benchmark.online_pipeline_v2.StudySelection.adapter.projection import (
    load_selection_package,
    project_prediction_rows,
    write_prediction_csvs,
)
from benchmark.online_pipeline_v2.StudySelection.adapter.run_manual import (
    _failure_diagnostics,
)


ROOT = Path(__file__).resolve().parents[3]


def test_public_review_materializes_selection_protocol_without_gold() -> None:
    path = (
        ROOT
        / "benchmark/online_pipeline_v2/StudySelection/data/candidates/input"
        / "CD003357/review.json"
    )

    protocol = build_study_selection_protocol(
        path,
        version="selection-protocol-1",
    )
    serialized = json.dumps(asdict(protocol))

    assert protocol.review_question == (
        "In vitro fertilisation for unexplained subfertility"
    )
    assert protocol.study_designs[0].heading == "Types of studies"
    assert protocol.setting_restrictions == ()
    assert protocol.language_restrictions == ()
    assert protocol.publication_status_restrictions == ()
    assert protocol.time_restrictions == ()
    assert "study_000" not in serialized
    assert "primary_exclusion_reason" not in serialized


def test_selection_protocol_allows_absent_optional_restrictions(
    tmp_path: Path,
) -> None:
    path = tmp_path / "review.json"
    path.write_text(
        json.dumps(
            {
                "review_question": "Question",
                "protocol": {
                    "objectives": {
                        "heading": "Objectives",
                        "text": "Assess.",
                    },
                    "eligibility_criteria": {
                        "study_designs": [
                            {"heading": "Studies", "text": "RCTs"}
                        ],
                        "participants": [
                            {"heading": "Participants", "text": "Adults"}
                        ],
                        "interventions_and_comparators": [
                            {"heading": "Interventions", "text": "A versus B"}
                        ],
                        "outcomes": [
                            {"heading": "Outcomes", "text": "Mortality"}
                        ],
                    },
                },
            }
        ),
        encoding="utf-8",
    )

    protocol = build_study_selection_protocol(path, version="v1")

    assert protocol.setting_restrictions == ()
    assert protocol.language_restrictions == ()
    assert protocol.publication_status_restrictions == ()
    assert protocol.time_restrictions == ()


def test_candidate_records_materialize_without_hidden_labels() -> None:
    path = (
        ROOT
        / "benchmark/online_pipeline_v2/StudySelection/data/candidates/input"
        / "CD000143/records.csv"
    )
    artifact = build_candidate_search_artifact(
        path,
        executed_at="2026-07-28T00:00:00+00:00",
    )

    assert artifact.summary.record_count == 19
    assert artifact.records[0].record_id == "record_000001"
    assert artifact.records[0].abstract is None
    serialized = json.dumps(asdict(artifact.records[0]))
    assert "study_id" not in serialized
    assert "included" not in serialized
    assert "excluded" not in serialized


def test_projection_reads_validated_selection_package(tmp_path: Path) -> None:
    package_root = tmp_path / "selection"
    store = FileSelectionPackageStore(package_root)
    package_id = "pilot:study_selection:draft-1:fixture"
    root = package_root / "pilot" / "draft-1" / package_id
    root.mkdir(parents=True)
    collections = {
        "record_screening": [],
        "reports": [],
        "report_discoveries": [],
        "record_report_links": [
            {"record_id": "record_1", "report_id": "report_1"}
        ],
        "report_evidence": [],
        "studies": [],
        "study_report_links": [
            {"study_id": "study_1", "report_id": "report_1"}
        ],
        "study_decisions": [
            {"study_id": "study_1", "classification": "included"}
        ],
        "conflicts": [],
    }
    manifest_collections = {}
    import hashlib

    for name, values in collections.items():
        filename = name.replace("_", "-") + ".jsonl"
        path = root / filename
        path.write_text(
            "".join(json.dumps(value) + "\n" for value in values),
            encoding="utf-8",
        )
        manifest_collections[name] = {
            "path": filename,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "record_count": len(values),
        }
    manifest = {
        "schema_version": "selection-package.v4",
        "package_id": package_id,
        "review_id": "pilot",
        "protocol_version": "draft-1",
        "collections": manifest_collections,
        "agent_outputs": {
            "primary-agent": {
                "files": [
                    {
                        "path": "review.json",
                        "sha256": "",
                    }
                ]
            }
        },
    }
    review_path = root / "review.json"
    review_path.write_text("{}\n", encoding="utf-8")
    manifest["agent_outputs"]["primary-agent"]["files"][0][
        "sha256"
    ] = hashlib.sha256(review_path.read_bytes()).hexdigest()
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )
    package_ref = SelectionPackageRef(
        package_id=package_id,
        review_id="pilot",
        protocol_version="draft-1",
        schema_version="selection-package.v4",
        content_digest=(
            "sha256:" + hashlib.sha256(manifest_path.read_bytes()).hexdigest()
        ),
    )

    package = load_selection_package(store, package_ref)
    links, studies = project_prediction_rows(package)

    assert links == (
        {
            "record_id": "record_1",
            "report_id": "report_1",
            "study_id": "study_1",
        },
    )
    assert studies == (
        {"study_id": "study_1", "prediction": "included"},
    )

    links_path, studies_path = write_prediction_csvs(
        tmp_path / "predictions",
        instance_id="case",
        link_rows=links,
        study_rows=studies,
    )
    with links_path.open(newline="", encoding="utf-8") as handle:
        assert list(csv.DictReader(handle)) == list(links)
    with studies_path.open(newline="", encoding="utf-8") as handle:
        assert list(csv.DictReader(handle)) == list(studies)


def test_agent_artifact_contract_failure_has_stable_diagnostic() -> None:
    diagnostic = _failure_diagnostics(
        AgentOutputError("natural-language detail is not persisted")
    )

    assert diagnostic == {
        "error_type": "AgentOutputError",
        "error_code": "agent_artifact_contract_failed",
    }

    structured = _failure_diagnostics(
        TaskOutputError(
            "selection rows violate schema",
            code="artifact_schema_invalid",
            stage="artifact_schema",
            artifact="selection rows",
            location="/reports/0/title",
            contract_version="agent-selection-collections.v2",
        )
    )
    assert structured == {
        "error_type": "TaskOutputError",
        "error_code": "artifact_schema_invalid",
        "message": "selection rows violate schema",
        "stage": "artifact_schema",
        "artifact": "selection rows",
        "location": "/reports/0/title",
        "contract_version": "agent-selection-collections.v2",
    }
