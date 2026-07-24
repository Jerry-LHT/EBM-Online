"""Module-level API routes."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, HTTPException

from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.meta_analysis import MetaAnalysisResultPackage
from ebm_backend.online_pipeline.domain.module_config import ModuleRunConfig
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.risk_of_bias import (
    RiskOfBiasAssessment,
    RiskOfBiasDomainConfig,
)
from ebm_backend.online_pipeline.domain.screening import ScreeningCriteria, ScreeningPolicy
from ebm_backend.online_pipeline.domain.serialization import from_jsonable, to_jsonable
from ebm_backend.online_pipeline.domain.study_characteristics import StudyPIOCharacteristics
from ebm_backend.online_pipeline.application.use_cases.run_study_pio import (
    StudyPIOArticleContentMissingError,
)
from ebm_backend.online_pipeline.application.use_cases.run_risk_of_bias import (
    RiskOfBiasArticleContentMissingError,
)
from ebm_backend.online_pipeline.interfaces.api.dependencies import (
    get_grade_use_case_for_api,
    get_meta_analysis_use_case_for_api,
    get_q2pico_use_case_for_api,
    get_risk_of_bias_use_case_for_api,
    get_search_retrieval_use_case_for_api,
    get_study_pio_use_case_for_api,
    get_study_screening_use_case_for_api,
)
from ebm_backend.online_pipeline.interfaces.api.request_schemas import (
    GradeAssessmentRequest,
    MetaAnalysisRequest,
    Q2PICORequest,
    RiskOfBiasRequest,
    SearchRetrievalRequest,
    StudyPIOExtractionRequest,
    StudyScreeningRequest,
)
from ebm_backend.online_pipeline.infrastructure.methods.q2pico.errors import (
    Q2PICOConfigurationError,
    Q2PICOInvocationError,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.errors import (
    SearchRetrievalStageError,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.errors import (
    StudyScreeningConfigurationError,
    StudyScreeningInvocationError,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_pio.errors import (
    StudyPIOConfigurationError,
    StudyPIOInvocationError,
)
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.errors import (
    RiskOfBiasConfigurationError,
    RiskOfBiasDomainInvocationError,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.risk_of_bias.method_evidence_body_llm.errors import (
    GRADERiskOfBiasConfigurationError,
    GRADERiskOfBiasInvocationError,
    GRADERiskOfBiasJudgementError,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.method_policy_deterministic.errors import (
    GRADEInconsistencyConfigurationError,
    GRADEInconsistencyInvocationError,
    GRADEInconsistencyJudgementError,
    GRADEInconsistencyPolicyError,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.indirectness.method_staged_applicability.errors import (
    GRADEIndirectnessClassificationError,
    GRADEIndirectnessConfigurationError,
    GRADEIndirectnessInvocationError,
    GRADEIndirectnessJudgementError,
    GRADEIndirectnessThresholdError,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_expert_threshold_ci.errors import (
    GRADEImprecisionConfigurationError,
    GRADEImprecisionInvocationError,
    GRADEImprecisionThresholdError,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.errors import (
    MetaAnalysisConfigurationError,
    MetaAnalysisInvocationError,
    MetaAnalysisOutputError,
)


router = APIRouter(prefix="/modules", tags=["modules"])

T = TypeVar("T")


@router.post("/q2pico")
def run_q2pico(payload: Q2PICORequest) -> dict[str, object]:
    question_text = payload.question_text.strip()
    use_case = get_q2pico_use_case_for_api()
    result = _run_q2pico_module(
        lambda: use_case.execute(question_text=question_text, expand_outcomes=payload.expand_outcomes)
    )
    return to_jsonable(result)


@router.post("/search-retrieval")
def run_search_retrieval(payload: SearchRetrievalRequest) -> dict[str, object]:
    def action():
        question_pico = _parse_required(
            payload.question_pico,
            "question_pico",
            QuestionPICO,
        )
        config = ModuleRunConfig(
            max_candidates_per_source=payload.max_candidates_per_source,
            max_results_per_source=payload.max_results_per_source,
            constraints=WorkflowConstraints(
                study_design="RCT" if payload.rct_filter_enabled else "",
            ),
        )
        use_case = get_search_retrieval_use_case_for_api(
            source_names=payload.source_names,
        )
        return use_case.execute(
            question_pico=question_pico,
            config=config,
        )

    result = _run_search_retrieval_module(action)
    return to_jsonable(result)


@router.post("/study-screening")
def run_study_screening(payload: StudyScreeningRequest) -> dict[str, object]:
    def action():
        question_pico = _parse_required(
            payload.question_pico,
            "question_pico",
            QuestionPICO,
        )
        articles = _parse_required_list(payload.articles, "articles", CleanedArticle)
        year_start, year_end = _screening_year_bounds(payload)
        use_case = get_study_screening_use_case_for_api(
            evidence_scope=payload.evidence_scope,
        )
        return use_case.execute(
            question_text=payload.question_text.strip(),
            question_pico=question_pico,
            constraints=WorkflowConstraints(
                study_design="RCT" if payload.rct_only else "",
                publication_year_range=(
                    f"{year_start}-{year_end}"
                    if year_start is not None and year_end is not None
                    else None
                ),
            ),
            articles=articles,
            policy=ScreeningPolicy(
                rct_only=payload.rct_only,
                report_scope=payload.report_scope,
                outcome_eligibility_enabled=payload.outcome_eligibility_enabled,
                publication_year_start=year_start,
                publication_year_end=year_end,
                allowed_languages=list(payload.allowed_languages),
                exclude_retracted=payload.exclude_retracted,
            ),
        )

    result = _run_study_screening_module(action)
    return to_jsonable(result)


@router.post("/study-pio-extraction")
def run_study_pio_extraction(payload: StudyPIOExtractionRequest) -> dict[str, object]:
    def action():
        question_pico = _parse_required(
            payload.question_pico,
            "question_pico",
            QuestionPICO,
        )
        included_studies = _required_text_list(
            payload.included_studies,
            "included_studies",
        )
        articles = _parse_required_list(payload.articles, "articles", CleanedArticle)
        use_case = get_study_pio_use_case_for_api()
        return use_case.execute(
            question_pico=question_pico,
            included_studies=included_studies,
            articles=articles,
        )

    result = _run_study_pio_module(action)
    return to_jsonable(result)


@router.post("/risk-of-bias")
def run_risk_of_bias(payload: RiskOfBiasRequest) -> dict[str, object]:
    def action():
        included_studies = _required_text_list(
            payload.included_studies,
            "included_studies",
        )
        articles = _parse_required_list(payload.articles, "articles", CleanedArticle)
        domain_config = RiskOfBiasDomainConfig(
            assessed_domains=list(payload.domain_config.assessed_domains),
            overall_key_domains=list(payload.domain_config.overall_key_domains),
        )
        use_case = get_risk_of_bias_use_case_for_api()
        return use_case.execute(
            included_studies=included_studies,
            articles=articles,
            domain_config=domain_config,
        )

    result = _run_risk_of_bias_module(action)
    return to_jsonable(result)


@router.post("/meta-analysis")
def run_meta_analysis(payload: MetaAnalysisRequest) -> dict[str, object]:
    def action():
        review_id = payload.review_id.strip()
        question_text = payload.question_text.strip()
        question_pico = _parse_required(
            payload.question_pico,
            "question_pico",
            QuestionPICO,
        )
        screening_criteria = _parse_required(
            payload.screening_criteria,
            "screening_criteria",
            ScreeningCriteria,
        )
        included_studies = _required_text_list(
            payload.included_studies,
            "included_studies",
        )
        articles = _parse_required_list(payload.articles, "articles", CleanedArticle)
        return get_meta_analysis_use_case_for_api().execute(
            review_id=review_id,
            question_text=question_text,
            question_pico=question_pico,
            screening_criteria=screening_criteria,
            included_studies=included_studies,
            articles=articles,
        )

    result = _run_meta_analysis_module(action)
    return to_jsonable(result)


@router.post("/grade-assessment")
def run_grade_assessment(payload: GradeAssessmentRequest) -> dict[str, object]:
    review_id = payload.review_id.strip()
    question_text = payload.question_text.strip()
    question_pico = _parse_required(payload.question_pico, "question_pico", QuestionPICO)
    screening_criteria = _parse_required(payload.screening_criteria, "screening_criteria", ScreeningCriteria)
    study_characteristics = _parse_required_list(payload.study_characteristics, "study_characteristics", StudyPIOCharacteristics)
    risk_of_bias = _parse_required_list(payload.risk_of_bias, "risk_of_bias", RiskOfBiasAssessment)
    meta_analysis_result = _parse_required(payload.meta_analysis_result, "meta_analysis_result", MetaAnalysisResultPackage)
    result = _run_grade_module(
        lambda: get_grade_use_case_for_api().execute(
            review_id=review_id,
            question_text=question_text,
            question_pico=question_pico,
            screening_criteria=screening_criteria,
            study_characteristics=study_characteristics,
            risk_of_bias=risk_of_bias,
            meta_analysis_result=meta_analysis_result,
        )
    )
    return to_jsonable(result)


def _run_module(action: Callable[[], T]) -> T:
    try:
        return action()
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _run_meta_analysis_module(action: Callable[[], T]) -> T:
    try:
        return _run_module(action)
    except MetaAnalysisConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "meta_analysis_configuration_unavailable",
                "stage": exc.stage,
                "message": "Meta-analysis is unavailable due to method configuration.",
            },
        ) from exc
    except MetaAnalysisInvocationError as exc:
        code = (
            "meta_analysis_stage_retry_exhausted"
            if exc.retry_exhausted
            else "meta_analysis_stage_invocation_failed"
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": code,
                "stage": exc.stage,
                "attempts": exc.attempts,
                "context_id": exc.context_id,
                "failure_code": exc.failure_code,
                "status_code": exc.status_code,
                "request_id": exc.request_id,
                "failure_detail": exc.failure_detail,
                "attempt_history": exc.attempt_history,
                "message": "A Meta-analysis provider stage failed.",
            },
        ) from exc
    except MetaAnalysisOutputError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "meta_analysis_invalid_method_output",
                "stage": exc.stage,
                "attempts": exc.attempts,
                "context_id": exc.context_id,
                "failure_code": exc.failure_code,
                "failure_detail": exc.failure_detail,
                "attempt_history": exc.attempt_history,
                "message": "A Meta-analysis method returned an invalid output contract.",
            },
        ) from exc
    except HTTPException as exc:
        if exc.status_code != 400:
            raise
        raise HTTPException(
            status_code=400,
            detail={
                "code": "meta_analysis_invalid_input",
                "message": str(exc.detail),
            },
        ) from exc


def _run_grade_module(action: Callable[[], T]) -> T:
    try:
        return _run_module(action)
    except GRADERiskOfBiasConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "grade_risk_of_bias_configuration_unavailable",
                "message": "GRADE risk-of-bias assessment is unavailable due to LLM configuration.",
            },
        ) from exc
    except GRADERiskOfBiasInvocationError as exc:
        code = (
            "grade_risk_of_bias_retry_exhausted"
            if exc.retry_exhausted
            else "grade_risk_of_bias_invocation_failed"
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": code,
                "domain": "risk_of_bias",
                "stage": exc.stage,
                "setting_id": exc.setting_id,
                "attempts": exc.attempts,
                "message": "The GRADE risk-of-bias LLM stage failed.",
            },
        ) from exc
    except GRADERiskOfBiasJudgementError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "grade_risk_of_bias_invalid_judgement_output",
                "domain": "risk_of_bias",
                "stage": exc.stage,
                "setting_id": exc.setting_id,
                "attempts": exc.attempts,
                "message": "GRADE risk-of-bias judgement output was invalid.",
            },
        ) from exc
    except GRADEInconsistencyConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "grade_inconsistency_configuration_unavailable",
                "domain": "inconsistency",
                "message": "GRADE inconsistency assessment is unavailable due to LLM configuration.",
            },
        ) from exc
    except GRADEInconsistencyInvocationError as exc:
        code = (
            "grade_inconsistency_retry_exhausted"
            if exc.retry_exhausted
            else "grade_inconsistency_invocation_failed"
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": code,
                "domain": "inconsistency",
                "stage": exc.stage,
                "setting_id": exc.setting_id,
                "attempts": exc.attempts,
                "message": "A GRADE inconsistency LLM stage failed.",
            },
        ) from exc
    except GRADEInconsistencyPolicyError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "grade_inconsistency_invalid_policy_output",
                "domain": "inconsistency",
                "setting_id": exc.setting_id,
                "attempts": exc.attempts,
                "message": "GRADE inconsistency policy output was invalid.",
            },
        ) from exc
    except GRADEInconsistencyJudgementError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "grade_inconsistency_invalid_judgement_output",
                "domain": "inconsistency",
                "stage": "judgement",
                "setting_id": exc.setting_id,
                "attempts": exc.attempts,
                "message": "GRADE inconsistency judgement output was invalid.",
            },
        ) from exc
    except GRADEIndirectnessConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "grade_indirectness_configuration_unavailable",
                "domain": "indirectness",
                "message": "GRADE indirectness assessment is unavailable due to LLM configuration.",
            },
        ) from exc
    except GRADEIndirectnessInvocationError as exc:
        code = (
            "grade_indirectness_retry_exhausted"
            if exc.retry_exhausted
            else "grade_indirectness_invocation_failed"
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": code,
                "domain": "indirectness",
                "stage": exc.stage,
                "setting_id": exc.setting_id,
                "attempts": exc.attempts,
                "message": "A GRADE indirectness LLM stage failed.",
            },
        ) from exc
    except GRADEIndirectnessClassificationError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "grade_indirectness_invalid_classification_output",
                "domain": "indirectness",
                "stage": "study_classification",
                "setting_id": exc.setting_id,
                "attempts": exc.attempts,
                "message": "GRADE indirectness classification output was invalid.",
            },
        ) from exc
    except GRADEIndirectnessThresholdError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "grade_indirectness_invalid_threshold_output",
                "domain": "indirectness",
                "stage": "threshold_generation",
                "setting_id": exc.setting_id,
                "attempts": exc.attempts,
                "message": "GRADE indirectness threshold output was invalid.",
            },
        ) from exc
    except GRADEIndirectnessJudgementError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "grade_indirectness_invalid_judgement_output",
                "domain": "indirectness",
                "stage": "evidence_body_judgement",
                "setting_id": exc.setting_id,
                "attempts": exc.attempts,
                "message": "GRADE indirectness judgement output was invalid.",
            },
        ) from exc
    except GRADEImprecisionConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "grade_imprecision_configuration_unavailable",
                "domain": "imprecision",
                "message": "GRADE imprecision assessment is unavailable due to LLM configuration.",
            },
        ) from exc
    except GRADEImprecisionInvocationError as exc:
        code = (
            "grade_imprecision_retry_exhausted"
            if exc.retry_exhausted
            else "grade_imprecision_invocation_failed"
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": code,
                "domain": "imprecision",
                "stage": exc.stage,
                "setting_id": exc.setting_id,
                "attempts": exc.attempts,
                "message": "The GRADE imprecision threshold stage failed.",
            },
        ) from exc
    except GRADEImprecisionThresholdError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "grade_imprecision_invalid_threshold_output",
                "domain": "imprecision",
                "stage": "threshold_generation",
                "setting_id": exc.setting_id,
                "attempts": exc.attempts,
                "message": "GRADE imprecision threshold output was invalid.",
            },
        ) from exc


def _run_q2pico_module(action: Callable[[], T]) -> T:
    try:
        return _run_module(action)
    except Q2PICOConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "q2pico_configuration_unavailable",
                "message": "Q2PICO is temporarily unavailable due to LLM configuration.",
            },
        ) from exc
    except Q2PICOInvocationError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "q2pico_stage_retry_exhausted",
                "stage": exc.stage,
                "attempts": exc.attempts,
                "message": "Q2PICO model stage failed after its retry budget was exhausted.",
            },
        ) from exc


def _run_search_retrieval_module(action: Callable[[], T]) -> T:
    try:
        return action()
    except SearchRetrievalStageError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "search_retrieval_stage_retry_exhausted",
                "stage": exc.stage,
                "attempts": exc.attempts,
                "message": "Search Retrieval provider stage failed after its retry budget was exhausted.",
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "search_retrieval_invalid_input",
                "message": str(exc),
            },
        ) from exc
    except HTTPException as exc:
        if exc.status_code != 400:
            raise
        raise HTTPException(
            status_code=400,
            detail={
                "code": "search_retrieval_invalid_input",
                "message": str(exc.detail),
            },
        ) from exc


def _run_study_screening_module(action: Callable[[], T]) -> T:
    try:
        return action()
    except StudyScreeningConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "study_screening_configuration_unavailable",
                "message": "Study Screening is unavailable due to LLM configuration.",
            },
        ) from exc
    except StudyScreeningInvocationError as exc:
        error_code = (
            "study_screening_criteria_retry_exhausted"
            if exc.stage == "criteria_planning"
            else "study_screening_article_retry_exhausted"
        )
        raise HTTPException(
            status_code=502,
            detail={
                "code": error_code,
                "stage": exc.stage,
                "attempts": exc.attempts,
                "article_id": exc.article_id,
                "evidence_scope": exc.evidence_scope,
                "message": "Study Screening LLM stage failed after its retry budget was exhausted.",
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "study_screening_invalid_input",
                "message": str(exc),
            },
        ) from exc
    except HTTPException as exc:
        if exc.status_code != 400:
            raise
        raise HTTPException(
            status_code=400,
            detail={
                "code": "study_screening_invalid_input",
                "message": str(exc.detail),
            },
        ) from exc


def _run_study_pio_module(action: Callable[[], T]) -> T:
    try:
        return action()
    except StudyPIOArticleContentMissingError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "study_pio_article_content_missing",
                "study_ids": list(exc.study_ids),
                "message": "One or more included studies have no usable full-text article content.",
            },
        ) from exc
    except StudyPIOConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "study_pio_configuration_unavailable",
                "message": "Study PIO is unavailable due to LLM configuration.",
            },
        ) from exc
    except StudyPIOInvocationError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "study_pio_stage_retry_exhausted",
                "stage": exc.stage,
                "study_id": exc.study_id,
                "attempts": exc.attempts,
                "message": "Study PIO extraction stage failed after its retry budget was exhausted.",
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "study_pio_invalid_input",
                "message": str(exc),
            },
        ) from exc
    except HTTPException as exc:
        if exc.status_code != 400:
            raise
        raise HTTPException(
            status_code=400,
            detail={
                "code": "study_pio_invalid_input",
                "message": str(exc.detail),
            },
        ) from exc


def _run_risk_of_bias_module(action: Callable[[], T]) -> T:
    try:
        return action()
    except RiskOfBiasArticleContentMissingError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "risk_of_bias_article_content_missing",
                "study_ids": list(exc.study_ids),
                "message": "One or more included studies have no usable full-text article content.",
            },
        ) from exc
    except RiskOfBiasConfigurationError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "risk_of_bias_configuration_unavailable",
                "message": "Risk of Bias is unavailable due to LLM configuration.",
            },
        ) from exc
    except RiskOfBiasDomainInvocationError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "code": "risk_of_bias_domain_retry_exhausted",
                "study_id": exc.study_id,
                "domain": exc.domain,
                "attempts": exc.attempts,
                "message": "Risk of Bias domain assessment failed after its retry budget was exhausted.",
            },
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "risk_of_bias_invalid_input",
                "message": str(exc),
            },
        ) from exc
    except HTTPException as exc:
        if exc.status_code != 400:
            raise
        raise HTTPException(
            status_code=400,
            detail={
                "code": "risk_of_bias_invalid_input",
                "message": str(exc.detail),
            },
        ) from exc


def _screening_year_bounds(
    payload: StudyScreeningRequest,
) -> tuple[int | None, int | None]:
    if payload.publication_year_range:
        value = payload.publication_year_range.strip()
        parts = [part.strip() for part in value.split("-", 1)]
        if len(parts) != 2 or not all(part.isdigit() and len(part) == 4 for part in parts):
            raise ValueError("publication_year_range must use YYYY-YYYY format")
        start, end = (int(part) for part in parts)
        if start > end:
            raise ValueError("publication year start must not exceed end")
        return start, end
    return payload.publication_year_start, payload.publication_year_end


def _optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    text = value.strip()
    return text or None


def _required_text_list(value: list[str], field_name: str) -> list[str]:
    items = [str(item).strip() for item in value]
    if any(not item for item in items):
        raise HTTPException(status_code=400, detail=f"{field_name} must not contain empty values")
    return items


def _parse_required(value: object, field_name: str, target_type: type):
    try:
        return from_jsonable(value, target_type, path=field_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _parse_required_list(value: object, field_name: str, item_type: type):
    try:
        return from_jsonable(value, list[item_type], path=field_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
