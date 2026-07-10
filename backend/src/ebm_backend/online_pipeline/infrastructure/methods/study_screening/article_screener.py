"""LLM-backed article criterion judging for study screening."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.common import EvidenceSourceSpan
from ebm_backend.online_pipeline.domain.screening import (
    ScreeningCriteria,
    ScreeningCriterionJudgment,
    ScreeningCriterionJudgmentValue,
    ScreeningCriterionType,
)
from ebm_backend.online_pipeline.infrastructure.llm import LLMConfig, call_llm_json, load_llm_config
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.section_selector import (
    SelectedSection,
    select_screening_sections,
)


SYSTEM_PROMPT = (
    "You judge article eligibility criteria for evidence-based medicine study screening. "
    "Use only explicit evidence from the candidate article. Return JSON only."
)
PROMPT_VERSION = "study_screening_article_criterion_judge_v1"


@dataclass(frozen=True)
class ArticleScreeningResult:
    criterion_judgments: list[ScreeningCriterionJudgment]
    overall_note: str


@dataclass(frozen=True)
class StudyScreeningArticleScreener:
    config: LLMConfig | dict[str, Any] | None = None
    llm_caller: Any = call_llm_json
    prompt_dir: Path = Path(__file__).resolve().parent / "prompts"
    max_sections: int = 8

    def run(
        self,
        *,
        criteria: ScreeningCriteria,
        article: CleanedArticle,
    ) -> ArticleScreeningResult:
        config = self._config()
        payload = self.llm_caller(
            config=config,
            system=SYSTEM_PROMPT,
            prompt=self._render_prompt(
                criteria=criteria,
                article=article,
            ),
            temperature=_temperature(config),
        )
        return _parse_article_screening_result(payload, criteria=criteria)

    def _config(self) -> LLMConfig | dict[str, Any]:
        if self.config is not None:
            return self.config
        config = load_llm_config()
        if config is None:
            raise RuntimeError("Missing required LLM config")
        return config

    def _render_prompt(
        self,
        *,
        criteria: ScreeningCriteria,
        article: CleanedArticle,
    ) -> str:
        template = (self.prompt_dir / f"{PROMPT_VERSION}.txt").read_text(encoding="utf-8")
        selected_sections = select_screening_sections(article, max_sections=self.max_sections)
        return template.format(
            inclusion_criteria=_format_criteria_lines(criteria.inclusion_criteria, prefix="inc"),
            exclusion_criteria=_format_criteria_lines(criteria.exclusion_criteria, prefix="exc"),
            article_title=article.metadata.title or "[Missing title]",
            article_year=article.metadata.publication_year or "",
            sections=_format_selected_sections(selected_sections),
        )


def _parse_article_screening_result(
    payload: dict[str, Any],
    *,
    criteria: ScreeningCriteria,
) -> ArticleScreeningResult:
    raw_judgments = payload.get("criterion_judgments")
    if not isinstance(raw_judgments, dict):
        raise ValueError("study_screening article judgment response must include object field 'criterion_judgments'")

    expected_keys = {
        **{f"inc_{index}": (ScreeningCriterionType.INCLUSION, text) for index, text in enumerate(criteria.inclusion_criteria, start=1)},
        **{f"exc_{index}": (ScreeningCriterionType.EXCLUSION, text) for index, text in enumerate(criteria.exclusion_criteria, start=1)},
    }

    judgments: list[ScreeningCriterionJudgment] = []
    for key, (criterion_type, criterion_text) in expected_keys.items():
        item = raw_judgments.get(key)
        if not isinstance(item, dict):
            raise ValueError(f"study_screening article judgment missing criterion object for '{key}'")
        judgment_value = _parse_judgment_value(item.get("judgment"), key=key)
        reason = str(item.get("reason") or "").strip()
        spans = _parse_evidence_spans(item.get("evidence_spans"), key=key)
        judgments.append(
            ScreeningCriterionJudgment(
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
            f"study_screening article judgment for '{key}' must be one of yes, no, unclear"
        ) from exc


def _parse_evidence_spans(value: Any, *, key: str) -> list[EvidenceSourceSpan]:
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
        spans.append(
            EvidenceSourceSpan(
                source_id="article_text",
                text=clean,
            )
        )
    return spans


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

def _temperature(config: LLMConfig | dict[str, Any]) -> float | None:
    value = config.temperature if isinstance(config, LLMConfig) else config.get("temperature")
    return float(value) if value is not None and str(value).strip() else None
