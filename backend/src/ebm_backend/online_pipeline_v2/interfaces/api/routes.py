"""HTTP routes for independent professional tasks."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactStatus,
    DomainValidationError,
    TaskContext,
    TaskInvocation,
    TaskName,
    TaskWorkStatus,
)
from ebm_backend.online_pipeline_v2.domain.grade import GradeSummaryOfFindingsInput
from ebm_backend.online_pipeline_v2.domain.protocol import Q2ProtocolInput
from ebm_backend.online_pipeline_v2.domain.risk_of_bias import RiskOfBiasInput
from ebm_backend.online_pipeline_v2.domain.search import (
    EvidenceSearchInput,
    public_search_artifact,
)
from ebm_backend.online_pipeline_v2.domain.selection import StudySelectionInput
from ebm_backend.online_pipeline_v2.domain.study_data_collection import (
    StudyDataCollectionInput,
)
from ebm_backend.online_pipeline_v2.domain.synthesis import EvidenceSynthesisInput
from ebm_backend.online_pipeline_v2.domain.systematic_review import (
    SystematicReviewReportingInput,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_execution.contracts import (
    TaskExecutionError,
    TaskOutputError,
)
from ebm_backend.online_pipeline_v2.infrastructure.agent_runtime.errors import (
    AgentConfigurationError,
    AgentProcessTimeoutError,
    AgentRuntimeError,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.work import (
    WorkBindingConflict,
    WorkExecutionConflict,
)
from ebm_backend.online_pipeline_v2.infrastructure.unavailable import (
    TaskExecutorUnavailable,
)
from ebm_backend.online_pipeline_v2.interfaces.api import dependencies
from ebm_backend.online_pipeline_v2.interfaces.api.schemas import (
    EvidenceSearchRequest,
    EvidenceSearchResponse,
    EvidenceSynthesisRequest,
    GradeSummaryOfFindingsRequest,
    Q2ProtocolRequest,
    Q2ProtocolResponse,
    RiskOfBiasRequest,
    RiskOfBiasResponse,
    StudyDataCollectionRequest,
    StudySelectionRequest,
    StudySelectionResponse,
    SystematicReviewReportingRequest,
    TaskRequest,
    TaskWorkResponse,
    UpstreamArtifact,
)


router = APIRouter(prefix="/v2/tasks", tags=["v2 tasks"])


def _context(request: TaskRequest) -> TaskContext:
    return TaskContext(
        review_id=request.review_id,
        protocol_version=request.protocol_version,
    )


def _validate_upstream(
    request: TaskRequest,
    artifact: UpstreamArtifact[Any],
    expected_task: TaskName,
    *,
    require_completed: bool = False,
) -> None:
    if artifact.review_id != request.review_id:
        raise DomainValidationError("upstream artifact review_id does not match")
    if artifact.protocol_version != request.protocol_version:
        raise DomainValidationError("upstream artifact protocol_version does not match")
    if artifact.task is not expected_task:
        raise DomainValidationError(
            f"expected {expected_task.value} artifact, got {artifact.task.value}"
        )
    if artifact.status is ArtifactStatus.BLOCKED or artifact.data is None:
        raise DomainValidationError(f"{expected_task.value} artifact is not usable")
    if require_completed and artifact.status is not ArtifactStatus.COMPLETED:
        raise DomainValidationError(f"{expected_task.value} artifact must be completed")


def _get_use_case(factory, task: TaskName):
    try:
        return factory()
    except TaskExecutorUnavailable as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "task_executor_unavailable",
                "task": task.value,
                "execution_status": "configuration_error",
                "message": "No executor adapter is configured for this v2 task.",
            },
        ) from exc
    except (AgentConfigurationError, ValueError) as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "task_executor_configuration_error",
                "task": task.value,
                "execution_status": "configuration_error",
                "message": str(exc),
            },
        ) from exc


def _execute(use_case, invocation):
    try:
        return use_case.execute(invocation)
    except DomainValidationError as exc:
        raise HTTPException(
            status_code=400,
            detail={"code": "invalid_task_input", "message": str(exc)},
        ) from exc
    except AgentProcessTimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail={
                "code": "agent_timeout",
                "execution_status": "timed_out",
                "message": str(exc),
            },
        ) from exc
    except TaskOutputError as exc:
        raise _artifact_invalid(exc) from exc
    except (AgentRuntimeError, TaskExecutionError) as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "agent_runtime_error",
                "execution_status": "failed",
                "message": str(exc),
            },
        ) from exc


def _execute_work(use_case, invocation) -> JSONResponse:
    try:
        result = use_case.execute(invocation)
    except WorkExecutionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "work_execution_conflict", "message": str(exc)},
        ) from exc
    except WorkBindingConflict as exc:
        raise HTTPException(
            status_code=409,
            detail={"code": "work_binding_conflict", "message": str(exc)},
        ) from exc
    except (DomainValidationError, ValueError) as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_task_input", "message": str(exc)},
        ) from exc
    except AgentProcessTimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail={
                "code": "agent_timeout",
                "execution_status": "timed_out",
                "message": str(exc),
            },
        ) from exc
    except TaskOutputError as exc:
        raise _artifact_invalid(exc) from exc
    except (AgentRuntimeError, TaskExecutionError) as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "agent_runtime_error",
                "execution_status": "failed",
                "message": str(exc),
            },
        ) from exc
    status_code = {
        TaskWorkStatus.COMPLETED: 200,
        TaskWorkStatus.INCOMPLETE: 202,
        TaskWorkStatus.BLOCKED: 409,
    }[result.status]
    payload = TaskWorkResponse.model_validate(result).model_dump(mode="json")
    return JSONResponse(status_code=status_code, content=payload)


def _artifact_invalid(error: TaskOutputError) -> HTTPException:
    return HTTPException(
        status_code=502,
        detail={
            "code": "agent_artifact_invalid",
            "execution_status": "completed",
            **error.diagnostic(),
        },
    )


def _bad_request(exc: DomainValidationError) -> HTTPException:
    return HTTPException(
        status_code=400,
        detail={"code": "invalid_task_input", "message": str(exc)},
    )


@router.post("/q2protocol", response_model=Q2ProtocolResponse)
def q2protocol(request: Q2ProtocolRequest) -> Q2ProtocolResponse:
    use_case = _get_use_case(
        dependencies.get_q2protocol_use_case,
        TaskName.Q2PROTOCOL,
    )
    invocation = TaskInvocation(
        context=_context(request),
        inputs=Q2ProtocolInput(
            topic_text=request.topic_text,
            topic_kind=request.topic_kind,
            scope_notes=request.scope_notes,
            background_sources=request.background_sources,
            standards=request.standards,
            template=request.template,
        ),
        provenance=request.provenance,
    )
    return _execute(use_case, invocation)


@router.post("/evidence-search", response_model=EvidenceSearchResponse)
def evidence_search(request: EvidenceSearchRequest) -> EvidenceSearchResponse:
    try:
        _validate_upstream(request, request.protocol, TaskName.Q2PROTOCOL)
    except DomainValidationError as exc:
        raise _bad_request(exc) from exc
    use_case = _get_use_case(
        dependencies.get_evidence_search_use_case,
        TaskName.EVIDENCE_SEARCH,
    )
    invocation = TaskInvocation(
        context=_context(request),
        inputs=EvidenceSearchInput(protocol=request.protocol.data),
        provenance=request.provenance,
    )
    result = _execute(use_case, invocation)
    return EvidenceSearchResponse(
        artifact_id=result.artifact_id,
        schema_version=result.schema_version,
        review_id=result.review_id,
        protocol_version=result.protocol_version,
        task=result.task,
        status=result.status,
        data=(public_search_artifact(result.data) if result.data is not None else None),
        provenance=result.provenance,
        issues=result.issues,
        content_digest=result.content_digest,
        upstream_artifacts=result.upstream_artifacts,
    )


@router.post("/study-selection", response_model=StudySelectionResponse)
def study_selection(request: StudySelectionRequest) -> StudySelectionResponse:
    try:
        _validate_upstream(request, request.search, TaskName.EVIDENCE_SEARCH)
    except DomainValidationError as exc:
        raise _bad_request(exc) from exc
    use_case = _get_use_case(
        dependencies.get_study_selection_use_case,
        TaskName.STUDY_SELECTION,
    )
    invocation = TaskInvocation(
        context=_context(request),
        inputs=StudySelectionInput(
            protocol=request.protocol,
            search=request.search.data,
        ),
        provenance=request.provenance,
    )
    return _execute(use_case, invocation)


@router.post(
    "/study-data-collection",
    response_model=TaskWorkResponse,
    responses={
        202: {"model": TaskWorkResponse},
        409: {"model": TaskWorkResponse},
    },
)
def study_data_collection(request: StudyDataCollectionRequest) -> JSONResponse:
    try:
        if request.protocol_context.version != request.protocol_version:
            raise DomainValidationError(
                "Study Data Collection Protocol version does not match request"
            )
        _validate_upstream(
            request,
            request.selection,
            TaskName.STUDY_SELECTION,
            require_completed=True,
        )
        if request.selection.data is None:
            raise DomainValidationError("Study Data Collection requires Selection data")
        if (
            request.selection.data.package_ref.protocol_version
            != request.protocol_version
        ):
            raise DomainValidationError(
                "Selection Package Protocol version does not match"
            )
    except DomainValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_task_input", "message": str(exc)},
        ) from exc
    use_case = _get_use_case(
        dependencies.get_study_data_collection_use_case,
        TaskName.STUDY_DATA_COLLECTION,
    )
    return _execute_work(
        use_case,
        TaskInvocation(
            context=_context(request),
            inputs=StudyDataCollectionInput(
                protocol=request.protocol_context,
                selection=request.selection.data,
            ),
            provenance=request.provenance,
        ),
    )


@router.post("/risk-of-bias", response_model=RiskOfBiasResponse)
def risk_of_bias(request: RiskOfBiasRequest) -> RiskOfBiasResponse:
    try:
        _validate_upstream(
            request,
            request.protocol,
            TaskName.Q2PROTOCOL,
            require_completed=True,
        )
        _validate_upstream(
            request,
            request.selection,
            TaskName.STUDY_SELECTION,
            require_completed=True,
        )
        collection = request.study_data_collection
        if collection.review_id != request.review_id:
            raise DomainValidationError(
                "Study Data Collection review_id does not match"
            )
        if collection.protocol_version != request.protocol_version:
            raise DomainValidationError(
                "Study Data Collection protocol_version does not match"
            )
        if collection.task is not TaskName.STUDY_DATA_COLLECTION:
            raise DomainValidationError(
                "Risk of Bias requires a Study Data Collection artifact"
            )
    except DomainValidationError as exc:
        raise _bad_request(exc) from exc
    use_case = _get_use_case(
        dependencies.get_risk_of_bias_use_case,
        TaskName.RISK_OF_BIAS,
    )
    invocation = TaskInvocation(
        context=_context(request),
        inputs=RiskOfBiasInput(
            protocol=request.protocol.data,
            selection=request.selection.data,
            study_data_collection=request.study_data_collection,
        ),
        provenance=request.provenance,
    )
    return _execute(use_case, invocation)


@router.post(
    "/evidence-synthesis",
    response_model=TaskWorkResponse,
    responses={
        202: {"model": TaskWorkResponse},
        409: {"model": TaskWorkResponse},
    },
)
def evidence_synthesis(request: EvidenceSynthesisRequest) -> JSONResponse:
    try:
        if request.protocol_context.version != request.protocol_version:
            raise DomainValidationError(
                "Evidence Synthesis Protocol context version does not match request"
            )
        _validate_upstream(
            request,
            request.risk_of_bias,
            TaskName.RISK_OF_BIAS,
            require_completed=False,
        )
        if request.risk_of_bias.data is None:
            raise DomainValidationError(
                "Evidence Synthesis requires non-blocked Risk of Bias evidence"
            )
        if request.study_data_collection.review_id != request.review_id:
            raise DomainValidationError(
                "Study Data Collection review_id does not match request"
            )
        if request.study_data_collection.protocol_version != request.protocol_version:
            raise DomainValidationError(
                "Study Data Collection Protocol version does not match request"
            )
        if request.study_data_collection.task is not TaskName.STUDY_DATA_COLLECTION:
            raise DomainValidationError(
                "Evidence Synthesis requires a Study Data Collection artifact"
            )
        if (
            request.study_data_collection.schema_version
            != "study-data-collection-artifact.v3"
        ):
            raise DomainValidationError(
                "Evidence Synthesis requires Study Data Collection artifact v3"
            )
    except DomainValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_task_input", "message": str(exc)},
        ) from exc
    use_case = _get_use_case(
        dependencies.get_evidence_synthesis_use_case,
        TaskName.EVIDENCE_SYNTHESIS,
    )
    return _execute_work(
        use_case,
        TaskInvocation(
            context=_context(request),
            inputs=EvidenceSynthesisInput(
                protocol=request.protocol_context,
                study_data_collection=request.study_data_collection,
                risk_of_bias=request.risk_of_bias.data,
                work_id=request.work_id,
            ),
            provenance=request.provenance,
        ),
    )


@router.post(
    "/grade-summary-of-findings",
    response_model=TaskWorkResponse,
    responses={
        202: {"model": TaskWorkResponse},
        409: {"model": TaskWorkResponse},
    },
)
def grade_summary_of_findings(
    request: GradeSummaryOfFindingsRequest,
) -> JSONResponse:
    try:
        if request.protocol_context.version != request.protocol_version:
            raise DomainValidationError(
                "GRADE Protocol context version does not match request"
            )
        if request.evidence_package.review_id != request.review_id:
            raise DomainValidationError(
                "GRADE evidence package review_id does not match request"
            )
        if request.evidence_package.protocol_version != request.protocol_version:
            raise DomainValidationError(
                "GRADE evidence package Protocol version does not match request"
            )
    except DomainValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_task_input", "message": str(exc)},
        ) from exc
    use_case = _get_use_case(
        dependencies.get_grade_summary_of_findings_use_case,
        TaskName.GRADE_SUMMARY_OF_FINDINGS,
    )
    invocation = TaskInvocation(
        context=_context(request),
        inputs=GradeSummaryOfFindingsInput(
            protocol=request.protocol_context,
            evidence_package=request.evidence_package,
        ),
        provenance=request.provenance,
    )
    return _execute_work(use_case, invocation)


@router.post(
    "/systematic-review-reporting",
    response_model=TaskWorkResponse,
    responses={
        202: {"model": TaskWorkResponse},
        409: {"model": TaskWorkResponse},
    },
)
def systematic_review_reporting(
    request: SystematicReviewReportingRequest,
) -> JSONResponse:
    try:
        if request.protocol.version != request.protocol_version:
            raise DomainValidationError(
                "Reporting Protocol version does not match request"
            )
        if request.evidence_package.review_id != request.review_id:
            raise DomainValidationError(
                "Systematic Review evidence package review_id does not match request"
            )
        if request.evidence_package.protocol_version != request.protocol_version:
            raise DomainValidationError(
                "Systematic Review evidence package Protocol version does not match request"
            )
    except DomainValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"code": "invalid_task_input", "message": str(exc)},
        ) from exc
    use_case = _get_use_case(
        dependencies.get_systematic_review_reporting_use_case,
        TaskName.SYSTEMATIC_REVIEW_REPORTING,
    )
    return _execute_work(
        use_case,
        TaskInvocation(
            context=_context(request),
            inputs=SystematicReviewReportingInput(
                protocol=request.protocol,
                evidence_package=request.evidence_package,
            ),
            provenance=request.provenance,
        ),
    )
