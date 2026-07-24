"""LLM-backed article judging paired with full-text criteria planning."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any
import unicodedata

from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.common import EvidenceSourceSpan
from ebm_backend.online_pipeline.domain.screening import (
    ArticleScreeningResult,
    ScreeningCriteria,
    ScreeningCriterionJudgment,
    ScreeningCriterionJudgmentValue,
    ScreeningCriterionType,
)
from ebm_backend.online_pipeline.infrastructure.llm import LLMConfig, call_llm_json
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.full_text_screening_llm.section_selector import (
    SelectedSection,
    select_screening_sections,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.llm_support import (
    call_with_one_retry,
    screening_llm_config,
)


SYSTEM_PROMPT = (
    "You judge article eligibility criteria for evidence-based medicine study screening. "
    "Use only explicit evidence from the candidate article. Return JSON only."
)
PROMPT_VERSION = "full_text_article_criterion_judge_v1"


@dataclass(frozen=True)
class FullTextStudyArticleScreener:
    config: LLMConfig | dict[str, Any] | None = None
    llm_caller: Any = call_llm_json
    prompt_dir: Path = Path(__file__).resolve().parent / "prompts"
    max_sections: int = 8
    max_input_chars: int = 60_000

    def run(
        self,
        *,
        criteria: ScreeningCriteria,
        article: CleanedArticle,
    ) -> ArticleScreeningResult:
        config = self._config()
        selected_sections = select_screening_sections(
            article,
            max_sections=self.max_sections,
        )
        if self.max_input_chars <= 0:
            raise ValueError("max_input_chars must be positive")
        evidence_text = _format_selected_sections(selected_sections)[: self.max_input_chars]
        evidence_sources = {
            "title": article.metadata.title or "",
            "metadata": _format_article_metadata(article),
            "article_text": evidence_text,
        }
        return call_with_one_retry(
            stage="article_screening",
            article_id=article.study_id,
            evidence_scope="full_text",
            action=lambda: _parse_article_screening_result(
                self.llm_caller(
                    config=config,
                    system=SYSTEM_PROMPT,
                    prompt=self._render_prompt(
                        criteria=criteria,
                        article=article,
                        evidence_text=evidence_text,
                    ),
                    temperature=_temperature(config),
                    json_schema=_article_response_schema(criteria=criteria),
                    json_schema_name="study_screening_full_text_article",
                ),
                criteria=criteria,
                evidence_sources=evidence_sources,
            ),
        )

    def _config(self) -> LLMConfig | dict[str, Any]:
        return screening_llm_config(self.config)

    def _render_prompt(
        self,
        *,
        criteria: ScreeningCriteria,
        article: CleanedArticle,
        evidence_text: str,
    ) -> str:
        template = (self.prompt_dir / f"{PROMPT_VERSION}.txt").read_text(encoding="utf-8")
        return template.format(
            inclusion_criteria=_format_criteria_lines(criteria.inclusion_criteria, prefix="inc"),
            exclusion_criteria=_format_criteria_lines(criteria.exclusion_criteria, prefix="exc"),
            article_title=article.metadata.title or "[Missing title]",
            article_year=article.metadata.publication_year or "",
            article_metadata=_format_article_metadata(article),
            sections=evidence_text,
        )


def _parse_article_screening_result(
    payload: dict[str, Any],
    *,
    criteria: ScreeningCriteria,
    evidence_sources: dict[str, str],
) -> ArticleScreeningResult:
    raw_judgments = payload.get("criterion_judgments")
    if not isinstance(raw_judgments, dict):
        raise ValueError("study_screening article judgment response must include object field 'criterion_judgments'")
    expected_keys = {
        **{
            f"inc_{index}": (ScreeningCriterionType.INCLUSION, text)
            for index, text in enumerate(criteria.inclusion_criteria, start=1)
        },
        **{
            f"exc_{index}": (ScreeningCriterionType.EXCLUSION, text)
            for index, text in enumerate(criteria.exclusion_criteria, start=1)
        },
    }
    judgments: list[ScreeningCriterionJudgment] = []
    for key, (criterion_type, criterion_text) in expected_keys.items():
        item = raw_judgments.get(key)
        if not isinstance(item, dict):
            raise ValueError(f"study_screening article judgment missing criterion object for '{key}'")
        judgment_value = _parse_judgment_value(item.get("judgment"), key=key)
        reason = str(item.get("reason") or "").strip()
        spans = _parse_evidence_spans(
            item.get("evidence_spans"),
            key=key,
            evidence_sources=evidence_sources,
        )
        judgments.append(
            ScreeningCriterionJudgment(
                criterion_id=key,
                criterion_text=criterion_text,
                criterion_type=criterion_type,
                judgment=judgment_value,
                reason=reason,
                source_spans=spans,
            )
        )
    overall_note = str(payload.get("overall_note") or "").strip()
    return ArticleScreeningResult(
        criterion_judgments=judgments,
        overall_note=overall_note,
    )


def _parse_judgment_value(value: Any, *, key: str) -> ScreeningCriterionJudgmentValue:
    text = str(value or "").strip().lower()
    try:
        return ScreeningCriterionJudgmentValue(text)
    except ValueError as exc:
        raise ValueError(
            f"study_screening article judgment for '{key}' must be one of yes, no"
        ) from exc


def _parse_evidence_spans(
    value: Any,
    *,
    key: str,
    evidence_sources: dict[str, str],
) -> list[EvidenceSourceSpan]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"study_screening evidence_spans for '{key}' must be a list")
    spans: list[EvidenceSourceSpan] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"study_screening evidence_spans for '{key}' must contain strings")
        clean = item.strip()
        if not clean:
            continue
        source_id = _matching_source_id(clean, evidence_sources)
        if source_id is None:
            continue
        spans.append(
            EvidenceSourceSpan(
                source_id=source_id,
                text=clean,
            )
        )
    return spans


def _matching_source_id(
    span: str,
    evidence_sources: dict[str, str],
) -> str | None:
    for source_id, source_text in evidence_sources.items():
        if span in source_text:
            return source_id
    normalized_span = _normalize_span_text(span)
    if not normalized_span:
        return None
    return next(
        (
            source_id
            for source_id, source_text in evidence_sources.items()
            if normalized_span in _normalize_span_text(source_text)
        ),
        None,
    )


def _normalize_span_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.translate(
        str.maketrans({"“": '\"', "”": '\"', "‘": "'", "’": "'", "–": "-", "—": "-"})
    )
    return re.sub(r"\s+", " ", normalized).strip()


def _format_criteria_lines(criteria: list[str], *, prefix: str) -> str:
    if not criteria:
        return "- None provided"
    return "\n".join(f"- {prefix}_{index}: {criterion}" for index, criterion in enumerate(criteria, start=1))


def _format_selected_sections(sections: list[SelectedSection]) -> str:
    if not sections:
        return "[No article sections available]"
    blocks: list[str] = []
    for section in sections:
        blocks.append(f"[{section.label}: {section.title}]")
        blocks.append(section.text)
    return "\n\n".join(blocks)


def _article_response_schema(*, criteria: ScreeningCriteria) -> dict[str, Any]:
    keys = [
        *[f"inc_{index}" for index in range(1, len(criteria.inclusion_criteria) + 1)],
        *[f"exc_{index}" for index in range(1, len(criteria.exclusion_criteria) + 1)],
    ]
    judgment_schema = {
        "type": "object",
        "properties": {
            "judgment": {"type": "string", "enum": ["yes", "no"]},
            "reason": {"type": "string"},
            "evidence_spans": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": ["judgment", "reason", "evidence_spans"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "criterion_judgments": {
                "type": "object",
                "properties": {key: judgment_schema for key in keys},
                "required": keys,
                "additionalProperties": False,
            },
            "overall_note": {"type": "string"},
        },
        "required": ["criterion_judgments", "overall_note"],
        "additionalProperties": False,
    }


def _format_article_metadata(article: CleanedArticle) -> str:
    metadata = article.metadata
    return (
        f"Languages: {metadata.languages or []}\n"
        f"Retracted: {metadata.is_retracted}\n"
        f"Retraction notice: {metadata.is_retraction_notice}\n"
        f"Correction: {metadata.is_correction}"
    )


def _temperature(config: LLMConfig | dict[str, Any]) -> float | None:
    value = config.temperature if isinstance(config, LLMConfig) else config.get("temperature")
    return float(value) if value is not None and str(value).strip() else None
