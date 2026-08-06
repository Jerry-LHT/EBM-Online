from __future__ import annotations

import csv
from copy import deepcopy
from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path

import pytest

from ebm_backend.online_pipeline_v2.domain.common import (
    Provenance,
    TaskContext,
    TaskWorkStatus,
)
from ebm_backend.online_pipeline_v2.domain.selection import (
    Report,
    SelectionCollections,
    SelectionSummary,
    Study,
    StudyClassification,
    StudyEligibilityDecision,
    StudyReportLink,
    StudySelectionArtifact,
)
from ebm_backend.online_pipeline_v2.domain.study_data_collection import (
    StudyDataCollectionInput,
    study_data_collection_protocol_from_draft,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution import (
    AgentTaskExecutorAdapter,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.tasks.study_data_collection import (
    CollectStudyDataTask,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime import (
    AgentOutputArtifact,
    AgentProvider,
    AgentRunRequest,
    AgentRunResult,
    AgentSkillSnapshot,
    WebAccessAudit,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.formats.study_data_collection import (
    canonical_json_bytes,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.packages import (
    FileSelectionPackageStore,
    SelectionAgentSnapshot,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.work import (
    FileStudyDataCollectionStore,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.formats.study_data_collection import (
    StudyDataCollectionError,
    project_study_data_collection,
    validate_study_data_collection_document,
)


_SKILL = (
    Path(__file__).parents[3]
    / "backend/src/ebm_backend/online_pipeline_v2/infrastructure/agent_execution/"
    "skills/study_data_collection/collect-study-data"
)
_SPEC = importlib.util.spec_from_file_location(
    "study_data_collection_calculator_test",
    _SKILL / "scripts/data_calculator.py",
)
assert _SPEC is not None and _SPEC.loader is not None
_CALCULATOR = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_CALCULATOR)


def _field(value: str = "Reported") -> dict:
    return {
        "status": "reported",
        "value": value,
        "source_texts": [value],
        "provenance": [
            {
                "source_id": "report-1",
                "source_type": "report",
                "locator": "https://example.test/report",
                "excerpt": value,
            }
        ],
        "note": None,
    }


def _binding() -> dict[str, str]:
    return {
        "review_id": "review-1",
        "protocol_version": "protocol-1",
        "protocol_digest": "sha256:protocol",
        "selection_package_id": "selection-1",
        "selection_package_digest": "sha256:selection",
    }


def _document() -> dict:
    calculation = _CALCULATOR.calculate(
        {
            "expression": "n - successes",
            "inputs": {"n": "25", "successes": "21"},
            "precision": 34,
        }
    )
    methods = {
        name: _field(value)
        for name, value in {
            "design": "Randomized parallel trial",
            "setting": "Neonatal unit",
            "centres": "One centre",
            "recruitment": "Eligible preterm infants",
            "study_dates": "Not reported",
            "follow_up": "Seven days",
            "allocation_or_exposure": "Random allocation",
            "unit_of_analysis": "Infant",
            "analysis_methods": "Arm-level comparison",
        }.items()
    }
    population = {
        name: _field(value)
        for name, value in {
            "eligibility_criteria": "Preterm infants ready for extubation",
            "diagnostic_criteria": "Respiratory distress syndrome",
            "recruitment_setting": "Neonatal intensive care",
            "regions": "United Kingdom",
            "sample_size": "50 randomized infants",
            "baseline_characteristics": "Groups were similar at baseline",
        }.items()
    }
    arm = {
        "arm_id": "arm-ncpap",
        "role": "intervention",
        "label": _field("NCPAP"),
        "description": _field("Nasal continuous positive airway pressure"),
        "dose_or_intensity": _field("Protocol-defined pressure"),
        "route_or_mode": _field("Nasal"),
        "frequency": _field("Continuous"),
        "duration": _field("Post-extubation"),
        "cointerventions": _field("Routine care"),
        "fidelity_or_adherence": _field("Not reported"),
    }
    outcome = {
        "outcome_id": "outcome-reventilation",
        "assessed": _field("Assessed"),
        "definition": _field("Reventilation after extubation"),
        "measurement": _field("Need for reventilation"),
        "metric": _field("Presence of event"),
        "aggregation": _field("Number of infants"),
        "time_points": _field("Seven days"),
    }
    observations = [
        {
            "observation_id": "obs-n",
            "report_id": "report-1",
            "target_id": "target-1",
            "source_locator": "https://example.test/report",
            "source_location": "Results",
            "evidence_description": "NCPAP arm denominator",
            "reported_name": "NCPAP infants",
            "reported_value": {"kind": "integer", "value": 25},
            "reported_unit": "infants",
            "uncertainty": None,
        },
        {
            "observation_id": "obs-success",
            "report_id": "report-1",
            "target_id": "target-1",
            "source_locator": "https://example.test/report",
            "source_location": "Abstract results",
            "evidence_description": "Successful extubation count",
            "reported_name": "Successfully extubated",
            "reported_value": {"kind": "integer", "value": 21},
            "reported_unit": "infants",
            "uncertainty": None,
        },
    ]
    return {
        "schema_version": "study-data-collection-document.v3",
        "binding": _binding(),
        "status": "completed",
        "review_process": {
            "human_independent_extraction_satisfied": False,
            "methodology_authorities": [
                {
                    "authority_id": "cochrane-5",
                    "standard": "Cochrane Handbook",
                    "title": "Chapter 5: Collecting data",
                    "version_or_date": "version 6.5, 2024; chapter updated 2019",
                    "locator": "https://www.cochrane.org/handbook/current/chapter-05",
                    "scope": ["Study data collection"],
                    "applied_principles": ["Preserve source data before conversion"],
                }
            ],
            "method_decisions": [],
        },
        "studies": [
            {
                "study_id": "study-1",
                "display_name": "Example 1995",
                "report_coverage": [
                    {
                        "report_id": "report-1",
                        "status": "inspected",
                        "attempts": [
                            {
                                "locator": "https://example.test/report",
                                "evidence_format": "html",
                                "accessed": True,
                                "content_scope": "complete_report",
                                "observed_at": None,
                                "summary": "Read Methods, Results, and tables.",
                            }
                        ],
                        "reason": None,
                    }
                ],
                "characteristics": {
                    "status": "completed",
                    "methods": methods,
                    "population": population,
                    "funding": _field("Not reported"),
                    "conflicts_of_interest": _field("Not reported"),
                    "notes": _field("No additional notes"),
                    "additional_characteristics": [],
                },
                "arms": [arm],
                "outcomes": [outcome],
                "targets": [
                    {
                        "target_id": "target-1",
                        "outcome_id": "outcome-reventilation",
                        "outcome_name": "Reventilation",
                        "revman_outcome_name": "Reventilation — seven days",
                        "timepoint": "seven days",
                        "population": "preterm infants",
                        "comparison": "NCPAP versus control",
                        "analysis_population": "randomized",
                        "unit_of_analysis": "infant",
                        "protocol_references": ["Primary outcome"],
                        "report_ids": ["report-1"],
                    }
                ],
                "source_observations": observations,
                "results": [
                    {
                        "result_id": "result-1",
                        "target_id": "target-1",
                        "collection_assessment": {
                            "status": "reported with arm-level counts",
                            "rationale": "The Report gives randomized group denominators and successful extubations.",
                            "report_ids": ["report-1"],
                            "limitations": [],
                        },
                        "source_observation_ids": ["obs-n", "obs-success"],
                        "analysis_representations": [
                            {
                                "representation_id": "revman-result-1",
                                "kind": "revman",
                                "result": {
                                    "arm-level-result": {
                                        "dichotomous-data-rows": [
                                            {
                                                "arm_id": "arm-ncpap",
                                                "cases": {
                                                    "value_id": "value-events",
                                                    "value": 4,
                                                    "origin": {
                                                        "kind": "calculated",
                                                        "calculation_id": "calc-events",
                                                        "output_name": "value",
                                                    },
                                                },
                                                "sample-size": {
                                                    "value_id": "value-n",
                                                    "value": 25,
                                                    "origin": {
                                                        "kind": "observed",
                                                        "observation_id": "obs-n",
                                                    },
                                                },
                                            }
                                        ],
                                        "continuous-data-rows": None,
                                        "footnote": "Calculated from reported success count.",
                                    },
                                    "contrast-level-results": None,
                                },
                                "notes": [],
                            }
                        ],
                        "calculation_ids": ["calc-events"],
                        "conflict_ids": [],
                        "notes": [],
                    }
                ],
                "calculations": [
                    {
                        "derivation_id": "calc-events",
                        "tool": "data-calculator",
                        "expression": calculation["expression"],
                        "inputs": calculation["inputs"],
                        "input_origins": {
                            "n": {
                                "kind": "observed",
                                "observation_id": "obs-n",
                            },
                            "successes": {
                                "kind": "observed",
                                "observation_id": "obs-success",
                            },
                        },
                        "precision": calculation["precision"],
                        "outputs": calculation["outputs"],
                        "input_digest": calculation["input_digest"],
                        "output_digest": calculation["output_digest"],
                        "rationale": "The Protocol outcome is reventilation, while the Report gives successful extubation.",
                    }
                ],
                "conflicts": [],
                "issues": [],
                "completion": {
                    "characteristics": "completed",
                    "results": "completed",
                    "completed": True,
                },
            }
        ],
        "issues": [],
    }


def test_generic_calculator_preserves_decimal_and_supports_agent_formula() -> None:
    result = _CALCULATOR.calculate(
        {
            "expression": "sd / sqrt(n)",
            "inputs": {"sd": "1.50", "n": "25"},
            "precision": 34,
        }
    )

    assert result["inputs"] == {"sd": "1.5", "n": "25"}
    assert result["outputs"] == {"value": 0.3, "exact": "0.3"}


def test_unified_document_replays_calculation_and_projects_results() -> None:
    document = _document()
    validate_study_data_collection_document(
        document,
        expected_binding=_binding(),
        require_completed=True,
        calculate=_CALCULATOR.calculate,
    )

    files, summary = project_study_data_collection(document)
    rows = list(
        csv.DictReader(
            io.StringIO(files["review-1-study-results.csv"].decode("utf-8"))
        )
    )
    assert rows[0]["Cases"] == "4"
    assert rows[0]["Sample size"] == "25"
    assert summary["analysis_representation_count"] == 1
    assert b'"study_id":"study-1"' in files[
        "review-1-study-characteristics.jsonl"
    ]


def test_long_source_excerpt_is_preserved_as_professional_evidence() -> None:
    document = _document()
    long_eligibility_criteria = "Eligibility criterion from source. " * 300
    field = document["studies"][0]["characteristics"]["population"][
        "eligibility_criteria"
    ]
    field["value"] = long_eligibility_criteria
    field["source_texts"] = [long_eligibility_criteria]
    field["provenance"][0]["excerpt"] = long_eligibility_criteria

    validated = validate_study_data_collection_document(
        document,
        expected_binding=_binding(),
        require_completed=True,
        calculate=_CALCULATOR.calculate,
    )

    assert (
        validated["studies"][0]["characteristics"]["population"]
        ["eligibility_criteria"]["provenance"][0]["excerpt"]
        == long_eligibility_criteria
    )


def test_equivalent_calculation_precision_is_accepted_and_canonicalized() -> None:
    document = _document()
    calculation = document["studies"][0]["calculations"][0]
    calculation["outputs"] = {
        "value": 4.0000000000001,
        "exact": "4.0000000000001",
    }
    calculation["output_digest"] = "sha256:agent-serialized-output"

    validated = validate_study_data_collection_document(
        document,
        expected_binding=_binding(),
        require_completed=True,
        calculate=_CALCULATOR.calculate,
    )

    assert validated["studies"][0]["calculations"][0]["outputs"] == {
        "value": 4,
        "exact": "4",
    }
    assert any(
        issue["code"] == "calculation_trace_normalized"
        for issue in validated["issues"]
    )


def test_material_calculation_mismatch_warns_and_uses_calculator_output() -> None:
    document = _document()
    calculation = document["studies"][0]["calculations"][0]
    calculation["outputs"] = {"value": 40, "exact": "40"}
    calculation["output_digest"] = "sha256:incorrect-output"
    cases = document["studies"][0]["results"][0]["analysis_representations"][0][
        "result"
    ]["arm-level-result"]["dichotomous-data-rows"][0]["cases"]
    cases["value"] = 40

    validated = validate_study_data_collection_document(
        document,
        expected_binding=_binding(),
        require_completed=True,
        calculate=_CALCULATOR.calculate,
    )

    assert validated["studies"][0]["calculations"][0]["outputs"]["value"] == 4
    validated_cases = validated["studies"][0]["results"][0][
        "analysis_representations"
    ][0]["result"]["arm-level-result"]["dichotomous-data-rows"][0]["cases"]
    assert validated_cases["value"] == 4
    assert {
        issue["code"] for issue in validated["issues"]
    } >= {"calculation_trace_normalized", "calculated_value_normalized"}


def test_completed_document_accepts_methodology_llm_fallback() -> None:
    document = _document()
    document["review_process"] = {
        "human_independent_extraction_satisfied": False,
        "methodology_authorities": [],
        "method_decisions": [],
        "methodology_basis_status": "llm_fallback",
        "fallback_model": "openai/example-model",
        "fallback_note": "Official methodology could not be retrieved during this run.",
    }

    validated = validate_study_data_collection_document(
        document,
        expected_binding=_binding(),
        require_completed=True,
        calculate=_CALCULATOR.calculate,
    )

    assert validated["status"] == "completed"


def test_unused_calculation_is_a_warning_not_a_task_failure() -> None:
    document = _document()
    unused = deepcopy(document["studies"][0]["calculations"][0])
    unused["derivation_id"] = "calc-unused"
    document["studies"][0]["calculations"].append(unused)

    validated = validate_study_data_collection_document(
        document,
        expected_binding=_binding(),
        require_completed=True,
        calculate=_CALCULATOR.calculate,
    )

    assert any(issue["code"] == "unused_calculation" for issue in validated["issues"])


def test_calculation_input_must_match_source_observation() -> None:
    document = _document()
    document["studies"][0]["calculations"][0]["inputs"]["successes"] = "20"

    with pytest.raises(
        StudyDataCollectionError,
        match="does not match its declared source",
    ):
        validate_study_data_collection_document(
            document,
            expected_binding=_binding(),
            require_completed=True,
            calculate=_CALCULATOR.calculate,
        )


def test_decimal_source_value_preserves_reported_lexeme() -> None:
    document = _document()
    document["studies"][0]["source_observations"].append(
        {
            "observation_id": "obs-decimal",
            "report_id": "report-1",
            "target_id": None,
            "source_locator": "https://example.test/report",
            "source_location": "Table 1",
            "evidence_description": "Reported baseline measure",
            "reported_name": "Baseline ratio",
            "reported_value": {"kind": "decimal", "value": "0.10"},
            "reported_unit": None,
            "uncertainty": None,
        }
    )

    validate_study_data_collection_document(
        document,
        expected_binding=_binding(),
        require_completed=True,
        calculate=_CALCULATOR.calculate,
    )
    assert document["studies"][0]["source_observations"][-1]["reported_value"][
        "value"
    ] == "0.10"


def test_reported_qualitative_result_needs_no_analysis_representation() -> None:
    document = _document()
    result = document["studies"][0]["results"][0]
    result["collection_assessment"] = {
        "status": "qualitative result reported",
        "rationale": "The Report states there was no difference but gives no arm-level values.",
        "report_ids": ["report-1"],
        "limitations": ["No result-specific denominators were reported."],
    }
    result["analysis_representations"] = []
    result["calculation_ids"] = []
    document["studies"][0]["calculations"] = []

    validated = validate_study_data_collection_document(
        document,
        expected_binding=_binding(),
        require_completed=True,
        calculate=_CALCULATOR.calculate,
    )

    collected = validated["studies"][0]["results"][0]
    assert collected["collection_assessment"]["status"] == (
        "qualitative result reported"
    )
    assert collected["analysis_representations"] == []
    projections, summary = project_study_data_collection(validated)
    assert summary["analysis_representation_count"] == 0
    assert summary["result_without_analysis_representation_count"] == 1
    assert projections["review-1-study-results.csv"].count(b"\n") == 1


def test_analysis_representation_calculation_requires_declared_output() -> None:
    document = _document()
    cell = document["studies"][0]["results"][0]["analysis_representations"][0][
        "result"
    ]["arm-level-result"]["dichotomous-data-rows"][0]["cases"]
    cell["origin"]["calculation_id"] = "different-calculation"

    with pytest.raises(
        StudyDataCollectionError,
        match="not declared by Result",
    ):
        validate_study_data_collection_document(
            document,
            expected_binding=_binding(),
            require_completed=True,
            calculate=_CALCULATOR.calculate,
        )


def test_revman_projection_uses_arm_ids_and_preserves_zero_event_arm() -> None:
    document = _document()
    study = document["studies"][0]
    control = deepcopy(study["arms"][0])
    control["arm_id"] = "arm-control"
    control["role"] = "comparator"
    control["label"] = _field("Usual care")
    study["arms"].append(control)
    study["source_observations"].extend(
        [
            {
                "observation_id": "obs-control-events",
                "report_id": "report-1",
                "target_id": "target-1",
                "source_locator": "https://example.test/report",
                "source_location": "Table 2",
                "evidence_description": "Control events",
                "reported_name": "Control events",
                "reported_value": {"kind": "integer", "value": 0},
            },
            {
                "observation_id": "obs-control-n",
                "report_id": "report-1",
                "target_id": "target-1",
                "source_locator": "https://example.test/report",
                "source_location": "Table 2",
                "evidence_description": "Control denominator",
                "reported_name": "Control denominator",
                "reported_value": {"kind": "integer", "value": 25},
            },
        ]
    )
    result = study["results"][0]
    result["source_observation_ids"].extend(
        ["obs-control-events", "obs-control-n"]
    )
    rows = result["analysis_representations"][0]["result"]["arm-level-result"][
        "dichotomous-data-rows"
    ]
    rows.append(
        {
            "arm_id": "arm-control",
            "cases": {
                "value_id": "value-control-events",
                "value": 0,
                "origin": {
                    "kind": "observed",
                    "observation_id": "obs-control-events",
                },
            },
            "sample-size": {
                "value_id": "value-control-n",
                "value": 25,
                "origin": {
                    "kind": "observed",
                    "observation_id": "obs-control-n",
                },
            },
        }
    )

    validated = validate_study_data_collection_document(
        document,
        expected_binding=_binding(),
        require_completed=True,
        calculate=_CALCULATOR.calculate,
    )
    files, _ = project_study_data_collection(validated)
    projected = list(
        csv.DictReader(io.StringIO(files["review-1-study-results.csv"].decode()))
    )
    assert [(row["Arm"], row["Cases"]) for row in projected] == [
        ("NCPAP", "4"),
        ("Usual care", "0"),
    ]


def test_unknown_arm_id_is_rejected_as_referential_integrity() -> None:
    document = _document()
    row = document["studies"][0]["results"][0]["analysis_representations"][0][
        "result"
    ]["arm-level-result"]["dichotomous-data-rows"][0]
    row["arm_id"] = "missing-arm"

    with pytest.raises(StudyDataCollectionError, match="unknown Study arm id"):
        validate_study_data_collection_document(
            document,
            expected_binding=_binding(),
            require_completed=True,
            calculate=_CALCULATOR.calculate,
        )


def test_observed_value_mismatch_is_rejected_without_path_resolution() -> None:
    document = _document()
    cell = document["studies"][0]["results"][0]["analysis_representations"][0][
        "result"
    ]["arm-level-result"]["dichotomous-data-rows"][0]["sample-size"]
    cell["value"] = 24

    with pytest.raises(StudyDataCollectionError, match="does not match its declared origin"):
        validate_study_data_collection_document(
            document,
            expected_binding=_binding(),
            require_completed=True,
            calculate=_CALCULATOR.calculate,
        )


def test_not_started_report_cannot_claim_access_attempts() -> None:
    document = _document()
    coverage = document["studies"][0]["report_coverage"][0]
    coverage["status"] = "not_started"

    with pytest.raises(
        StudyDataCollectionError,
        match="not_started Report coverage cannot contain access attempts",
    ):
        validate_study_data_collection_document(
            document,
            expected_binding=_binding(),
            require_completed=False,
            calculate=_CALCULATOR.calculate,
        )


def test_inspected_report_requires_accessed_content() -> None:
    document = _document()
    coverage = document["studies"][0]["report_coverage"][0]
    coverage["attempts"][0]["accessed"] = False

    with pytest.raises(
        StudyDataCollectionError,
        match="inspected Report coverage requires actually accessed content",
    ):
        validate_study_data_collection_document(
            document,
            expected_binding=_binding(),
            require_completed=True,
            calculate=_CALCULATOR.calculate,
        )


def test_unreachable_report_is_valid_local_unavailability() -> None:
    document = _document()
    coverage = document["studies"][0]["report_coverage"][0]
    coverage["status"] = "unavailable"
    coverage["reason"] = "Known full-text route returned HTTP 403."
    coverage["attempts"][0].update(
        {
            "accessed": False,
            "content_scope": "other",
            "summary": "Publisher route returned HTTP 403.",
        }
    )

    validated = validate_study_data_collection_document(
        document,
        expected_binding=_binding(),
        require_completed=True,
        calculate=_CALCULATOR.calculate,
    )

    assert validated["status"] == "completed"
    assert validated["studies"][0]["report_coverage"][0]["status"] == "unavailable"


class _Runtime:
    provider = AgentProvider.OPENAI

    def __init__(self) -> None:
        self.requests: list[AgentRunRequest] = []

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.requests.append(request)
        document = _document()
        document["binding"] = dict(request.input_data["binding"])
        content = canonical_json_bytes(document)
        relative = request.output_artifacts["document"]
        return AgentRunResult(
            provider=AgentProvider.OPENAI,
            model="openai/test-model",
            run_id=request.run_id,
            session_id=f"session-{request.run_id}",
            output={
                "status": "completed",
                "issues": [],
                "blocker": None,
                "warnings": [],
                "human_independent_extraction_satisfied": False,
            },
            events=(),
            stderr="",
            duration_seconds=1.0,
            web_access_audit=WebAccessAudit(True, False, 0, ()),
            skill_snapshots=(
                AgentSkillSnapshot("collect-study-data", "a" * 64),
                AgentSkillSnapshot("find-and-read-reports", "b" * 64),
            ),
            output_artifacts={
                "document": AgentOutputArtifact(
                    name="document",
                    relative_path=relative,
                    content=content,
                    sha256=f"sha256:{sha256(content).hexdigest()}",
                )
            },
        )


def _selection(tmp_path: Path, protocol_version: str):
    provenance = (
        Provenance(
            "report-1",
            "report",
            "https://example.test/report",
        ),
    )
    collections = SelectionCollections(
        record_screening=(),
        reports=(
            Report(
                report_id="report-1",
                title="Example report",
                report_type="journal_article",
                locators=("https://example.test/report",),
                provenance=provenance,
            ),
            Report(
                report_id="report-2",
                title="Awaiting report",
                report_type="journal_article",
                locators=("https://example.test/paywalled",),
                provenance=provenance,
            ),
        ),
        report_discoveries=(),
        record_report_links=(),
        report_evidence=(),
        studies=(
            Study("study-1", "Example 1995", provenance),
            Study("study-2", "Awaiting 2001", provenance),
        ),
        study_report_links=(
            StudyReportLink(
                "study-1",
                "report-1",
                True,
                "Primary results Report",
                provenance,
            ),
            StudyReportLink(
                "study-2",
                "report-2",
                True,
                "Only identified Report",
                provenance,
            ),
        ),
        study_decisions=(
            StudyEligibilityDecision(
                study_id="study-1",
                classification=StudyClassification.INCLUDED,
                reason="Meets Protocol eligibility",
                provenance=provenance,
            ),
            StudyEligibilityDecision(
                study_id="study-2",
                classification=StudyClassification.AWAITING_CLASSIFICATION,
                reason="The complete Report remained unavailable.",
                follow_up_actions=(
                    "Reassess when a complete Report becomes available.",
                ),
                provenance=provenance,
            ),
        ),
        conflicts=(),
    )
    store = FileSelectionPackageStore(tmp_path / "selection")
    reference = store.persist(
        review_id="review-1",
        protocol_version=protocol_version,
        collections=collections,
        agent_runs=(
            SelectionAgentSnapshot(
                "primary-agent",
                {"status": "completed"},
                {"selection/manifest.json": b"{}\n"},
            ),
        ),
    )
    artifact = StudySelectionArtifact(
        package_ref=reference,
        summary=SelectionSummary(
            source_record_count=0,
            duplicate_record_count=0,
            records_screened_count=0,
            title_abstract_excluded_count=0,
            reports_sought_count=2,
            reports_not_retrieved_count=1,
            reports_assessed_count=1,
            study_count=2,
            included_count=1,
            excluded_count=0,
            awaiting_classification_count=1,
            ongoing_count=0,
            unresolved_conflict_count=0,
        ),
    )
    return store, artifact


def test_one_runtime_call_completes_both_characteristics_and_results(
    protocol,
    tmp_path: Path,
) -> None:
    selection_store, selection = _selection(tmp_path, protocol.version)
    runtime = _Runtime()
    executor = AgentTaskExecutorAdapter(
        runtime,
        (
            _SKILL,
            _SKILL.parents[1] / "shared/find-and-read-reports",
        ),
    )
    store = FileStudyDataCollectionStore(
        tmp_path / "study-data",
        _CALCULATOR.calculate,
    )
    task = CollectStudyDataTask(
        executor=executor,
        selection_package_store=selection_store,
        data_collection_store=store,
        calculate=_CALCULATOR.calculate,
        run_id_factory=lambda: "study-data-run-1",
    )

    result = task.collect(
        StudyDataCollectionInput(
            protocol=study_data_collection_protocol_from_draft(protocol),
            selection=selection,
        ),
        TaskContext("review-1", protocol.version),
    )

    assert result.status is TaskWorkStatus.COMPLETED
    assert result.artifact is not None
    assert len(runtime.requests) == 1
    request = runtime.requests[0]
    assert request.task_name == "study_data_collection"
    assert "Complete the Study Data Collection task" in request.prompt
    assert "produce the declared Study Data document" in request.prompt
    assert "Do not defer any Study" not in request.prompt
    assert "or advance" not in request.prompt
    assert "work_id" not in request.input_data
    assert "prior_checkpoint" not in request.input_data
    assert "prior-checkpoint" not in request.input_artifacts
    output_schema = json.dumps(request.output_schema)
    assert '"completed"' in output_schema
    assert '"blocked"' in output_schema
    assert '"incomplete"' not in output_schema
    assert selection.summary.included_count == 1
    assert selection.summary.awaiting_classification_count == 1
    assert set(request.input_artifacts) == {
        "selection-package",
        "work-binding",
    }
    assert {item.name for item in result.artifact.files} == {
        "review-1-study-data-collection.json",
        "review-1-study-characteristics.jsonl",
        "review-1-study-arms.csv",
        "review-1-study-results.csv",
    }
