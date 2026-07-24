"""Request schemas for module-level and complete-workflow API endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, model_validator

from ebm_backend.online_pipeline.domain.module_config import (
    DEFAULT_MAX_CANDIDATES_PER_SOURCE,
    DEFAULT_MAX_RESULTS_PER_SOURCE,
    MAX_CANDIDATES_PER_SOURCE,
    MAX_RESULTS_PER_SOURCE,
)
from ebm_backend.online_pipeline.domain.screening import (
    ScreeningEvidenceScope,
    ScreeningReportScope,
)
from ebm_backend.online_pipeline.domain.risk_of_bias import DEFAULT_ROB1_DOMAINS


MAX_ARTICLE_LEVEL_ITEMS_PER_RUN = 500


class OnlineEBMWorkflowRequest(BaseModel):
    review_id: str = Field(min_length=1)
    question_text: str = Field(min_length=1)
    expand_outcomes: bool = True
    source_names: list[str] = Field(
        default_factory=lambda: ["pubmed"],
        min_length=1,
        max_length=4,
    )
    max_candidates_per_source: int | None = Field(
        default=DEFAULT_MAX_CANDIDATES_PER_SOURCE,
        ge=1,
        le=MAX_CANDIDATES_PER_SOURCE,
    )
    max_results_per_source: int = Field(
        default=DEFAULT_MAX_RESULTS_PER_SOURCE,
        ge=1,
        le=MAX_RESULTS_PER_SOURCE,
    )
    rct_only: bool = True
    publication_year_range: str | None = None

    @model_validator(mode="after")
    def validate_workflow_limits(self) -> "OnlineEBMWorkflowRequest":
        if (
            self.max_candidates_per_source is not None
            and self.max_candidates_per_source < self.max_results_per_source
        ):
            raise ValueError(
                "max_candidates_per_source must be greater than or equal to "
                "max_results_per_source"
            )
        return self


class Q2PICORequest(BaseModel):
    question_text: str = Field(min_length=1)
    expand_outcomes: bool = True


class SearchRetrievalRequest(BaseModel):
    source_names: list[str] = Field(
        default_factory=lambda: ["pubmed"],
        min_length=1,
    )
    question_pico: dict[str, Any]
    max_candidates_per_source: int | None = Field(
        default=DEFAULT_MAX_CANDIDATES_PER_SOURCE,
        ge=1,
        le=MAX_CANDIDATES_PER_SOURCE,
    )
    max_results_per_source: int = Field(
        default=DEFAULT_MAX_RESULTS_PER_SOURCE,
        ge=1,
        le=MAX_RESULTS_PER_SOURCE,
    )
    rct_filter_enabled: bool = True

    @model_validator(mode="after")
    def validate_search_limits(self) -> "SearchRetrievalRequest":
        if (
            self.max_candidates_per_source is not None
            and self.max_candidates_per_source < self.max_results_per_source
        ):
            raise ValueError(
                "max_candidates_per_source must be greater than or equal to max_results_per_source"
            )
        return self


class StudyScreeningRequest(BaseModel):
    question_text: str = Field(min_length=1)
    question_pico: dict[str, Any]
    publication_year_range: str | None = None
    publication_year_start: int | None = Field(default=None, ge=1000, le=3000)
    publication_year_end: int | None = Field(default=None, ge=1000, le=3000)
    rct_only: bool = True
    report_scope: ScreeningReportScope = ScreeningReportScope.PRIMARY_RESULTS_REPORT
    outcome_eligibility_enabled: bool = False
    allowed_languages: list[str] = Field(default_factory=list, max_length=20)
    exclude_retracted: bool = True
    evidence_scope: ScreeningEvidenceScope = ScreeningEvidenceScope.FULL_TEXT
    articles: list[dict[str, Any]] = Field(max_length=500)

    @model_validator(mode="after")
    def validate_screening_years(self) -> "StudyScreeningRequest":
        if (
            self.publication_year_start is not None
            and self.publication_year_end is not None
            and self.publication_year_start > self.publication_year_end
        ):
            raise ValueError(
                "publication_year_start must be less than or equal to publication_year_end"
            )
        if self.publication_year_range and (
            self.publication_year_start is not None
            or self.publication_year_end is not None
        ):
            raise ValueError(
                "publication_year_range cannot be combined with structured publication year fields"
            )
        return self


class StudyPIOExtractionRequest(BaseModel):
    question_pico: dict[str, Any]
    included_studies: list[str] = Field(
        max_length=MAX_ARTICLE_LEVEL_ITEMS_PER_RUN,
    )
    articles: list[dict[str, Any]] = Field(
        max_length=MAX_ARTICLE_LEVEL_ITEMS_PER_RUN,
    )


class RiskOfBiasDomainConfigRequest(BaseModel):
    assessed_domains: list[str] = Field(
        default_factory=lambda: list(DEFAULT_ROB1_DOMAINS),
        json_schema_extra={"minItems": 1, "maxItems": 7},
    )
    overall_key_domains: list[str] = Field(
        default_factory=lambda: list(DEFAULT_ROB1_DOMAINS),
        json_schema_extra={"minItems": 1, "maxItems": 7},
    )


class RiskOfBiasRequest(BaseModel):
    included_studies: list[str] = Field(
        max_length=MAX_ARTICLE_LEVEL_ITEMS_PER_RUN,
    )
    articles: list[dict[str, Any]] = Field(
        max_length=MAX_ARTICLE_LEVEL_ITEMS_PER_RUN,
    )
    domain_config: RiskOfBiasDomainConfigRequest = Field(
        default_factory=RiskOfBiasDomainConfigRequest
    )


class MetaAnalysisRequest(BaseModel):
    review_id: str = Field(min_length=1)
    question_text: str = Field(min_length=1)
    question_pico: dict[str, Any]
    screening_criteria: dict[str, Any]
    included_studies: list[str] = Field(
        max_length=MAX_ARTICLE_LEVEL_ITEMS_PER_RUN,
    )
    articles: list[dict[str, Any]] = Field(
        max_length=MAX_ARTICLE_LEVEL_ITEMS_PER_RUN,
    )


class GradeAssessmentRequest(BaseModel):
    review_id: str = Field(min_length=1)
    question_text: str = Field(min_length=1)
    question_pico: dict[str, Any]
    screening_criteria: dict[str, Any]
    study_characteristics: list[dict[str, Any]] = Field(
        max_length=MAX_ARTICLE_LEVEL_ITEMS_PER_RUN,
    )
    risk_of_bias: list[dict[str, Any]] = Field(
        max_length=MAX_ARTICLE_LEVEL_ITEMS_PER_RUN,
    )
    meta_analysis_result: dict[str, Any]
