from __future__ import annotations

import csv
from hashlib import sha256
import json

import pytest

from benchmark.online_pipeline_v2.StudyDataCollection.CharacteristicsOfStudies.adapter.markdown import (
    render_characteristics_markdown,
)
from benchmark.online_pipeline_v2.StudyDataCollection.CharacteristicsOfStudies.adapter.materialize import (
    build_selection_artifact,
    load_characteristics_protocol_context,
)
from benchmark.online_pipeline_v2.StudyDataCollection.CharacteristicsOfStudies.adapter.projection import (
    project_prediction,
)
from benchmark.online_pipeline_v2.StudyDataCollection.CharacteristicsOfStudies.adapter.protocol_compat import (
    prepare_characteristics_protocol_context,
)
from benchmark.online_pipeline_v2.StudyDataCollection.CharacteristicsOfStudies.adapter.selection_compat import (
    prepare_selection_package,
)
from ebm_backend.online_pipeline_v2.domain.selection import SelectionPackageRef
from ebm_backend.online_pipeline_v2.infrastructure.persistence.packages import (
    FileSelectionPackageStore,
)


def test_materializer_creates_one_included_study_with_public_report_metadata(
    tmp_path,
) -> None:
    studies_path = tmp_path / "studies.csv"
    reports_path = tmp_path / "reports.csv"
    _write_csv(
        studies_path,
        ("study_id", "study_label"),
        ({"study_id": "study-1", "study_label": "Example 2026"},),
    )
    _write_csv(
        reports_path,
        (
            "study_id",
            "report_id",
            "ris_type",
            "title",
            "citation_text",
            "identifiers",
        ),
        (
            {
                "study_id": "study-1",
                "report_id": "report-1",
                "ris_type": "JOUR",
                "title": "Example report",
                "citation_text": "Example citation",
                "identifiers": json.dumps(
                    [
                        {"scheme": "DOI", "value": "10.1000/example"},
                        {"scheme": "PubMed", "value": "123"},
                    ]
                ),
            },
        ),
    )
    store = FileSelectionPackageStore(tmp_path / "packages")

    artifact = build_selection_artifact(
        studies_csv=studies_path,
        reports_csv=reports_path,
        study_id="study-1",
        store=store,
        review_id="review-1",
        protocol_version="protocol-1",
    )
    manifest = store.validate(artifact.package_ref)
    report_path = (
        store.resolve_manifest(artifact.package_ref).parent
        / manifest["collections"]["reports"]["path"]
    )
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert artifact.summary.included_count == 1
    assert artifact.summary.reports_assessed_count == 1
    assert report["external_identifiers"] == [
        "DOI:10.1000/example",
        "PubMed:123",
    ]
    assert report["locators"] == [
        "https://doi.org/10.1000/example",
        "https://pubmed.ncbi.nlm.nih.gov/123/",
    ]


def test_protocol_context_is_projected_directly_from_public_review_input(
    tmp_path,
) -> None:
    review_path = tmp_path / "review.json"
    review_path.write_text(
        json.dumps(
            {
                "review_question": "Does treatment improve survival?",
                "review_pico": {
                    "population": ["Adults"],
                    "intervention": ["Treatment"],
                    "comparison": ["Usual care"],
                    "outcome": ["Survival"],
                },
                "methods": [
                    {
                        "canonical_heading": "study_designs",
                        "heading": "Types of studies",
                        "text": "Types of studies\nRandomized trials.",
                    },
                    {
                        "canonical_heading": "participants",
                        "heading": "Types of participants",
                        "text": "Types of participants\nAdults.",
                    },
                    {
                        "canonical_heading": "interventions",
                        "heading": "Types of interventions",
                        "text": "Types of interventions\nTreatment versus usual care.",
                    },
                    {
                        "canonical_heading": "primary_outcomes",
                        "heading": "Primary outcomes",
                        "text": (
                            "Primary outcomes\nSurvival.\n"
                            "Search methods for identification of studies\n"
                            "Do not expose this search section."
                        ),
                    },
                    {
                        "canonical_heading": "data_collection",
                        "heading": "Data extraction and management",
                        "text": "Data extraction and management\nExtract in duplicate.",
                    },
                    {
                        "canonical_heading": "risk_of_bias",
                        "heading": "Assessment of risk of bias",
                        "text": "Do not expose RoB.",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )

    first = load_characteristics_protocol_context(review_path)
    second = load_characteristics_protocol_context(review_path)

    assert first == second
    assert first.protocol_version.startswith("characteristics-context-")
    assert first.review_pico.comparator == ("Usual care",)
    assert {item.name.value for item in first.method_sections} == {
        "study_designs",
        "participants",
        "interventions",
        "primary_outcomes",
        "data_collection",
    }
    primary = next(
        item
        for item in first.method_sections
        if item.name.value == "primary_outcomes"
    )
    assert "Search methods" not in primary.text


def test_historical_protocol_projects_to_current_characteristics_context() -> None:
    eligibility_section = {
        "description": "Eligible trials.",
        "inclusion_criteria": ["Randomized trials."],
        "exclusion_criteria": ["Observational studies."],
    }
    protocol = {
        "version": "draft-1",
        "review_question": "Does treatment improve survival?",
        "review_pico": {
            "population": ["Adults"],
            "intervention": ["Treatment"],
            "comparator": ["Usual care"],
            "outcomes": ["Survival"],
            "context": [],
        },
        "methodology_basis": [{
            "standard": "cochrane_handbook",
            "title": "Cochrane Handbook",
            "version_or_revision": "6.5",
            "sections": ["Chapter 5"],
            "url": "https://www.cochrane.org/handbook",
            "accessed_on": "2026-07-31",
        }],
        "methods": {
            "eligibility": {
                "types_of_studies": eligibility_section,
                "types_of_participants": eligibility_section,
                "types_of_interventions": eligibility_section,
                "comparators": eligibility_section,
            },
            "outcomes": {"outcomes": [{
                "role": "primary",
                "name": "Survival",
                "definition": "Alive at follow-up.",
                "measurement": "Number alive.",
                "time_points": ["30 days"],
            }]},
            "data_collection": {
                "extraction_process": "Extract using a piloted form.",
                "data_items": ["Study design"],
                "study_report_linkage": "Collate Reports by Study.",
                "missing_information": "Record missing information.",
            },
        },
    }

    context, source_schema = prepare_characteristics_protocol_context(protocol)

    assert source_schema == "legacy-protocol"
    assert context.schema_version == "study-characteristics-protocol-context.v2"
    assert context.protocol_version == "draft-1"
    assert len(context.method_sections) == 5


def test_projection_and_markdown_are_deterministic_and_do_not_score() -> None:
    record = {"study_id": "study-1", "status": "completed", "methods": {}}
    package = {
        "manifest": {
            "package_id": "package-1",
            "schema_version": "study-characteristics-package.v6",
        },
        "collections": {
            "studies": (record,),
            "discovered_reports": (),
            "discovered_report_links": (),
            "report_evidence": (),
            "issues": (),
        },
    }
    prediction = project_prediction(
        package,
        instance_id="case-1",
        study_id="study-1",
    )
    markdown = render_characteristics_markdown(
        instance_id="case-1",
        study_id="study-1",
        response={
            "artifact_id": "artifact-1",
            "status": "completed",
            "data": {"summary": {"included_study_count": 1}},
            "issues": [],
        },
        package=package,
    )

    assert prediction["characteristics"] == record
    assert "Evaluation invoked: `false`" in markdown
    assert '"study_id": "study-1"' in markdown


def test_completed_historical_selection_is_repackaged_without_decision_changes(
    tmp_path,
) -> None:
    artifact, source_store = _selection_fixture(tmp_path)
    source_manifest_path = source_store.resolve_manifest(artifact.package_ref)
    manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "selection-package.v3"
    source_manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    source_ref = SelectionPackageRef(
        package_id=artifact.package_ref.package_id,
        review_id=artifact.package_ref.review_id,
        protocol_version=artifact.package_ref.protocol_version,
        schema_version="selection-package.v3",
        content_digest=f"sha256:{sha256(source_manifest_path.read_bytes()).hexdigest()}",
    )

    prepared = prepare_selection_package(
        selection_run=tmp_path,
        package_ref=source_ref,
        output_root=tmp_path / "adapted",
    )
    migrated_manifest = prepared.store.validate(prepared.package_ref)

    assert prepared.migrated is True
    assert prepared.package_ref.schema_version == "selection-package.v4"
    assert migrated_manifest["collections"]["study_decisions"]["record_count"] == 1


def test_historical_selection_migration_rejects_tampered_collection(tmp_path) -> None:
    artifact, source_store = _selection_fixture(tmp_path)
    source_manifest_path = source_store.resolve_manifest(artifact.package_ref)
    manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    manifest["schema_version"] = "selection-package.v3"
    source_manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    source_ref = SelectionPackageRef(
        package_id=artifact.package_ref.package_id,
        review_id=artifact.package_ref.review_id,
        protocol_version=artifact.package_ref.protocol_version,
        schema_version="selection-package.v3",
        content_digest=f"sha256:{sha256(source_manifest_path.read_bytes()).hexdigest()}",
    )
    studies_path = source_manifest_path.parent / manifest["collections"]["studies"]["path"]
    studies_path.write_text(studies_path.read_text(encoding="utf-8") + "{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="digest mismatch"):
        prepare_selection_package(
            selection_run=tmp_path,
            package_ref=source_ref,
            output_root=tmp_path / "adapted",
        )


def _selection_fixture(tmp_path):
    studies_path = tmp_path / "studies.csv"
    reports_path = tmp_path / "reports.csv"
    _write_csv(
        studies_path,
        ("study_id", "study_label"),
        ({"study_id": "study-1", "study_label": "Example 2026"},),
    )
    _write_csv(
        reports_path,
        ("study_id", "report_id", "ris_type", "title", "citation_text", "identifiers"),
        ({
            "study_id": "study-1",
            "report_id": "report-1",
            "ris_type": "JOUR",
            "title": "Example report",
            "citation_text": "Example citation",
            "identifiers": "[]",
        },),
    )
    store = FileSelectionPackageStore(tmp_path / "backend-packages" / "selection")
    artifact = build_selection_artifact(
        studies_csv=studies_path,
        reports_csv=reports_path,
        study_id="study-1",
        store=store,
        review_id="review-1",
        protocol_version="protocol-1",
    )
    return artifact, store


def _write_csv(path, fieldnames, rows) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
