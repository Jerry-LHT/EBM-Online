from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import TypeAdapter

from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactFile,
    ArtifactStatus,
    CompletedArtifactRef,
    Provenance,
    TaskContext,
    TaskName,
)
from ebm_backend.online_pipeline_v2.domain.risk_of_bias import (
    RiskOfBiasAssessment,
    RiskOfBiasAssessmentItem,
    RiskOfBiasAssessmentSection,
    RiskOfBiasBinding,
    RiskOfBiasCoverage,
    RiskOfBiasDocumentV4,
    RiskOfBiasDomainAssessment,
    RiskOfBiasInput,
    RiskOfBiasMethodUse,
    RiskOfBiasSignallingResponse,
    RiskOfBiasTarget,
)
from ebm_backend.online_pipeline_v2.domain.synthesis import (
    SynthesisRiskOfBiasSourceStatus,
    synthesis_risk_of_bias_from_artifact,
)
from ebm_backend.online_pipeline_v2.domain.study_data_collection import (
    StudyDataCollectionProtocol,
    study_data_collection_protocol_from_draft,
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
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution import (
    AgentTaskExecutorAdapter,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.contracts import (
    TaskOutputError,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.tasks.risk_of_bias import (
    AssessRiskOfBiasTask,
    risk_of_bias_output_schema,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime import (
    AgentProvider,
    AgentRunRequest,
    AgentRunResult,
    AgentSkillSnapshot,
    WebAccessAudit,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime.skill_loader import (
    load_skill,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.packages import (
    FileRiskOfBiasPackageStore,
    FileSelectionPackageStore,
    SelectionAgentSnapshot,
)


_SKILL_ROOT = (
    Path(__file__).parents[3]
    / "backend/src/ebm_backend/online_pipeline_v2/infrastructure/"
    "agent_execution/skills/risk_of_bias/risk-of-bias"
)
_STUDY_ID = "study/1:opaque"
_REPORT_ID = "report/1:opaque"
_RESULT_ID = "result/1:opaque"


def _executor(runtime) -> AgentTaskExecutorAdapter:
    return AgentTaskExecutorAdapter(runtime, (_SKILL_ROOT,))


class FakeCollectionStore:
    def __init__(self, snapshot) -> None:
        self.snapshot = snapshot

    def resolve(self, artifact):
        assert artifact == self.snapshot.artifact
        return self.snapshot


class FakeRuntime:
    provider = AgentProvider.OPENAI

    def __init__(self, *, result_id: str = _RESULT_ID) -> None:
        self.requests: list[AgentRunRequest] = []
        self.result_id = result_id

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        self.requests.append(request)
        planned = request.input_data["planned_standard"]
        binding = request.input_data["binding"]
        report_source = {
            "source_id": "report-evidence-1",
            "source_type": "report",
            "locator": "https://example.test/public-copy",
            "excerpt": "The sequence-generation method was not reported.",
        }
        authority = {
            "source_id": "official-rob1",
            "source_type": "methodology_authority",
            "locator": "https://example.test/official-rob1",
            "excerpt": None,
        }
        output = {
            "status": "completed",
            "data": {
                "schema_version": "risk-of-bias-document.v4",
                "binding": binding,
                "method_uses": [
                    {
                        "method_use_id": "rob1",
                        "planned_standard": planned,
                        "applied_standard": planned,
                        "applied_version": "version inspected by Agent",
                        "applied_variant": None,
                        "applicability": "Randomized parallel-group trial",
                        "authoritative_sources": [authority],
                        "decisions": [],
                        "protocol_conflict": None,
                    }
                ],
                "targets": [
                    {
                        "target_id": "target-1",
                        "study_id": _STUDY_ID,
                        "study_result_ids": [self.result_id],
                        "method_use_id": "rob1",
                        "outcome_id": "mortality",
                        "outcome_name": "Mortality",
                        "outcome_measurement": "All-cause mortality",
                        "timepoint": "12 months",
                        "comparison": "Intervention versus comparator",
                        "effect_of_interest": "Effect of assignment",
                        "analysis": "Primary randomized comparison",
                        "selection_rationale": "Protocol primary outcome.",
                        "provenance": [report_source],
                    }
                ],
                "assessments": [
                    {
                        "assessment_id": "assessment-1",
                        "study_id": _STUDY_ID,
                        "target_id": "target-1",
                        "method_use_id": "rob1",
                        "pre_assessment_sections": [],
                        "domains": [
                            {
                                "domain_id": "random_sequence_generation",
                                "domain_name": "Random sequence generation",
                                "applicability": None,
                                "signalling_responses": [],
                                "proposed_judgement": None,
                                "judgement": "Unclear risk",
                                "override_rationale": None,
                                "support": "The method was not reported.",
                                "bias_direction": None,
                                "evidence_observation_ids": ["observation-1"],
                                "provenance": [report_source],
                            }
                        ],
                        "overall": None,
                        "limitations": [
                            "No complete public article was found; the official "
                            "uncertainty category was applied."
                        ],
                    }
                ],
                "evidence_observations": [
                    {
                        "observation_id": "observation-1",
                        "study_id": _STUDY_ID,
                        "upstream_report_id": None,
                        "source_kind": "public author copy",
                        "source_identity": "Verified companion material",
                        "locator": "https://example.test/public-copy",
                        "observed_at": "2026-08-01",
                        "read_scope": ["Methods section"],
                        "observation": "Sequence generation was not described.",
                        "limitations": ["Complete journal article unavailable"],
                        "provenance": [report_source],
                    }
                ],
                "coverage": {
                    "scope": "Protocol-primary results represented in Study Data Collection",
                    "assessed_target_ids": ["target-1"],
                    "unassessed_results": [],
                    "rationale": "All selected targets were assessed.",
                },
            },
            "issues": [],
            "execution_summary": "Completed one RoB 1 result assessment.",
        }
        return AgentRunResult(
            provider=self.provider,
            model="openai/test-model",
            run_id=request.run_id,
            session_id="session-1",
            output=output,
            events=(),
            stderr="",
            duration_seconds=1.0,
            web_access_audit=WebAccessAudit(True, False, 0, ()),
            skill_snapshots=(AgentSkillSnapshot("risk-of-bias", "a" * 64),),
        )


class EmptyCoverageRuntime(FakeRuntime):
    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        result = await super().run(request)
        output = json.loads(json.dumps(result.output))
        data = output["data"]
        data["targets"] = []
        data["assessments"] = []
        data["evidence_observations"] = []
        data["coverage"] = {
            "scope": "Protocol-relevant Results",
            "assessed_target_ids": [],
            "unassessed_results": [
                {
                    "study_id": _STUDY_ID,
                    "study_result_id": None,
                    "description": "No method-applicable Study Result was reported.",
                    "reason": "The Included Study had no extractable result target.",
                }
            ],
            "rationale": "The Study is accounted for without inventing a target.",
        }
        output["execution_summary"] = "Completed with no applicable RoB target."
        return replace(result, output=output)


def test_one_agent_consumes_protocol_selection_and_study_data(
    protocol,
    tmp_path: Path,
) -> None:
    protocol = _rob1_protocol(protocol)
    selection_store, selection = _selection(tmp_path)
    collection = _collection(tmp_path, protocol, selection)
    risk_store = FileRiskOfBiasPackageStore(tmp_path / "risk-of-bias")
    runtime = FakeRuntime()
    adapter = AssessRiskOfBiasTask(
        executor=_executor(runtime),
        selection_package_store=selection_store,
        study_data_collection_store=FakeCollectionStore(collection),
        risk_of_bias_package_store=risk_store,
        run_id_factory=lambda: "risk-of-bias-run-1",
    )

    completion = adapter.assess(
        RiskOfBiasInput(protocol, selection, collection.artifact),
        TaskContext("review-1", "protocol-1"),
    )

    assert completion.status is ArtifactStatus.COMPLETED
    assert completion.data is not None
    assert completion.data.document.targets[0].study_result_ids == (_RESULT_ID,)
    assert completion.data.document.assessments[0].domains[0].judgement == (
        "Unclear risk"
    )
    assert completion.data.summary.target_count == 1
    assert completion.data.package_ref.schema_version == "risk-of-bias-package.v4"
    risk_store.validate(completion.data.package_ref)
    assert len(runtime.requests) == 1
    request = runtime.requests[0]
    assert request.input_data["review_mode"] == "single_agent"
    assert request.input_data["declared_tools"] == []
    assert request.enable_workspace_network is True
    assert request.enable_web_search is True
    assert set(request.input_artifacts) == {
        "selection-package",
        "study-data-collection",
    }


def test_unknown_study_result_is_rejected(protocol, tmp_path: Path) -> None:
    protocol = _rob1_protocol(protocol)
    selection_store, selection = _selection(tmp_path)
    collection = _collection(tmp_path, protocol, selection)
    adapter = AssessRiskOfBiasTask(
        executor=_executor(FakeRuntime(result_id="unknown-result")),
        selection_package_store=selection_store,
        study_data_collection_store=FakeCollectionStore(collection),
        risk_of_bias_package_store=FileRiskOfBiasPackageStore(
            tmp_path / "risk-of-bias"
        ),
    )

    with pytest.raises(TaskOutputError, match="unknown Study Result"):
        adapter.assess(
            RiskOfBiasInput(protocol, selection, collection.artifact),
            TaskContext("review-1", "protocol-1"),
        )


def test_completed_rob_can_record_no_applicable_result_and_synthesis_keeps_it(
    protocol,
    tmp_path: Path,
) -> None:
    protocol = _rob1_protocol(protocol)
    selection_store, selection = _selection(tmp_path)
    collection = _collection(tmp_path, protocol, selection, include_result=False)
    adapter = AssessRiskOfBiasTask(
        executor=_executor(EmptyCoverageRuntime()),
        selection_package_store=selection_store,
        study_data_collection_store=FakeCollectionStore(collection),
        risk_of_bias_package_store=FileRiskOfBiasPackageStore(
            tmp_path / "risk-of-bias"
        ),
    )

    completion = adapter.assess(
        RiskOfBiasInput(protocol, selection, collection.artifact),
        TaskContext("review-1", "protocol-1"),
    )

    assert completion.status is ArtifactStatus.COMPLETED
    assert completion.data is not None
    assert completion.data.summary.target_count == 0
    assert completion.data.summary.assessment_count == 0
    assert completion.data.summary.unassessed_result_count == 1
    synthesis_view = synthesis_risk_of_bias_from_artifact(completion.data)
    assert synthesis_view.coverage_scope == "Protocol-relevant Results"
    assert synthesis_view.studies[0].source_status is SynthesisRiskOfBiasSourceStatus.EMPTY
    assert synthesis_view.studies[0].assessments == ()
    assert synthesis_view.studies[0].unassessed_results[0].study_result_id is None
    assert "no extractable result" in (
        synthesis_view.studies[0].unassessed_results[0].reason
    )


def test_empty_rob_document_requires_explicit_unassessed_coverage(
    source: Provenance,
) -> None:
    with pytest.raises(ValueError, match="explicit unassessed coverage"):
        RiskOfBiasDocumentV4(
            schema_version="risk-of-bias-document.v4",
            binding=RiskOfBiasBinding(
                review_id="review-1",
                protocol_version="protocol-1",
                complete_protocol_digest="sha256:complete-protocol",
                study_data_protocol_projection_digest="sha256:study-data-protocol",
                selection_package_id="selection-1",
                selection_package_digest="sha256:selection",
                study_data_collection_artifact_id="data-1",
                study_data_collection_digest="sha256:data",
            ),
            method_uses=(
                RiskOfBiasMethodUse(
                    method_use_id="rob1",
                    planned_standard="RoB 1",
                    applied_standard="RoB 1",
                    applied_version="current",
                    applicability="Included randomized Study",
                    authoritative_sources=(source,),
                ),
            ),
            coverage=RiskOfBiasCoverage(
                scope="Protocol-relevant Results",
                assessed_target_ids=(),
                rationale="No target was selected.",
            ),
        )


def test_protocol_projection_binding_is_verified_before_agent_call(
    protocol,
    tmp_path: Path,
) -> None:
    protocol = _rob1_protocol(protocol)
    selection_store, selection = _selection(tmp_path)
    collection = _collection(tmp_path, protocol, selection)
    collection.document["binding"]["protocol_digest"] = "sha256:wrong-projection"
    runtime = FakeRuntime()
    adapter = AssessRiskOfBiasTask(
        executor=_executor(runtime),
        selection_package_store=selection_store,
        study_data_collection_store=FakeCollectionStore(collection),
        risk_of_bias_package_store=FileRiskOfBiasPackageStore(
            tmp_path / "risk-of-bias"
        ),
    )

    with pytest.raises(TaskOutputError, match="deterministic Protocol projection"):
        adapter.assess(
            RiskOfBiasInput(protocol, selection, collection.artifact),
            TaskContext("review-1", "protocol-1"),
        )

    assert runtime.requests == []


def test_open_schema_represents_rob2_and_robins_context(source: Provenance) -> None:
    binding = RiskOfBiasBinding(
        review_id="review-1",
        protocol_version="protocol-1",
        complete_protocol_digest="sha256:complete-protocol",
        study_data_protocol_projection_digest="sha256:study-data-protocol",
        selection_package_id="selection-1",
        selection_package_digest="sha256:selection",
        study_data_collection_artifact_id="data-1",
        study_data_collection_digest="sha256:data",
    )
    method = RiskOfBiasMethodUse(
        method_use_id="robins",
        planned_standard="ROBINS-I",
        applied_standard="ROBINS-I",
        applied_version="version inspected at runtime",
        applied_variant="follow-up study",
        applicability="Non-randomized intervention result",
        authoritative_sources=(source,),
    )
    target = RiskOfBiasTarget(
        target_id="target-1",
        study_id=_STUDY_ID,
        study_result_ids=(_RESULT_ID,),
        method_use_id="robins",
        outcome_name="Mortality",
        outcome_measurement="All-cause mortality",
        timepoint="12 months",
        comparison="Intervention versus comparator",
        effect_of_interest="Per-protocol effect",
        analysis="Adjusted analysis",
        selection_rationale="Protocol-important outcome.",
        provenance=(source,),
    )
    section = RiskOfBiasAssessmentSection(
        section_id="target-trial",
        section_name="Target trial specification",
        items=(
            RiskOfBiasAssessmentItem(
                item_id="confounding",
                label="Important confounding domains",
                response="Age and baseline severity",
                support="Specified from Protocol and study context.",
                provenance=(source,),
            ),
        ),
    )
    domain = RiskOfBiasDomainAssessment(
        domain_id="confounding",
        domain_name="Bias due to confounding",
        signalling_responses=(
            RiskOfBiasSignallingResponse(
                question_id="q1",
                question="Was confounding addressed?",
                response="Probably yes",
                support="The adjusted model included prespecified variables.",
                provenance=(source,),
            ),
        ),
        proposed_judgement="Moderate",
        judgement="Moderate",
        support="Residual confounding remains possible.",
        provenance=(source,),
    )
    document = RiskOfBiasDocumentV4(
        schema_version="risk-of-bias-document.v4",
        binding=binding,
        method_uses=(method,),
        targets=(target,),
        assessments=(
            RiskOfBiasAssessment(
                assessment_id="assessment-1",
                study_id=_STUDY_ID,
                target_id="target-1",
                method_use_id="robins",
                pre_assessment_sections=(section,),
                domains=(domain,),
            ),
        ),
        coverage=RiskOfBiasCoverage(
            scope="Important results",
            assessed_target_ids=("target-1",),
            rationale="All selected targets were assessed.",
        ),
    )

    assert document.assessments[0].pre_assessment_sections[0].section_id == (
        "target-trial"
    )
    assert document.assessments[0].domains[0].proposed_judgement == "Moderate"


def test_package_store_rejects_full_text(tmp_path: Path) -> None:
    store = FileRiskOfBiasPackageStore(tmp_path / "risk-of-bias")
    with pytest.raises(ValueError, match="prohibited field"):
        store.persist(
            review_id="review-1",
            protocol_version="protocol-1",
            document=SimpleNamespace(
                model_dump=lambda **_: {"full_text": "not allowed"},
                method_uses=(),
                targets=(),
                assessments=(),
                evidence_observations=(),
                coverage=SimpleNamespace(unassessed_results=()),
            ),
            issues=(),
            review_process=SimpleNamespace(),
        )


def test_skill_and_schema_are_provider_neutral() -> None:
    package = load_skill(_SKILL_ROOT)
    schema = risk_of_bias_output_schema()

    assert package.name == "risk-of-bias"
    assert len(package.sha256) == 64
    assert schema["additionalProperties"] is False
    assert "risk-of-bias-document.v4" in json.dumps(schema)


def _rob1_protocol(protocol):
    return replace(
        protocol,
        methods=replace(
            protocol.methods,
            risk_of_bias=replace(
                protocol.methods.risk_of_bias,
                tool="Cochrane Risk of Bias tool version 1 (RoB 1)",
            ),
        ),
    )


def _collection(tmp_path: Path, protocol, selection, *, include_result: bool = True):
    artifact = CompletedArtifactRef(
        artifact_id="study-data-1",
        schema_version="study-data-collection-artifact.v3",
        review_id="review-1",
        protocol_version="protocol-1",
        task=TaskName.STUDY_DATA_COLLECTION,
        content_digest="sha256:study-data",
        files=(ArtifactFile("review-1-study-data-collection.json", "sha256:x", 2),),
        counts={"study_count": 1, "result_count": int(include_result)},
    )
    public = tmp_path / "study-data-public"
    public.mkdir()
    document_path = public / "review-1-study-data-collection.json"
    document = {
        "binding": {
            "review_id": "review-1",
            "protocol_version": "protocol-1",
            "protocol_digest": "sha256:"
            + sha256(
                TypeAdapter(StudyDataCollectionProtocol).dump_json(
                    study_data_collection_protocol_from_draft(protocol)
                )
            ).hexdigest(),
            "selection_package_id": selection.package_ref.package_id,
            "selection_package_digest": selection.package_ref.content_digest,
        },
        "studies": [
            {
                "study_id": _STUDY_ID,
                "report_coverage": [{"report_id": _REPORT_ID}],
                "results": ([{"result_id": _RESULT_ID}] if include_result else []),
            }
        ]
    }
    document_path.write_text(json.dumps(document), encoding="utf-8")
    return SimpleNamespace(
        artifact=artifact,
        document=document,
        document_path=document_path,
        public_directory=public,
    )


def _selection(
    tmp_path: Path,
) -> tuple[FileSelectionPackageStore, StudySelectionArtifact]:
    provenance = (
        Provenance("source-1", "report", "https://example.test/report-1"),
    )
    store = FileSelectionPackageStore(tmp_path / "selection")
    reference = store.persist(
        review_id="review-1",
        protocol_version="protocol-1",
        collections=SelectionCollections(
            record_screening=(),
            reports=(
                Report(
                    report_id=_REPORT_ID,
                    title="A randomized trial",
                    report_type="journal_article",
                    locators=("https://example.test/report-1",),
                    provenance=provenance,
                ),
            ),
            report_discoveries=(),
            record_report_links=(),
            report_evidence=(),
            studies=(Study(_STUDY_ID, "Example 2026", provenance),),
            study_report_links=(
                StudyReportLink(
                    _STUDY_ID,
                    _REPORT_ID,
                    True,
                    "Primary results Report.",
                    provenance,
                ),
            ),
            study_decisions=(
                StudyEligibilityDecision(
                    study_id=_STUDY_ID,
                    classification=StudyClassification.INCLUDED,
                    provenance=provenance,
                ),
            ),
            conflicts=(),
        ),
        agent_runs=(
            SelectionAgentSnapshot(
                "primary-agent",
                {"status": "completed"},
                {"selection/manifest.json": b"{}\n"},
            ),
        ),
    )
    return store, StudySelectionArtifact(
        package_ref=reference,
        summary=SelectionSummary(
            source_record_count=0,
            duplicate_record_count=0,
            records_screened_count=0,
            title_abstract_excluded_count=0,
            reports_sought_count=1,
            reports_not_retrieved_count=0,
            reports_assessed_count=1,
            study_count=1,
            included_count=1,
            excluded_count=0,
            awaiting_classification_count=0,
            ongoing_count=0,
            unresolved_conflict_count=0,
        ),
    )
