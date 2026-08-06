from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

from ebm_backend.online_pipeline_v2.application.use_cases.grade_summary_of_findings.execute import (
    ExecuteGradeSummaryOfFindings,
)
from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactFile,
    Provenance,
    TaskContext,
    TaskInvocation,
    TaskWorkResult,
    TaskWorkStatus,
)
from ebm_backend.online_pipeline_v2.domain.grade import (
    AbsoluteEffectCalculation,
    AbsoluteEffectScenario,
    Certainty,
    EffectPresentation,
    EffectStatus,
    GRADEConcern,
    GRADEDomain,
    GRADEDomainJudgement,
    GRADEUpgradeAssessment,
    GRADEUpgradeDomain,
    GRADEUpgradeJudgement,
    GradeEvidencePackageRef,
    GradeProtocol,
    GradeSummaryOfFindingsDraft,
    GradeSummaryOfFindingsInput,
    EvidenceProfileStatus,
    GradedGRADEAssessment,
    GradedGRADEAssessmentDraft,
    NoEvidenceGRADEProfileDraft,
    MethodologyBasisStatus,
    SummaryOfFindingsRowDraft,
    SummaryOfFindingsTableDraft,
    finalize_grade_artifact,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime.skill_loader import (
    load_skill,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime import (
    AgentProvider,
    AgentRunResult,
    AgentSkillSnapshot,
    WebAccessAudit,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution import (
    AgentTaskExecutorAdapter,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.formats.grade import (
    GradeAgentOutput,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.tasks.grade_summary_of_findings import (
    GradeEvidenceTask,
)
from ebm_backend.online_pipeline_v2.infrastructure.grade.evidence_index import (
    synthesis_analysis_ids,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.work import (
    FileGradeArtifactStore,
    FileGradeEvidencePackageStore,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.work.grade import (
    OPTIONAL_EVIDENCE_FILES,
    REQUIRED_EVIDENCE_FILES,
)
from benchmark.online_pipeline_v2.GRADE.adapter.materialize import (
    build_grade_protocol,
    persist_grade_evidence_package,
)


ROOT = Path(__file__).resolve().parents[3]
SKILL = (
    ROOT
    / "backend/src/ebm_backend/online_pipeline_v2/infrastructure"
    / "agent_execution/skills/grade_summary_of_findings/grade-evidence-and-build-sof"
)


def _executor(runtime) -> AgentTaskExecutorAdapter:
    return AgentTaskExecutorAdapter(runtime, (SKILL,))


def _judgements(provenance):
    return tuple(
        GRADEDomainJudgement(domain, GRADEConcern.NOT_SERIOUS, 0, "Supported.", provenance)
        for domain in GRADEDomain
    )


def _upgrades():
    return tuple(
        GRADEUpgradeAssessment(
            domain,
            GRADEUpgradeJudgement.NOT_APPLICABLE,
            0,
            "Not applicable.",
        )
        for domain in GRADEUpgradeDomain
    )


def test_grade_certainty_arithmetic_is_a_domain_invariant() -> None:
    provenance = (Provenance("row-1", "synthesis_row"),)
    assessment = GradedGRADEAssessment(
        evidence_body_id="body-1",
        synthesis_analysis_ids=("analysis-1",),
        status=EvidenceProfileStatus.GRADED,
        initial_certainty=Certainty.HIGH,
        initial_certainty_basis="Randomized evidence.",
        domains=_judgements(provenance),
        upgrades=_upgrades(),
        final_certainty=Certainty.HIGH,
        explanation="No reasons to downgrade.",
    )
    risk = replace(
        assessment.domains[0],
        concern=GRADEConcern.SERIOUS,
        downgrade_levels=1,
    )
    with pytest.raises(ValueError, match="final certainty"):
        replace(assessment, domains=(risk,) + assessment.domains[1:])


def test_grade_upgrade_cannot_mechanically_offset_a_downgrade() -> None:
    provenance = (Provenance("row-1", "synthesis_row"),)
    risk = replace(
        _judgements(provenance)[0],
        concern=GRADEConcern.SERIOUS,
        downgrade_levels=1,
    )
    upgrade = GRADEUpgradeAssessment(
        GRADEUpgradeDomain.LARGE_EFFECT,
        GRADEUpgradeJudgement.PRESENT,
        1,
        "Large effect.",
        provenance,
    )
    with pytest.raises(ValueError, match="upgrading applies only"):
        GradedGRADEAssessment(
            evidence_body_id="body-1",
            synthesis_analysis_ids=("analysis-1",),
            status=EvidenceProfileStatus.GRADED,
            initial_certainty=Certainty.LOW,
            initial_certainty_basis="Non-randomized evidence.",
            domains=(risk,) + _judgements(provenance)[1:],
            upgrades=(upgrade,) + _upgrades()[1:],
            final_certainty=Certainty.LOW,
            explanation="Invalid mechanical offset.",
        )


def test_application_boundary_invokes_one_grade_port(protocol: GradeProtocol) -> None:
    package = GradeEvidencePackageRef(
        package_id="package-1",
        schema_version="grade-evidence-package.v2",
        review_id="review-1",
        protocol_version=protocol.version,
        content_digest="sha256:package",
        files=(ArtifactFile("protocol.json", "sha256:x", 1),),
    )
    expected = TaskWorkResult(TaskWorkStatus.INCOMPLETE, work_id="grade-work-1")
    calls = []
    use_case = ExecuteGradeSummaryOfFindings(
        grade_evidence=type(
            "Port",
            (),
            {"grade": lambda self, inputs, context: calls.append(inputs) or expected},
        )()
    )
    result = use_case.execute(
        TaskInvocation(
            TaskContext("review-1", protocol.version),
            GradeSummaryOfFindingsInput(protocol, package),
            (Provenance("request", "test"),),
        )
    )
    assert result is expected
    assert len(calls) == 1


def test_grade_protocol_accepts_explicit_llm_methodology_fallback(
    protocol: GradeProtocol,
) -> None:
    fallback = replace(
        protocol,
        methodology_basis=(),
        methodology_basis_status=MethodologyBasisStatus.LLM_FALLBACK,
        methodology_fallback_model="openai/gpt-5.6-terra",
        methodology_fallback_note="Official guidance was unavailable and remains unverified.",
    )
    assert fallback.methodology_basis == ()
    assert fallback.methodology_basis_status is MethodologyBasisStatus.LLM_FALLBACK


@pytest.fixture
def protocol() -> GradeProtocol:
    case = ROOT / "benchmark/online_pipeline_v2/GRADE/data/candidates/input/grade_000001"
    return build_grade_protocol(case / "protocol.json", version="protocol-1")


def test_benchmark_materializes_exact_public_package_without_gold(
    tmp_path: Path,
    protocol: GradeProtocol,
) -> None:
    case = ROOT / "benchmark/online_pipeline_v2/GRADE/data/candidates/input/grade_000001"
    store = FileGradeEvidencePackageStore(tmp_path)
    package = persist_grade_evidence_package(
        case,
        store=store,
        package_id="opaque-package",
        review_id="opaque-review",
        protocol_version=protocol.version,
    )
    assert {item.name for item in package.files} == (
        REQUIRED_EVIDENCE_FILES | OPTIONAL_EVIDENCE_FILES
    )
    assert "grade_000001" not in json.dumps(package, default=str)
    assert not any("gold" in item.name.casefold() for item in package.files)


def test_benchmark_preserves_complete_grade_protocol_context(
    protocol: GradeProtocol,
) -> None:
    assert protocol.schema_version == "grade-protocol.v2"
    assert protocol.review_pico.population
    assert protocol.objectives
    assert protocol.eligibility_and_outcomes
    assert protocol.risk_of_bias
    assert protocol.effect_calculation
    assert protocol.synthesis
    assert protocol.reporting_bias
    assert protocol.certainty


def test_estimated_effect_without_interval_requires_an_explicit_reason() -> None:
    with pytest.raises(ValueError, match="requires a reason"):
        EffectPresentation(
            status=EffectStatus.ESTIMATED,
            measure="risk ratio",
            estimate=0.8,
        )
    effect = EffectPresentation(
        status=EffectStatus.ESTIMATED,
        measure="risk ratio",
        estimate=0.8,
        confidence_interval_unavailable_reason="The synthesis did not report one.",
    )
    assert effect.estimate == 0.8


def test_supported_absolute_effect_calculation_is_a_domain_invariant() -> None:
    def effect(value: float) -> EffectPresentation:
        return EffectPresentation(
            status=EffectStatus.ESTIMATED,
            measure="risk per 1000",
            estimate=value,
            confidence_interval_unavailable_reason="No interval supplied in probe.",
        )

    calculation = AbsoluteEffectCalculation(
        measure="RR",
        baseline_risk=0.2,
        effect_estimate=0.5,
        display_scale=1000,
    )
    scenario = AbsoluteEffectScenario(
        label="Typical baseline risk",
        comparator_effect=effect(200),
        intervention_effect=effect(100),
        absolute_difference=effect(-100),
        baseline_basis="Supplied comparator risk.",
        calculation=calculation,
    )
    assert scenario.calculation is calculation
    with pytest.raises(ValueError, match="deterministic calculation"):
        replace(scenario, intervention_effect=effect(101))


def test_grade_rejects_unknown_synthesis_analysis_reference() -> None:
    provenance = (Provenance("analysis-1", "synthesis_analysis"),)
    profile = GradedGRADEAssessmentDraft(
        evidence_body_id="body-1",
        synthesis_analysis_ids=("unknown-analysis",),
        status=EvidenceProfileStatus.GRADED,
        initial_certainty=Certainty.HIGH,
        initial_certainty_basis="Randomized evidence.",
        domains=_judgements(provenance),
        upgrades=_upgrades(),
        explanation="No reasons to downgrade.",
    )
    row = SummaryOfFindingsRowDraft(
        evidence_body_id="body-1",
        outcome="Outcome",
        time_frame="Follow-up",
        relative_effect=None,
        absolute_effects=(),
        study_count=1,
        participant_count=20,
        explanation="One contributing Study.",
    )
    draft = GradeSummaryOfFindingsDraft(
        schema_version="grade-sof-draft.v4",
        evidence_profiles=(profile,),
        summary_of_findings=(
            SummaryOfFindingsTableDraft(
                table_id="table-1",
                population="Population",
                setting=None,
                intervention="Intervention",
                comparison="Comparator",
                rows=(row,),
            ),
        ),
    )
    with pytest.raises(ValueError, match="unknown Synthesis Analysis"):
        finalize_grade_artifact(
            draft,
            known_synthesis_analysis_ids=frozenset({"analysis-1"}),
        )
    bound_profile = replace(
        profile,
        synthesis_analysis_ids=("analysis-1",),
    )
    bound = replace(draft, evidence_profiles=(bound_profile,))
    artifact = finalize_grade_artifact(
        bound,
        known_synthesis_analysis_ids=frozenset({"analysis-1"}),
    )
    assert artifact.summary_of_findings[0].rows[0].study_count == 1


def test_grade_schema_separates_graded_and_no_evidence_profiles() -> None:
    schema = GradeAgentOutput.model_json_schema()
    profile_schema = schema["$defs"]["GradeSummaryOfFindingsDraft"]["properties"][
        "evidence_profiles"
    ]["items"]
    refs = {item["$ref"].rsplit("/", 1)[-1] for item in profile_schema["anyOf"]}
    assert refs == {"GradedGRADEAssessmentDraft", "NoEvidenceGRADEProfileDraft"}
    no_evidence = schema["$defs"]["NoEvidenceGRADEProfileDraft"]
    assert "domains" not in no_evidence["properties"]
    assert "initial_certainty" not in no_evidence["properties"]
    assert "synthesis_analysis_ids" not in no_evidence["properties"]


def test_no_evidence_profile_is_a_valid_completed_sof_row() -> None:
    profile = NoEvidenceGRADEProfileDraft(
        evidence_body_id="body-none",
        status=EvidenceProfileStatus.NO_EVIDENCE,
        explanation="No eligible study reported this outcome.",
        provenance=(),
        issues=(),
    )
    row = SummaryOfFindingsRowDraft(
        evidence_body_id="body-none",
        outcome="Mortality",
        time_frame="At discharge",
        relative_effect=None,
        absolute_effects=(),
        study_count=0,
        participant_count=None,
        explanation="No eligible study reported this outcome.",
    )
    draft = GradeSummaryOfFindingsDraft(
        schema_version="grade-sof-draft.v4",
        evidence_profiles=(profile,),
        summary_of_findings=(
            SummaryOfFindingsTableDraft(
                table_id="table-none",
                population="Population",
                setting=None,
                intervention="Intervention",
                comparison="Comparator",
                rows=(row,),
            ),
        ),
    )
    artifact = finalize_grade_artifact(draft)
    persisted_profile = artifact.evidence_profiles[0]
    assert persisted_profile.status is EvidenceProfileStatus.NO_EVIDENCE
    assert artifact.summary_of_findings[0].rows[0].certainty is None

    invalid_row = replace(row, study_count=1, participant_count=10)
    with pytest.raises(ValueError, match="no-evidence SoF row"):
        finalize_grade_artifact(
            replace(
                draft,
                summary_of_findings=(
                    replace(
                        draft.summary_of_findings[0],
                        rows=(invalid_row,),
                    ),
                ),
            )
        )


def test_grade_package_accepts_semantic_core_without_optional_csvs(
    tmp_path: Path,
) -> None:
    store = FileGradeEvidencePackageStore(tmp_path)
    files = {
        "protocol.json": b"{}\n",
        "search.json": b"{}\n",
        "selection.json": b"{}\n",
        "study-characteristics.jsonl": b"",
        "risk-of-bias.json": b"{}\n",
        "synthesis.json": b'{"analyses": []}\n',
    }
    snapshot = store.persist(
        package_id="semantic-core",
        review_id="review-1",
        protocol_version="protocol-1",
        files=files,
    )
    assert snapshot.package.schema_version == "grade-evidence-package.v2"
    assert {item.name for item in snapshot.package.files} == set(files)
    without_synthesis = dict(files)
    without_synthesis.pop("synthesis.json")
    with pytest.raises(ValueError, match="incomplete or unknown"):
        store.persist(
            package_id="missing-semantic-core",
            review_id="review-1",
            protocol_version="protocol-1",
            files=without_synthesis,
        )


def test_grade_indexes_runtime_synthesis_analysis_identity(
    tmp_path: Path,
) -> None:
    (tmp_path / "synthesis.json").write_text(
        json.dumps(
            {
                "schema_version": "evidence-synthesis-document.v3",
                "analyses": [
                    {
                        "analysis_id": "analysis-1",
                        "contributions": [
                            {"study_id": "study-1", "included": True},
                            {"study_id": "study-2", "included": False},
                        ],
                        "overall_estimates_and_settings": [
                            {"Experimental N": 12, "Control N": 8}
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    assert synthesis_analysis_ids(tmp_path) == frozenset({"analysis-1"})


def test_grade_skill_loads_and_effect_tool_is_deterministic() -> None:
    skill = load_skill(SKILL)
    assert skill.name == "grade-evidence-and-build-sof"
    result = subprocess.run(
        [
            sys.executable,
            str(SKILL / "scripts/sof_effects.py"),
            "--measure",
            "RR",
            "--baseline-risk",
            "0.2",
            "--estimate",
            "0.5",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(result.stdout)["intervention_effect"] == pytest.approx(0.1)


def test_grade_agent_contract_accepts_structured_issues_only() -> None:
    with pytest.raises(ValueError, match="issues"):
        GradeAgentOutput.model_validate(
            {
                "status": "completed",
                "artifact": None,
                "issues": ["missing evidence"],
                "blocker": None,
                "warnings": [],
            }
        )


def test_agent_adapter_allows_methodology_web_and_persists_validated_artifact(
    tmp_path: Path,
    protocol: GradeProtocol,
) -> None:
    case = ROOT / "benchmark/online_pipeline_v2/GRADE/data/candidates/input/grade_000001"
    evidence_store = FileGradeEvidencePackageStore(tmp_path / "evidence")
    package = persist_grade_evidence_package(
        case,
        store=evidence_store,
        package_id="opaque-package",
        review_id="review-1",
        protocol_version=protocol.version,
    )
    runtime = _GradeRuntime()
    artifact_store = FileGradeArtifactStore(tmp_path / "artifact")
    adapter = GradeEvidenceTask(
        executor=_executor(runtime),
        evidence_store=evidence_store,
        artifact_store=artifact_store,
    )
    result = adapter.grade(
        GradeSummaryOfFindingsInput(protocol, package),
        TaskContext("review-1", protocol.version),
    )
    assert result.status is TaskWorkStatus.COMPLETED
    assert result.artifact is not None
    assert result.artifact.schema_version == "grade-sof-artifact.v4"
    assert runtime.request.enable_web_search is True
    assert runtime.request.enable_workspace_network is True
    assert runtime.request.output_artifacts == {}
    assert "grade_000001" not in json.dumps(runtime.request.input_data)
    artifact_store.resolve(result.artifact.artifact_id)


class _GradeRuntime:
    provider = AgentProvider.OPENAI

    async def run(self, request):
        self.request = request
        profile = {
            "evidence_body_id": "body-1",
            "status": "no_evidence",
            "explanation": "No eligible evidence was available.",
            "provenance": [],
            "issues": [
                {
                    "code": "no_eligible_evidence",
                    "message": "No eligible evidence was available.",
                    "severity": "warning",
                    "provenance": [],
                }
            ],
        }
        table = [
            {
                "table_id": "table-1",
                "population": "People who smoke",
                "setting": None,
                "intervention": "Antidepressants",
                "comparison": "Placebo",
                "rows": [
                    {
                        "evidence_body_id": "body-1",
                        "outcome": "Smoking cessation",
                        "time_frame": "At least six months",
                        "relative_effect": None,
                        "absolute_effects": [],
                        "study_count": 0,
                        "participant_count": None,
                        "explanation": "No eligible evidence was available.",
                        "provenance": [],
                    }
                ],
            }
        ]
        return AgentRunResult(
            provider=self.provider,
            model="openai/test-model",
            run_id=request.run_id,
            session_id="session-1",
            output={
                "status": "completed",
                "artifact": {
                    "schema_version": "grade-sof-draft.v4",
                    "method_decisions": [],
                    "evidence_profiles": [profile],
                    "summary_of_findings": table,
                },
                "issues": [],
                "blocker": None,
                "warnings": [],
            },
            events=(),
            stderr="",
            duration_seconds=0.1,
            web_access_audit=WebAccessAudit(True, False, 0, ()),
            skill_snapshots=(
                AgentSkillSnapshot("grade-evidence-and-build-sof", "a" * 64),
            ),
            output_artifacts={},
        )
