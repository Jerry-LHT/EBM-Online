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
from ebm_backend.online_pipeline.domain.risk_of_bias import RiskOfBiasAssessment
from ebm_backend.online_pipeline.domain.screening import ScreeningCriteria
from ebm_backend.online_pipeline.domain.serialization import from_jsonable, to_jsonable
from ebm_backend.online_pipeline.domain.study_characteristics import StudyPIOCharacteristics
from ebm_backend.online_pipeline.interfaces.api.dependencies import (
    get_module_use_case_facade_for_api,
    get_q2pico_use_case_for_api,
    get_search_retrieval_use_case_for_api,
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


router = APIRouter(prefix="/modules", tags=["modules"])

T = TypeVar("T")


@router.post("/q2pico")
def run_q2pico(payload: Q2PICORequest) -> dict[str, object]:
    question_text = payload.question_text.strip()
    use_case = get_q2pico_use_case_for_api(method_name=_method_name(payload))
    result = _run_module(
        lambda: use_case.execute(question_text=question_text, expand_outcomes=payload.expand_outcomes)
    )
    return to_jsonable(result)


@router.post("/search-retrieval")
def run_search_retrieval(payload: SearchRetrievalRequest) -> dict[str, object]:
    question_pico = _parse_required(payload.question_pico, "question_pico", QuestionPICO)
    config = ModuleRunConfig(max_results=payload.max_results)
    use_case = get_search_retrieval_use_case_for_api(
        method_name=_method_name(payload),
        mesh_method_name=_optional_method_name(payload.mesh_method_name),
        textword_method_name=_optional_method_name(payload.textword_method_name),
    )
    result = _run_module(
        lambda: use_case.execute(
            question_pico=question_pico,
            config=config,
            options=None
            if payload.mesh_method_name is None and payload.textword_method_name is None
            else _search_retrieval_options(payload),
        )
    )
    return to_jsonable(result)


@router.post("/study-screening")
def run_study_screening(payload: StudyScreeningRequest) -> dict[str, object]:
    question_text = payload.question_text.strip()
    question_pico = _parse_required(payload.question_pico, "question_pico", QuestionPICO)
    articles = _parse_required_list(payload.articles, "articles", CleanedArticle)
    use_case = get_study_screening_use_case_for_api(method_name=_method_name(payload))
    result = _run_module(
        lambda: use_case.execute(
            question_text=question_text,
            question_pico=question_pico,
            constraints=WorkflowConstraints(
                publication_year_range=_optional_text(payload.publication_year_range)
            ),
            articles=articles,
        )
    )
    return to_jsonable(result)


@router.post("/study-pio-extraction")
def run_study_pio_extraction(payload: StudyPIOExtractionRequest) -> dict[str, object]:
    question_pico = _parse_required(payload.question_pico, "question_pico", QuestionPICO)
    included_studies = _required_text_list(payload.included_studies, "included_studies")
    articles = _parse_required_list(payload.articles, "articles", CleanedArticle)
    facade = _module_use_case_facade()
    result = _run_module(
        lambda: facade.run_study_pio_extraction(
            method_name=_method_name(payload),
            question_pico=question_pico,
            included_studies=included_studies,
            articles=articles,
        )
    )
    return to_jsonable(result)


@router.post("/risk-of-bias")
def run_risk_of_bias(payload: RiskOfBiasRequest) -> dict[str, object]:
    included_studies = _required_text_list(payload.included_studies, "included_studies")
    articles = _parse_required_list(payload.articles, "articles", CleanedArticle)
    facade = _module_use_case_facade()
    result = _run_module(
        lambda: facade.run_risk_of_bias(
            method_name=_method_name(payload),
            included_studies=included_studies,
            articles=articles,
        )
    )
    return to_jsonable(result)


@router.post("/meta-analysis")
def run_meta_analysis(payload: MetaAnalysisRequest) -> dict[str, object]:
    review_id = payload.review_id.strip()
    question_text = payload.question_text.strip()
    question_pico = _parse_required(payload.question_pico, "question_pico", QuestionPICO)
    included_studies = _required_text_list(payload.included_studies, "included_studies")
    articles = _parse_required_list(payload.articles, "articles", CleanedArticle)
    study_characteristics = _parse_required_list(payload.study_characteristics, "study_characteristics", StudyPIOCharacteristics)
    facade = _module_use_case_facade()
    result = _run_module(
        lambda: facade.run_meta_analysis(
            method_name=_method_name(payload),
            review_id=review_id,
            question_text=question_text,
            question_pico=question_pico,
            included_studies=included_studies,
            articles=articles,
            study_characteristics=study_characteristics,
        )
    )
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
    facade = _module_use_case_facade()
    result = _run_module(
        lambda: facade.run_grade_assessment(
            method_name=_method_name(payload),
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


def _module_use_case_facade():
    return get_module_use_case_facade_for_api()


def _search_retrieval_options(payload: SearchRetrievalRequest):
    from ebm_backend.online_pipeline.domain.search import SearchRetrievalOptions

    return SearchRetrievalOptions(
        mesh_method_name=_optional_method_name(payload.mesh_method_name),
        textword_method_name=_optional_method_name(payload.textword_method_name),
    )


def _method_name(payload) -> str:
    method_name = payload.method_name.strip()
    if not method_name:
        raise HTTPException(status_code=400, detail="method_name is required")
    return method_name


def _run_module(action: Callable[[], T]) -> T:
    try:
        return action()
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _optional_method_name(value: str | None) -> str | None:
    if value is None:
        return None
    method_name = value.strip()
    return method_name or None


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
