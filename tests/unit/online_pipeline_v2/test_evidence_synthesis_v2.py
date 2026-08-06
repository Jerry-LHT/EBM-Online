from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactFile,
    CompletedArtifactRef,
    Provenance,
    TaskContext,
    TaskName,
    TaskWorkStatus,
)
from ebm_backend.online_pipeline_v2.domain.risk_of_bias import (
    RiskOfBiasArtifact,
    RiskOfBiasPackageRef,
    RiskOfBiasReviewProcess,
    RiskOfBiasSummary,
)
from ebm_backend.online_pipeline_v2.domain.synthesis import (
    EvidenceSynthesisInput,
    SynthesisRiskOfBiasEvidence,
    SynthesisRiskOfBiasSourceStatus,
    SynthesisRiskOfBiasStudy,
    SynthesisRiskOfBiasUnassessedResult,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution import (
    load_skill_tool,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.contracts import (
    TaskExecution,
    TaskOutputArtifact,
    TaskOutputError,
    TaskProvider,
    TaskRunResult,
    WebAccessAudit,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.tasks import (
    evidence_synthesis as synthesis_task_module,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.tasks.evidence_synthesis import (
    SynthesizeEvidenceTask,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.formats.evidence_synthesis import (
    parse_synthesis_ledger,
    project_synthesis_csv,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.work.evidence_synthesis import (
    FileEvidenceSynthesisStore,
)


_SKILL = (
    Path(__file__).parents[3]
    / "backend/src/ebm_backend/online_pipeline_v2/infrastructure/agent_execution/"
    "skills/evidence_synthesis/synthesize-evidence"
)


def test_synthesis_task_persists_one_v3_document_from_unified_collection(
    tmp_path: Path,
    synthesis_protocol,
    monkeypatch,
) -> None:
    review_id = "review-1"
    collection_document = tmp_path / "study-data.json"
    collection_document.write_text(
        json.dumps(
            {
                "studies": [
                    {
                        "study_id": "study-1",
                        "results": [
                            {
                                "result_id": "result-1",
                                "analysis_representations": [
                                    {
                                        "representation_id": "upstream-rep-1",
                                        "result": _upstream_values(5, 20),
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    collection_ref = CompletedArtifactRef(
        artifact_id="collection-1",
        schema_version="study-data-collection-artifact.v3",
        review_id=review_id,
        protocol_version=synthesis_protocol.version,
        task=TaskName.STUDY_DATA_COLLECTION,
        content_digest="sha256:collection",
        files=(ArtifactFile("study-data.json", "sha256:file", 1),),
        counts={"study_count": 1},
    )
    collection_snapshot = SimpleNamespace(
        artifact=collection_ref,
        document_path=collection_document,
        public_directory=tmp_path,
        document={},
    )
    risk_artifact = RiskOfBiasArtifact(
        package_ref=RiskOfBiasPackageRef(
            "rob-package",
            review_id,
            synthesis_protocol.version,
            "risk-of-bias-package.v4",
            "sha256:rob",
        ),
        document=SimpleNamespace(),
        summary=RiskOfBiasSummary(0, 0, 0, 0, 0, 0),
        review_process=RiskOfBiasReviewProcess("rob-run"),
    )
    risk_view = SynthesisRiskOfBiasEvidence(
        studies=(),
        provenance=(Provenance("sha256:rob", "risk_of_bias_artifact"),),
    )
    monkeypatch.setattr(
        synthesis_task_module,
        "synthesis_risk_of_bias_from_artifact",
        lambda _: risk_view,
    )
    compute = load_skill_tool(
        _SKILL,
        "scripts/meta_compute.py",
        "compute_meta_analysis",
    )
    calculate_scalar = load_skill_tool(
        _SKILL,
        "scripts/scalar_calculate.py",
        "calculate",
    )
    synthesis_store = FileEvidenceSynthesisStore(
        tmp_path / "synthesis",
        compute,
        calculate_scalar,
    )
    executor = _CompletedNoPoolingExecutor(review_id)
    task = SynthesizeEvidenceTask(
        executor=executor,
        data_collection_store=SimpleNamespace(resolve=lambda _: collection_snapshot),
        synthesis_store=synthesis_store,
        compute_meta_analysis=compute,
        calculate_scalar=calculate_scalar,
    )

    result = task.synthesize(
        EvidenceSynthesisInput(
            protocol=synthesis_protocol,
            study_data_collection=collection_ref,
            risk_of_bias=risk_artifact,
        ),
        TaskContext(review_id, synthesis_protocol.version),
    )

    assert result.status is TaskWorkStatus.COMPLETED
    assert result.artifact is not None
    assert result.artifact.schema_version == "evidence-synthesis-artifact.v3"
    assert result.artifact.warnings == ()
    snapshot = synthesis_store.resolve(result.artifact.artifact_id)
    assert snapshot.document_path.name == f"{review_id}-synthesis.json"
    assert not (snapshot.document_path.parents[1] / "private").exists()
    assert {item.name for item in result.artifact.files} == {
        f"{review_id}-synthesis.json",
        f"{review_id}-data-rows.csv",
        f"{review_id}-subgroup-estimates.csv",
        f"{review_id}-overall-estimates-and-settings.csv",
    }
    assert "results_artifact_id" not in executor.request.input_data


def test_synthesis_completes_with_no_evidence_when_included_study_has_no_result(
    tmp_path: Path,
    synthesis_protocol,
    monkeypatch,
) -> None:
    review_id = "review-1"
    collection_document = tmp_path / "study-data.json"
    collection_document.write_text(
        json.dumps({"studies": [{"study_id": "study-1", "results": []}]}),
        encoding="utf-8",
    )
    collection_ref = CompletedArtifactRef(
        artifact_id="collection-empty-results",
        schema_version="study-data-collection-artifact.v3",
        review_id=review_id,
        protocol_version=synthesis_protocol.version,
        task=TaskName.STUDY_DATA_COLLECTION,
        content_digest="sha256:collection-empty-results",
        files=(ArtifactFile("study-data.json", "sha256:file", 1),),
        counts={"study_count": 1, "result_count": 0},
    )
    collection_snapshot = SimpleNamespace(
        artifact=collection_ref,
        document_path=collection_document,
        public_directory=tmp_path,
        document={"studies": [{"study_id": "study-1", "results": []}]},
    )
    risk_artifact = RiskOfBiasArtifact(
        package_ref=RiskOfBiasPackageRef(
            "rob-empty-results",
            review_id,
            synthesis_protocol.version,
            "risk-of-bias-package.v4",
            "sha256:rob-empty-results",
        ),
        document=SimpleNamespace(
            method_uses=(),
            targets=(),
            assessments=(),
            coverage=SimpleNamespace(
                scope="Protocol-relevant Results",
                rationale="No applicable Study Result was available.",
                unassessed_results=(
                    SimpleNamespace(
                        study_id="study-1",
                        study_result_id=None,
                        description="No method-applicable Result was reported.",
                        reason="The Included Study had no extractable result target.",
                    ),
                ),
            ),
        ),
        summary=RiskOfBiasSummary(0, 0, 0, 0, 1, 0),
        review_process=RiskOfBiasReviewProcess("rob-run"),
    )
    risk_view = SynthesisRiskOfBiasEvidence(
        studies=(
            SynthesisRiskOfBiasStudy(
                study_id="study-1",
                source_status=SynthesisRiskOfBiasSourceStatus.EMPTY,
                assessments=(),
                unassessed_results=(
                    SynthesisRiskOfBiasUnassessedResult(
                        study_id="study-1",
                        study_result_id=None,
                        description="No method-applicable Result was reported.",
                        reason="The Included Study had no extractable result target.",
                    ),
                ),
            ),
        ),
        provenance=(Provenance("sha256:rob-empty-results", "risk_of_bias_artifact"),),
        coverage_scope="Protocol-relevant Results",
        coverage_rationale="No applicable Study Result was available.",
    )
    monkeypatch.setattr(
        synthesis_task_module,
        "synthesis_risk_of_bias_from_artifact",
        lambda _: risk_view,
    )
    compute = load_skill_tool(
        _SKILL,
        "scripts/meta_compute.py",
        "compute_meta_analysis",
    )
    calculate_scalar = load_skill_tool(
        _SKILL,
        "scripts/scalar_calculate.py",
        "calculate",
    )
    synthesis_store = FileEvidenceSynthesisStore(
        tmp_path / "synthesis",
        compute,
        calculate_scalar,
    )
    task = SynthesizeEvidenceTask(
        executor=_CompletedNoPoolingExecutor(review_id, no_evidence=True),
        data_collection_store=SimpleNamespace(resolve=lambda _: collection_snapshot),
        synthesis_store=synthesis_store,
        compute_meta_analysis=compute,
        calculate_scalar=calculate_scalar,
    )

    result = task.synthesize(
        EvidenceSynthesisInput(
            protocol=synthesis_protocol,
            study_data_collection=collection_ref,
            risk_of_bias=risk_artifact,
        ),
        TaskContext(review_id, synthesis_protocol.version),
    )

    assert result.status is TaskWorkStatus.COMPLETED
    assert result.progress["no_evidence_count"] == 1
    assert result.progress["representation_count"] == 0


def test_scalar_derivation_is_recomputed_and_bound_to_upstream_values(
    tmp_path: Path,
) -> None:
    binding = {
        "review_id": "review-1",
        "protocol_version": "protocol-1",
        "protocol_digest": "sha256:protocol",
        "study_data_collection_artifact_id": "collection-1",
        "study_data_collection_artifact_digest": "sha256:collection",
        "risk_of_bias_artifact_id": "rob-1",
        "risk_of_bias_artifact_digest": "sha256:rob",
    }
    calculate_scalar = load_skill_tool(
        _SKILL,
        "scripts/scalar_calculate.py",
        "calculate",
    )
    compute = load_skill_tool(
        _SKILL,
        "scripts/meta_compute.py",
        "compute_meta_analysis",
    )
    specification = {
        "expression": "(events / sample) * 100",
        "inputs": {"events": 1, "sample": 3},
        "precision": 34,
    }
    calculated = calculate_scalar(specification)
    document = _no_pooling_document(binding=binding)
    representation = document["analyses"][0]["representations"][0]
    representation["values"] = {"percentage": calculated["outputs"]["value"]}
    representation["result_value_sources"] = []
    representation["calculated_value_sources"] = [
        {
            "trace_id": "scalar-1",
            "output_name": "value",
            "value_name": "percentage",
            "inputs": [
                {
                    "result_id": "result-1",
                    "representation_id": "upstream-rep-1",
                    "source_value_id": "upstream-events",
                    "input_name": "events",
                },
                {
                    "result_id": "result-1",
                    "representation_id": "upstream-rep-1",
                    "source_value_id": "upstream-sample-size",
                    "input_name": "sample",
                },
            ],
        }
    ]
    document["analyses"][0]["calculation_traces"] = [
        {
            "trace_id": "scalar-1",
            "tool": "scalar-calculate",
            "engine_id": calculated["engine_id"],
            "engine_version": calculated["engine_version"],
            "input_digest": calculated["input_digest"],
            "output_digest": calculated["output_digest"],
            "input": specification,
            "output": calculated,
            "representation_projections": [],
            "input_projections": [],
            "projections": [],
        }
    ]
    document["analyses"][0]["calculation_traces"][0][
        "output_digest"
    ] = "sha256:agent-serialized-output"
    representation["values"]["percentage"] = 999
    collection = tmp_path / "collection.json"
    collection.write_text(
        json.dumps(
            {
                "studies": [
                    {
                        "study_id": "study-1",
                        "results": [
                            {
                                "result_id": "result-1",
                                "analysis_representations": [
                                    {
                                        "representation_id": "upstream-rep-1",
                                        "result": _upstream_values(1, 3),
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    parsed = parse_synthesis_ledger(
        (json.dumps(document) + "\n").encode(),
        expected_binding=binding,
        require_completed=True,
        compute=compute,
        calculate_scalar=calculate_scalar,
    )
    warnings = synthesis_task_module._validate_upstream_references(
        parsed,
        collection_document=collection,
        risk_of_bias=SynthesisRiskOfBiasEvidence(
            studies=(),
            provenance=(Provenance("rob", "risk_of_bias_artifact"),),
        ),
    )
    assert parsed["analyses"][0]["representations"][0]["values"][
        "percentage"
    ] == calculated["outputs"]["value"]
    assert any("calculator output is authoritative" in warning for warning in warnings)
    assert {
        issue["code"] for issue in parsed["issues"]
    } >= {
        "synthesis_calculation_trace_normalized",
        "synthesis_scalar_value_normalized",
    }


def test_unknown_source_value_id_is_a_core_validation_error(
    tmp_path: Path,
) -> None:
    binding = {
        "review_id": "review-1",
        "protocol_version": "protocol-1",
        "protocol_digest": "sha256:protocol",
        "study_data_collection_artifact_id": "collection-1",
        "study_data_collection_artifact_digest": "sha256:collection",
        "risk_of_bias_artifact_id": "rob-1",
        "risk_of_bias_artifact_digest": "sha256:rob",
    }
    compute = load_skill_tool(
        _SKILL,
        "scripts/meta_compute.py",
        "compute_meta_analysis",
    )
    calculate_scalar = load_skill_tool(
        _SKILL,
        "scripts/scalar_calculate.py",
        "calculate",
    )
    collection = tmp_path / "collection.json"
    collection.write_text(
        json.dumps(
            {
                "studies": [
                    {
                        "study_id": "study-1",
                        "results": [
                            {
                                "result_id": "result-1",
                                "analysis_representations": [
                                    {
                                        "representation_id": "upstream-rep-1",
                                        "result": _upstream_values(5, 20),
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    risk_of_bias = SynthesisRiskOfBiasEvidence(
        studies=(),
        provenance=(Provenance("rob", "risk_of_bias_artifact"),),
    )

    document = _no_pooling_document(binding=binding)
    document["analyses"][0]["representations"][0]["result_value_sources"][0][
        "source_value_id"
    ] = "missing-value"
    parsed = parse_synthesis_ledger(
        (json.dumps(document) + "\n").encode(),
        expected_binding=binding,
        require_completed=True,
        compute=compute,
        calculate_scalar=calculate_scalar,
    )
    with pytest.raises(TaskOutputError, match="unknown source value"):
        synthesis_task_module._validate_upstream_references(
            parsed,
            collection_document=collection,
            risk_of_bias=risk_of_bias,
        )


def test_unknown_result_remains_a_core_validation_error(
    tmp_path: Path,
) -> None:
    binding = {
        "review_id": "review-1",
        "protocol_version": "protocol-1",
        "protocol_digest": "sha256:protocol",
        "study_data_collection_artifact_id": "collection-1",
        "study_data_collection_artifact_digest": "sha256:collection",
        "risk_of_bias_artifact_id": "rob-1",
        "risk_of_bias_artifact_digest": "sha256:rob",
    }
    compute = load_skill_tool(
        _SKILL,
        "scripts/meta_compute.py",
        "compute_meta_analysis",
    )
    calculate_scalar = load_skill_tool(
        _SKILL,
        "scripts/scalar_calculate.py",
        "calculate",
    )
    document = _no_pooling_document(binding=binding)
    collection = tmp_path / "collection.json"
    collection.write_text(
        json.dumps(
            {
                "studies": [
                    {
                        "study_id": "study-1",
                        "results": [{"result_id": "different-result"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    parsed = parse_synthesis_ledger(
        (json.dumps(document) + "\n").encode(),
        expected_binding=binding,
        require_completed=True,
        compute=compute,
        calculate_scalar=calculate_scalar,
    )

    with pytest.raises(TaskOutputError, match="Result outside its Study"):
        synthesis_task_module._validate_upstream_references(
            parsed,
            collection_document=collection,
            risk_of_bias=SynthesisRiskOfBiasEvidence(
                studies=(),
                provenance=(Provenance("rob", "risk_of_bias_artifact"),),
            ),
        )


class _CompletedNoPoolingExecutor:
    def __init__(
        self,
        review_id: str,
        *,
        no_evidence: bool = False,
    ) -> None:
        self.review_id = review_id
        self.no_evidence = no_evidence
        self.request = None

    def execute(self, request, *, output_adapter, error_context):
        self.request = request
        document = _no_pooling_document(
            binding=dict(request.input_data["binding"]),
        )
        if self.no_evidence:
            analysis = document["analyses"][0]
            analysis["compatibility"]["rationale"] = (
                "No Study Result was available for the planned question."
            )
            analysis["representations"] = []
            analysis["contributions"] = [
                {
                    "study_id": "study-1",
                    "included": False,
                    "reason": "The Included Study reported no applicable Result.",
                }
            ]
            analysis["no_pooling"] = None
            analysis["no_evidence"] = {
                "reason": "No applicable Study Result was available."
            }
        content = (json.dumps(document, sort_keys=True) + "\n").encode()
        csvs = project_synthesis_csv(document)
        artifacts = {
            "document": _output(
                "document",
                "outputs/synthesis/document.json",
                content,
            ),
            "data_rows": _output(
                "data_rows",
                request.output_artifacts["data_rows"],
                csvs[f"{self.review_id}-data-rows.csv"],
            ),
            "subgroup_estimates": _output(
                "subgroup_estimates",
                request.output_artifacts["subgroup_estimates"],
                csvs[f"{self.review_id}-subgroup-estimates.csv"],
            ),
            "overall_estimates": _output(
                "overall_estimates",
                request.output_artifacts["overall_estimates"],
                csvs[f"{self.review_id}-overall-estimates-and-settings.csv"],
            ),
        }
        run = TaskRunResult(
            provider=TaskProvider.OPENAI,
            model="fake",
            run_id=request.run_id,
            session_id=None,
            output={"status": "completed", "issues": [], "warnings": []},
            events=(),
            stderr="",
            duration_seconds=0.01,
            web_access_audit=WebAccessAudit(False, False, 0, ()),
            skill_snapshots=(),
            output_artifacts=artifacts,
        )
        return TaskExecution(run, output_adapter.validate_python(run.output))


def _no_pooling_document(*, binding: dict[str, str]) -> dict:
    return {
        "schema_version": "evidence-synthesis-document.v3",
        "binding": binding,
        "status": "completed",
        "review_process": {
            "human_independent_synthesis_satisfied": False,
            "methodology_authorities": [],
            "method_decisions": [],
        },
        "analyses": [
            {
                "analysis_id": "analysis-1",
                "synthesis_pico_id": None,
                "origin": "protocol_planned",
                "change_rationale": None,
                "definition": {
                    "population": "adults",
                    "intervention": "intervention",
                    "comparator": "usual care",
                    "outcome": "mortality",
                    "time_point": "12 months",
                    "study_designs": ["randomized trial"],
                },
                "compatibility": {
                    "rationale": "Only one compatible Study was available.",
                    "clinical": "The Study matches the planned population.",
                    "methodological": "The eligible design matches the Protocol.",
                    "statistical": "A pooled estimate requires multiple Studies.",
                },
                "authority_ids": [],
                "method_decision_ids": [],
                "settings": {},
                "representations": [
                    {
                        "representation_id": "analysis-rep-1",
                        "study_id": "study-1",
                        "data_type": "dichotomous",
                        "effect_measure": "risk",
                        "source_result_ids": ["result-1"],
                        "values": {"events": 5, "sample_size": 20},
                        "result_value_sources": [
                            {
                                "result_id": "result-1",
                                "representation_id": "upstream-rep-1",
                                "source_value_id": "upstream-events",
                                "value_name": "events",
                            },
                            {
                                "result_id": "result-1",
                                "representation_id": "upstream-rep-1",
                                "source_value_id": "upstream-sample-size",
                                "value_name": "sample_size",
                            },
                        ],
                        "calculated_value_sources": [],
                    }
                ],
                "contributions": [
                    {
                        "study_id": "study-1",
                        "included": True,
                        "reason": "Eligible evidence for this synthesis question.",
                    }
                ],
                "risk_of_bias_refs": [],
                "calculation_traces": [],
                "data_rows": [],
                "subgroup_estimates": [],
                "overall_estimates_and_settings": [],
                "alternative_synthesis": None,
                "no_pooling": {"reason": "Only one Study was available."},
                "no_evidence": None,
                "issues": [],
            }
        ],
        "issues": [],
    }


def _upstream_values(events: int, sample_size: int) -> dict:
    return {
        "events": {
            "value_id": "upstream-events",
            "value": events,
            "origin": {"kind": "observed", "observation_id": "obs-events"},
        },
        "sample_size": {
            "value_id": "upstream-sample-size",
            "value": sample_size,
            "origin": {"kind": "observed", "observation_id": "obs-sample"},
        },
    }


def _output(name: str, path: str, content: bytes) -> TaskOutputArtifact:
    return TaskOutputArtifact(
        name=name,
        relative_path=path,
        content=content,
        sha256=f"sha256:{sha256(content).hexdigest()}",
    )
