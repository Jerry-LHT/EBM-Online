"""Composition root for task-level v2 application use cases."""

from functools import lru_cache
import os
from pathlib import Path
from typing import NoReturn

from ebm_backend.online_pipeline_v2.application.use_cases.evidence_search.execute import (
    ExecuteEvidenceSearch,
)
from ebm_backend.online_pipeline_v2.application.use_cases.evidence_search.search_evidence import (
    SearchEvidence,
)
from ebm_backend.online_pipeline_v2.application.use_cases.q2protocol.draft_protocol import (
    DraftProtocol,
)
from ebm_backend.online_pipeline_v2.application.use_cases.q2protocol.execute import (
    ExecuteQ2Protocol,
)
from ebm_backend.online_pipeline_v2.application.use_cases.risk_of_bias.assess import (
    AssessRiskOfBias,
)
from ebm_backend.online_pipeline_v2.application.use_cases.risk_of_bias.execute import (
    ExecuteRiskOfBias,
)
from ebm_backend.online_pipeline_v2.application.use_cases.review_runs import (
    ReviewRunService,
)
from ebm_backend.online_pipeline_v2.application.use_cases.review_run import (
    ExecuteReviewRun,
)
from ebm_backend.online_pipeline_v2.application.use_cases.study_selection.execute import (
    ExecuteStudySelection,
)
from ebm_backend.online_pipeline_v2.application.use_cases.study_selection.select_studies import (
    SelectStudies,
)
from ebm_backend.online_pipeline_v2.application.use_cases.study_data_collection.collect import (
    ExecuteStudyDataCollection,
)
from ebm_backend.online_pipeline_v2.application.use_cases.evidence_synthesis.execute import (
    ExecuteEvidenceSynthesis,
)
from ebm_backend.online_pipeline_v2.application.use_cases.grade_summary_of_findings.execute import (
    ExecuteGradeSummaryOfFindings,
)
from ebm_backend.online_pipeline_v2.application.use_cases.systematic_review_reporting import (
    ComposeSystematicReview,
)
from ebm_backend.online_pipeline_v2.domain.common import TaskName
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime import (
    build_agent_runtime,
    load_agent_runtime_config,
    load_web_access_policy,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution import (
    build_agent_task_gateway,
    load_skill_tool,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.tasks.evidence_search import (
    SearchEvidenceTask,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.tasks.q2protocol import (
    DraftProtocolTask,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.tasks.risk_of_bias import (
    AssessRiskOfBiasTask,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.tasks.study_selection import (
    SelectStudiesTask,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.tasks.study_data_collection import (
    CollectStudyDataTask,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.tasks.evidence_synthesis import (
    SynthesizeEvidenceTask,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.tasks.grade_summary_of_findings import (
    GradeEvidenceTask,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.tasks.systematic_review_reporting import (
    ComposeSystematicReviewTask,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.packages import (
    FileRiskOfBiasPackageStore,
    FileSearchPackageStore,
    FileSelectionPackageStore,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.work import (
    FileEvidenceSynthesisStore,
    FileGradeArtifactStore,
    FileGradeEvidencePackageStore,
    FileStudyDataCollectionStore,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.review_runs import (
    FileReviewRunStore,
)
from ebm_backend.online_pipeline_v2.infrastructure.background import (
    ThreadReviewRunDispatcher,
)
from ebm_backend.online_pipeline_v2.infrastructure.grade import (
    FileGradeEvidencePackageBuilder,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.systematic_review import (
    FileSystematicReviewArtifactStore,
    FileSystematicReviewEvidencePackageStore,
)
from ebm_backend.online_pipeline_v2.infrastructure.systematic_review import (
    FileSystematicReviewEvidencePackageBuilder,
)
from ebm_backend.online_pipeline_v2.infrastructure.unavailable import (
    TaskExecutorUnavailable,
)

_SKILLS_ROOT = (
    Path(__file__).resolve().parents[2]
    / "infrastructure"
    / "agent_execution"
    / "skills"
)
_TASK_SKILL_PATHS = {
    "q2protocol": _SKILLS_ROOT / "q2protocol" / "draft-q2protocol",
    "evidence_search": _SKILLS_ROOT / "evidence_search" / "evidence-search",
    "study_selection": _SKILLS_ROOT / "study_selection" / "select-studies",
    "study_data_collection": (
        _SKILLS_ROOT / "study_data_collection" / "collect-study-data"
    ),
    "risk_of_bias": _SKILLS_ROOT / "risk_of_bias" / "risk-of-bias",
    "evidence_synthesis": (_SKILLS_ROOT / "evidence_synthesis" / "synthesize-evidence"),
    "grade_summary_of_findings": (
        _SKILLS_ROOT / "grade_summary_of_findings" / "grade-evidence-and-build-sof"
    ),
    "systematic_review_reporting": (
        _SKILLS_ROOT
        / "systematic_review_reporting"
        / "compose-systematic-review"
    ),
}
_REPORT_ACCESS_SKILL_PATH = _SKILLS_ROOT / "shared" / "find-and-read-reports"
_METHODOLOGY_ACCESS_SKILL_PATH = _SKILLS_ROOT / "shared" / "find-and-read-methodology"
_TASK_COMPANION_SKILL_PATHS = {
    task: (
        _METHODOLOGY_ACCESS_SKILL_PATH,
        *(
            (_REPORT_ACCESS_SKILL_PATH,)
            if task
            in {
                "study_selection",
                "study_data_collection",
                "risk_of_bias",
            }
            else ()
        ),
    )
    for task in _TASK_SKILL_PATHS
}


def _configured_skill_paths_by_task() -> dict[str, tuple[Path, ...]]:
    return {
        task: (path, *_TASK_COMPANION_SKILL_PATHS.get(task, ()))
        for task, path in _TASK_SKILL_PATHS.items()
    }


@lru_cache(maxsize=1)
def _agent_gateway():
    runtime = build_agent_runtime(load_agent_runtime_config())
    return build_agent_task_gateway(
        runtime=runtime,
        skill_paths_by_task=_configured_skill_paths_by_task(),
    )


def _unavailable(task: TaskName) -> NoReturn:
    raise TaskExecutorUnavailable(task)


@lru_cache(maxsize=1)
def get_q2protocol_use_case() -> ExecuteQ2Protocol:
    if os.getenv("ENABLE_Q2PROTOCOL_AGENT") != "1":
        return _unavailable(TaskName.Q2PROTOCOL)
    policy = load_web_access_policy()
    gateway = _agent_gateway()
    adapter = DraftProtocolTask(
        executor=gateway,
        web_access_policy=policy,
    )
    return ExecuteQ2Protocol(draft_protocol=DraftProtocol(port=adapter))


@lru_cache(maxsize=1)
def get_evidence_search_use_case():
    if os.getenv("ENABLE_EVIDENCE_SEARCH_AGENT") != "1":
        return _unavailable(TaskName.EVIDENCE_SEARCH)
    policy = load_web_access_policy()
    gateway = _agent_gateway()
    adapter = SearchEvidenceTask(
        executor=gateway,
        package_store=FileSearchPackageStore(
            Path(os.getenv("SEARCH_PACKAGE_ROOT", ".search-packages"))
        ),
        web_access_policy=policy,
    )
    return ExecuteEvidenceSearch(search_evidence=SearchEvidence(port=adapter))


@lru_cache(maxsize=1)
def get_study_selection_use_case() -> ExecuteStudySelection:
    if os.getenv("ENABLE_STUDY_SELECTION_AGENT") != "1":
        return _unavailable(TaskName.STUDY_SELECTION)
    policy = load_web_access_policy()
    gateway = _agent_gateway()
    search_root = Path(os.getenv("SEARCH_PACKAGE_ROOT", ".search-packages"))
    selection_root = Path(os.getenv("SELECTION_PACKAGE_ROOT", ".selection-packages"))
    adapter = SelectStudiesTask(
        executor=gateway,
        search_package_store=FileSearchPackageStore(search_root),
        selection_package_store=FileSelectionPackageStore(selection_root),
        web_access_policy=policy,
    )
    return ExecuteStudySelection(select_studies=SelectStudies(port=adapter))


@lru_cache(maxsize=1)
def get_study_data_collection_use_case() -> ExecuteStudyDataCollection:
    if os.getenv("ENABLE_STUDY_DATA_COLLECTION_AGENT") != "1":
        return _unavailable(TaskName.STUDY_DATA_COLLECTION)
    policy = load_web_access_policy()
    gateway = _agent_gateway()
    skill_path = _TASK_SKILL_PATHS["study_data_collection"]
    calculate = load_skill_tool(
        skill_path,
        "scripts/data_calculator.py",
        "calculate",
    )
    adapter = CollectStudyDataTask(
        executor=gateway,
        selection_package_store=FileSelectionPackageStore(
            Path(os.getenv("SELECTION_PACKAGE_ROOT", ".selection-packages"))
        ),
        data_collection_store=FileStudyDataCollectionStore(
            Path(os.getenv("STUDY_DATA_COLLECTION_ROOT", ".study-data-collection")),
            calculate,
        ),
        calculate=calculate,
        web_access_policy=policy,
    )
    return ExecuteStudyDataCollection(collect_study_data=adapter)


@lru_cache(maxsize=1)
def get_risk_of_bias_use_case() -> ExecuteRiskOfBias:
    if os.getenv("ENABLE_RISK_OF_BIAS_AGENT") != "1":
        return _unavailable(TaskName.RISK_OF_BIAS)
    policy = load_web_access_policy()
    gateway = _agent_gateway()
    selection_root = Path(os.getenv("SELECTION_PACKAGE_ROOT", ".selection-packages"))
    risk_of_bias_root = Path(
        os.getenv("RISK_OF_BIAS_PACKAGE_ROOT", ".risk-of-bias-packages")
    )
    calculate = load_skill_tool(
        _TASK_SKILL_PATHS["study_data_collection"],
        "scripts/data_calculator.py",
        "calculate",
    )
    adapter = AssessRiskOfBiasTask(
        executor=gateway,
        selection_package_store=FileSelectionPackageStore(selection_root),
        study_data_collection_store=FileStudyDataCollectionStore(
            Path(
                os.getenv(
                    "STUDY_DATA_COLLECTION_ROOT",
                    ".study-data-collection",
                )
            ),
            calculate,
        ),
        risk_of_bias_package_store=FileRiskOfBiasPackageStore(risk_of_bias_root),
        web_access_policy=policy,
    )
    return ExecuteRiskOfBias(assess_risk_of_bias=AssessRiskOfBias(port=adapter))


@lru_cache(maxsize=1)
def get_evidence_synthesis_use_case() -> ExecuteEvidenceSynthesis:
    if os.getenv("ENABLE_EVIDENCE_SYNTHESIS_AGENT") != "1":
        return _unavailable(TaskName.EVIDENCE_SYNTHESIS)
    policy = load_web_access_policy()
    gateway = _agent_gateway()
    data_collection_root = Path(
        os.getenv("STUDY_DATA_COLLECTION_ROOT", ".study-data-collection")
    )
    synthesis_root = Path(os.getenv("EVIDENCE_SYNTHESIS_ROOT", ".evidence-synthesis"))
    data_skill_path = _TASK_SKILL_PATHS["study_data_collection"]
    synthesis_skill_path = _TASK_SKILL_PATHS["evidence_synthesis"]
    calculate_result = load_skill_tool(
        data_skill_path,
        "scripts/data_calculator.py",
        "calculate",
    )
    compute_meta_analysis = load_skill_tool(
        synthesis_skill_path,
        "scripts/meta_compute.py",
        "compute_meta_analysis",
    )
    calculate_scalar = load_skill_tool(
        synthesis_skill_path,
        "scripts/scalar_calculate.py",
        "calculate",
    )
    adapter = SynthesizeEvidenceTask(
        executor=gateway,
        data_collection_store=FileStudyDataCollectionStore(
            data_collection_root,
            calculate_result,
        ),
        synthesis_store=FileEvidenceSynthesisStore(
            synthesis_root,
            compute_meta_analysis,
            calculate_scalar,
        ),
        compute_meta_analysis=compute_meta_analysis,
        calculate_scalar=calculate_scalar,
        web_access_policy=policy,
    )
    return ExecuteEvidenceSynthesis(synthesize_evidence=adapter)


@lru_cache(maxsize=1)
def get_grade_summary_of_findings_use_case() -> ExecuteGradeSummaryOfFindings:
    if os.getenv("ENABLE_GRADE_AGENT") != "1":
        return _unavailable(TaskName.GRADE_SUMMARY_OF_FINDINGS)
    policy = load_web_access_policy()
    gateway = _agent_gateway()
    evidence_root = Path(
        os.getenv("GRADE_EVIDENCE_PACKAGE_ROOT", ".grade-evidence-packages")
    )
    artifact_root = Path(os.getenv("GRADE_ARTIFACT_ROOT", ".grade-artifacts"))
    adapter = GradeEvidenceTask(
        executor=gateway,
        evidence_store=FileGradeEvidencePackageStore(evidence_root),
        artifact_store=FileGradeArtifactStore(artifact_root),
        web_access_policy=policy,
    )
    return ExecuteGradeSummaryOfFindings(grade_evidence=adapter)


@lru_cache(maxsize=1)
def get_systematic_review_reporting_use_case() -> ComposeSystematicReview:
    if os.getenv("ENABLE_SYSTEMATIC_REVIEW_AGENT") != "1":
        return _unavailable(TaskName.SYSTEMATIC_REVIEW_REPORTING)
    policy = load_web_access_policy()
    adapter = ComposeSystematicReviewTask(
        executor=_agent_gateway(),
        evidence_store=FileSystematicReviewEvidencePackageStore(
            Path(
                os.getenv(
                    "SYSTEMATIC_REVIEW_EVIDENCE_ROOT",
                    ".systematic-review-evidence",
                )
            )
        ),
        artifact_store=FileSystematicReviewArtifactStore(
            Path(os.getenv("SYSTEMATIC_REVIEW_ROOT", ".systematic-reviews"))
        ),
        web_access_policy=policy,
    )
    return ComposeSystematicReview(composer=adapter)


@lru_cache(maxsize=1)
def get_review_run_service() -> ReviewRunService:
    synthesis_root = Path(os.getenv("EVIDENCE_SYNTHESIS_ROOT", ".evidence-synthesis"))
    selection_root = Path(os.getenv("SELECTION_PACKAGE_ROOT", ".selection-packages"))
    data_collection_root = Path(
        os.getenv("STUDY_DATA_COLLECTION_ROOT", ".study-data-collection")
    )
    grade_evidence_root = Path(
        os.getenv("GRADE_EVIDENCE_PACKAGE_ROOT", ".grade-evidence-packages")
    )
    grade_artifact_root = Path(os.getenv("GRADE_ARTIFACT_ROOT", ".grade-artifacts"))
    systematic_review_evidence_store = FileSystematicReviewEvidencePackageStore(
        Path(
            os.getenv(
                "SYSTEMATIC_REVIEW_EVIDENCE_ROOT",
                ".systematic-review-evidence",
            )
        )
    )
    compute_meta_analysis = load_skill_tool(
        _TASK_SKILL_PATHS["evidence_synthesis"],
        "scripts/meta_compute.py",
        "compute_meta_analysis",
    )
    calculate_scalar = load_skill_tool(
        _TASK_SKILL_PATHS["evidence_synthesis"],
        "scripts/scalar_calculate.py",
        "calculate",
    )
    review_store = FileReviewRunStore(
        Path(os.getenv("REVIEW_RUN_STORE_PATH", ".review-runs"))
    )
    review_store.mark_interrupted()
    calculate_data = load_skill_tool(
        _TASK_SKILL_PATHS["study_data_collection"],
        "scripts/data_calculator.py",
        "calculate",
    )
    data_collection_store = FileStudyDataCollectionStore(
        data_collection_root,
        calculate_data,
    )
    executor = ExecuteReviewRun(
        q2protocol=get_q2protocol_use_case,
        evidence_search=get_evidence_search_use_case,
        study_selection=get_study_selection_use_case,
        study_data_collection=get_study_data_collection_use_case,
        risk_of_bias=get_risk_of_bias_use_case,
        evidence_synthesis=get_evidence_synthesis_use_case,
        grade=get_grade_summary_of_findings_use_case,
        systematic_review_reporting=get_systematic_review_reporting_use_case,
        data_collection_repository=data_collection_store,
        grade_evidence_package_builder=FileGradeEvidencePackageBuilder(
            data_collection_store=data_collection_store,
            synthesis_store=FileEvidenceSynthesisStore(
                synthesis_root,
                compute_meta_analysis,
                calculate_scalar,
            ),
            grade_evidence_store=FileGradeEvidencePackageStore(grade_evidence_root),
            selection_store=FileSelectionPackageStore(selection_root),
        ),
        systematic_review_evidence_package_builder=(
            FileSystematicReviewEvidencePackageBuilder(
                data_collection_store=data_collection_store,
                synthesis_store=FileEvidenceSynthesisStore(
                    synthesis_root,
                    compute_meta_analysis,
                    calculate_scalar,
                ),
                grade_artifact_store=FileGradeArtifactStore(grade_artifact_root),
                evidence_store=systematic_review_evidence_store,
                selection_store=FileSelectionPackageStore(selection_root),
            )
        ),
    )
    return ReviewRunService(repository=review_store, executor=executor)


@lru_cache(maxsize=1)
def get_review_run_dispatcher() -> ThreadReviewRunDispatcher:
    return ThreadReviewRunDispatcher(get_review_run_service().run)
