"""Request schemas for module-level API endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ModuleMethodRequest(BaseModel):
    method_name: str = Field(min_length=1)


class Q2PICORequest(ModuleMethodRequest):
    method_name: str = "default"
    question_text: str = Field(min_length=1)
    expand_outcomes: bool = False


class SearchRetrievalRequest(ModuleMethodRequest):
    method_name: str = "pubmed_pmc"
    question_pico: dict[str, Any]
    max_results: int = Field(default=20, ge=1)
    mesh_method_name: str | None = None
    textword_method_name: str | None = None


class StudyScreeningRequest(ModuleMethodRequest):
    method_name: str = "default"
    question_text: str = Field(min_length=1)
    question_pico: dict[str, Any]
    publication_year_range: str | None = None
    articles: list[dict[str, Any]]


class StudyPIOExtractionRequest(ModuleMethodRequest):
    question_pico: dict[str, Any]
    included_studies: list[str]
    articles: list[dict[str, Any]]


class RiskOfBiasRequest(ModuleMethodRequest):
    included_studies: list[str]
    articles: list[dict[str, Any]]


class MetaAnalysisRequest(ModuleMethodRequest):
    review_id: str = Field(min_length=1)
    question_text: str = Field(min_length=1)
    question_pico: dict[str, Any]
    included_studies: list[str]
    articles: list[dict[str, Any]]
    study_characteristics: list[dict[str, Any]]


class GradeAssessmentRequest(ModuleMethodRequest):
    review_id: str = Field(min_length=1)
    question_text: str = Field(min_length=1)
    question_pico: dict[str, Any]
    screening_criteria: dict[str, Any]
    study_characteristics: list[dict[str, Any]]
    risk_of_bias: list[dict[str, Any]]
    meta_analysis_result: dict[str, Any]
