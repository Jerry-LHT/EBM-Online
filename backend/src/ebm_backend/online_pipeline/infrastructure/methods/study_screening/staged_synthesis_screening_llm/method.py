"""LLM adapters for high-recall and synthesis-ready Study Screening."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any
import unicodedata

from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.common import EvidenceSourceSpan
from ebm_backend.online_pipeline.domain.meta_analysis import MetaAnalysisSynthesisPlan
from ebm_backend.online_pipeline.domain.screening import (
    ArticleScreeningResult,
    ArticleSynthesisScreeningResult,
    CoarseScreeningDecision,
    ScreeningCriteria,
    ScreeningCriterionJudgment,
    ScreeningCriterionJudgmentValue,
    ScreeningCriterionType,
    SynthesisReadinessStatus,
    SynthesisTargetReadiness,
)
from ebm_backend.online_pipeline.domain.serialization import to_jsonable
from ebm_backend.online_pipeline.infrastructure.llm import LLMConfig, call_llm_json
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.llm_support import (
    call_with_one_retry,
    screening_llm_config,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.staged_synthesis_screening_llm.evidence import (
    EvidenceBundle,
    build_coarse_evidence,
    build_final_evidence,
)


SYSTEM_PROMPT = (
    "You are an evidence-based medicine reviewer performing an automated, "
    "auditable study-screening stage. Use only supplied article evidence. "
    "Return JSON matching the schema."
)
COARSE_PROMPT_VERSION = "coarse_screen_v1"
FINAL_PROMPT_VERSION = "final_screen_v1"


@dataclass(frozen=True)
class CoarseSynthesisStudyArticleScreener:
    config: LLMConfig | dict[str, Any] | None = None
    llm_caller: Any = call_llm_json
    prompt_dir: Path = Path(__file__).resolve().parent / "prompts"
    max_section_blocks: int = 4
    max_input_tokens: int = 12_000

    def run(
        self,
        *,
        criteria: ScreeningCriteria,
        synthesis_plan: MetaAnalysisSynthesisPlan,
        article: CleanedArticle,
    ) -> CoarseScreeningDecision:
        config = _single_attempt_config(screening_llm_config(self.config))
        input_tokens = min(
            self.max_input_tokens,
            _screening_input_token_budget(config),
        )
        evidence = build_coarse_evidence(
            article=article,
            criteria=criteria,
            synthesis_plan=synthesis_plan,
            max_section_blocks=self.max_section_blocks,
            max_chars=input_tokens * 4,
        )
        prompt = _render_prompt(
            prompt_dir=self.prompt_dir,
            version=COARSE_PROMPT_VERSION,
            criteria=criteria,
            synthesis_plan=synthesis_plan,
            evidence=evidence,
        )
        return call_with_one_retry(
            stage="coarse_article_screening",
            article_id=article.study_id,
            evidence_scope="title_abstract_selected_prose",
            action=lambda: _parse_coarse_result(
                self.llm_caller(
                    config=config,
                    system=SYSTEM_PROMPT,
                    prompt=prompt,
                    temperature=_temperature(config),
                    json_schema=_coarse_schema(),
                    json_schema_name="study_screening_coarse_synthesis_v1",
                ),
                article=article,
                evidence=evidence,
            ),
        )


@dataclass(frozen=True)
class SynthesisReadyStudyArticleScreener:
    config: LLMConfig | dict[str, Any] | None = None
    llm_caller: Any = call_llm_json
    prompt_dir: Path = Path(__file__).resolve().parent / "prompts"
    max_section_blocks: int = 10
    max_table_blocks: int = 5
    max_input_tokens: int | None = None

    def run(
        self,
        *,
        criteria: ScreeningCriteria,
        synthesis_plan: MetaAnalysisSynthesisPlan,
        article: CleanedArticle,
    ) -> ArticleSynthesisScreeningResult:
        config = _single_attempt_config(screening_llm_config(self.config))
        input_tokens = self.max_input_tokens or _screening_input_token_budget(config)
        evidence = build_final_evidence(
            article=article,
            criteria=criteria,
            synthesis_plan=synthesis_plan,
            max_section_blocks=self.max_section_blocks,
            max_table_blocks=self.max_table_blocks,
            max_chars=input_tokens * 4,
        )
        prompt = _render_prompt(
            prompt_dir=self.prompt_dir,
            version=FINAL_PROMPT_VERSION,
            criteria=criteria,
            synthesis_plan=synthesis_plan,
            evidence=evidence,
        )
        return call_with_one_retry(
            stage="synthesis_ready_article_screening",
            article_id=article.study_id,
            evidence_scope="targeted_prose_and_raw_tables",
            action=lambda: _parse_final_result(
                self.llm_caller(
                    config=config,
                    system=SYSTEM_PROMPT,
                    prompt=prompt,
                    temperature=_temperature(config),
                    json_schema=_final_schema(
                        criteria=criteria,
                        synthesis_plan=synthesis_plan,
                    ),
                    json_schema_name="study_screening_synthesis_ready_v1",
                ),
                criteria=criteria,
                synthesis_plan=synthesis_plan,
                evidence=evidence,
            ),
        )


def _render_prompt(
    *,
    prompt_dir: Path,
    version: str,
    criteria: ScreeningCriteria,
    synthesis_plan: MetaAnalysisSynthesisPlan,
    evidence: EvidenceBundle,
) -> str:
    template = (prompt_dir / f"{version}.txt").read_text(encoding="utf-8")
    return template.format(
        criteria=_format_criteria(criteria),
        targets=_format_targets(synthesis_plan),
        evidence=evidence.format(),
    )


def _format_criteria(criteria: ScreeningCriteria) -> str:
    lines = [
        *(
            f"- inc_{index}: {text}"
            for index, text in enumerate(criteria.inclusion_criteria, start=1)
        ),
        *(
            f"- exc_{index}: {text}"
            for index, text in enumerate(criteria.exclusion_criteria, start=1)
        ),
    ]
    return "\n".join(lines) if lines else "- None"


def _format_targets(synthesis_plan: MetaAnalysisSynthesisPlan) -> str:
    if not synthesis_plan.targets:
        return "- None"
    rows: list[str] = []
    for index, target in enumerate(synthesis_plan.targets, start=1):
        payload = to_jsonable(target)
        if isinstance(payload, dict):
            payload.pop("target_id", None)
        rows.append(
            f"- target_{index}: {json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
        )
    return "\n".join(rows)


def _parse_coarse_result(
    payload: dict[str, Any],
    *,
    article: CleanedArticle,
    evidence: EvidenceBundle,
) -> CoarseScreeningDecision:
    decision = str(payload.get("decision") or "").strip().lower()
    if decision not in {"advance", "exclude"}:
        raise ValueError("coarse screening decision must be advance or exclude")
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise ValueError("coarse screening reason is required")
    return CoarseScreeningDecision(
        study_id=article.study_id,
        decision=decision,
        reason=reason,
        source_spans=_parse_evidence_spans(
            payload.get("evidence_spans"),
            key="coarse",
            evidence_sources=evidence.sources,
        ),
        evidence_char_count=evidence.char_count,
        evidence_source_count=len(evidence.blocks),
    )


def _parse_final_result(
    payload: dict[str, Any],
    *,
    criteria: ScreeningCriteria,
    synthesis_plan: MetaAnalysisSynthesisPlan,
    evidence: EvidenceBundle,
) -> ArticleSynthesisScreeningResult:
    raw_judgments = payload.get("criterion_judgments")
    if not isinstance(raw_judgments, dict):
        raise ValueError("final screening requires criterion_judgments object")
    judgments: list[ScreeningCriterionJudgment] = []
    expected_criteria = {
        **{
            f"inc_{index}": (ScreeningCriterionType.INCLUSION, text)
            for index, text in enumerate(criteria.inclusion_criteria, start=1)
        },
        **{
            f"exc_{index}": (ScreeningCriterionType.EXCLUSION, text)
            for index, text in enumerate(criteria.exclusion_criteria, start=1)
        },
    }
    for key, (criterion_type, criterion_text) in expected_criteria.items():
        item = raw_judgments.get(key)
        if not isinstance(item, dict):
            raise ValueError(f"final screening missing criterion '{key}'")
        judgments.append(
            ScreeningCriterionJudgment(
                criterion_id=key,
                criterion_text=criterion_text,
                criterion_type=criterion_type,
                judgment=_judgment(item.get("judgment"), key=key),
                reason=_required_text(item.get("reason"), field=f"{key}.reason"),
                source_spans=_parse_evidence_spans(
                    item.get("evidence_spans"),
                    key=key,
                    evidence_sources=evidence.sources,
                ),
            )
        )

    raw_targets = payload.get("target_readiness")
    if not isinstance(raw_targets, dict):
        raise ValueError("final screening requires target_readiness object")
    readiness: list[SynthesisTargetReadiness] = []
    for index, target in enumerate(synthesis_plan.targets, start=1):
        key = f"target_{index}"
        item = raw_targets.get(key)
        if not isinstance(item, dict):
            raise ValueError(f"final screening missing target readiness '{key}'")
        try:
            status = SynthesisReadinessStatus(
                str(item.get("status") or "").strip().lower()
            )
        except ValueError as exc:
            raise ValueError(f"invalid readiness status for '{key}'") from exc
        readiness.append(
            SynthesisTargetReadiness(
                target_id=target.target_id,
                status=status,
                reason=_required_text(item.get("reason"), field=f"{key}.reason"),
                data_representation=_optional_text(item.get("data_representation")),
                experimental_arm=_optional_text(item.get("experimental_arm")),
                control_arm=_optional_text(item.get("control_arm")),
                source_spans=_parse_evidence_spans(
                    item.get("evidence_spans"),
                    key=key,
                    evidence_sources=evidence.sources,
                ),
            )
        )
    return ArticleSynthesisScreeningResult(
        article_screening=ArticleScreeningResult(
            criterion_judgments=judgments,
            overall_note=str(payload.get("overall_note") or "").strip(),
        ),
        target_readiness=readiness,
        overall_note=str(payload.get("overall_note") or "").strip(),
        evidence_char_count=evidence.char_count,
        evidence_source_count=len(evidence.blocks),
    )


def _coarse_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "decision": {"type": "string", "enum": ["advance", "exclude"]},
            "reason": {"type": "string"},
            "evidence_spans": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["decision", "reason", "evidence_spans"],
        "additionalProperties": False,
    }


def _final_schema(
    *,
    criteria: ScreeningCriteria,
    synthesis_plan: MetaAnalysisSynthesisPlan,
) -> dict[str, Any]:
    criterion_keys = [
        *(
            f"inc_{index}"
            for index in range(1, len(criteria.inclusion_criteria) + 1)
        ),
        *(
            f"exc_{index}"
            for index in range(1, len(criteria.exclusion_criteria) + 1)
        ),
    ]
    target_keys = [
        f"target_{index}" for index in range(1, len(synthesis_plan.targets) + 1)
    ]
    criterion_schema = {
        "type": "object",
        "properties": {
            "judgment": {"type": "string", "enum": ["yes", "no"]},
            "reason": {"type": "string"},
            "evidence_spans": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["judgment", "reason", "evidence_spans"],
        "additionalProperties": False,
    }
    target_schema = {
        "type": "object",
        "properties": {
            "status": {
                "type": "string",
                "enum": [status.value for status in SynthesisReadinessStatus],
            },
            "reason": {"type": "string"},
            "data_representation": {"type": ["string", "null"]},
            "experimental_arm": {"type": ["string", "null"]},
            "control_arm": {"type": ["string", "null"]},
            "evidence_spans": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "status",
            "reason",
            "data_representation",
            "experimental_arm",
            "control_arm",
            "evidence_spans",
        ],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {
            "criterion_judgments": {
                "type": "object",
                "properties": {key: criterion_schema for key in criterion_keys},
                "required": criterion_keys,
                "additionalProperties": False,
            },
            "target_readiness": {
                "type": "object",
                "properties": {key: target_schema for key in target_keys},
                "required": target_keys,
                "additionalProperties": False,
            },
            "overall_note": {"type": "string"},
        },
        "required": ["criterion_judgments", "target_readiness", "overall_note"],
        "additionalProperties": False,
    }


def _judgment(value: Any, *, key: str) -> ScreeningCriterionJudgmentValue:
    try:
        return ScreeningCriterionJudgmentValue(str(value or "").strip().lower())
    except ValueError as exc:
        raise ValueError(f"invalid binary judgment for '{key}'") from exc


def _parse_evidence_spans(
    value: Any,
    *,
    key: str,
    evidence_sources: dict[str, str],
) -> list[EvidenceSourceSpan]:
    if not isinstance(value, list):
        raise ValueError(f"evidence_spans for '{key}' must be a list")
    spans: list[EvidenceSourceSpan] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"evidence_spans for '{key}' must contain strings")
        clean = item.strip()
        if not clean:
            continue
        source_id = _matching_source_id(clean, evidence_sources)
        if source_id is not None:
            spans.append(EvidenceSourceSpan(source_id=source_id, text=clean))
    return spans


def _matching_source_id(span: str, evidence_sources: dict[str, str]) -> str | None:
    for source_id, source_text in evidence_sources.items():
        if span in source_text:
            return source_id
    normalized_span = _normalize(span)
    if not normalized_span:
        return None
    for source_id, source_text in evidence_sources.items():
        if normalized_span in _normalize(source_text):
            return source_id
    return None


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).translate(
        str.maketrans({"“": '"', "”": '"', "‘": "'", "’": "'", "–": "-", "—": "-"})
    )
    return re.sub(r"\s+", " ", normalized).strip()


def _required_text(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _temperature(config: LLMConfig | dict[str, Any]) -> float | None:
    value = config.temperature if isinstance(config, LLMConfig) else config.get("temperature")
    return float(value) if value is not None and str(value).strip() else None


def _single_attempt_config(config: LLMConfig | dict[str, Any]) -> dict[str, Any]:
    """Leave retry ownership to the screening stage (initial call + one retry)."""
    normalized = config.to_dict() if isinstance(config, LLMConfig) else dict(config)
    normalized["sdk_max_retries"] = 0
    normalized["json_marker_retry_enabled"] = False
    return normalized


def _screening_input_token_budget(config: LLMConfig | dict[str, Any]) -> int:
    if isinstance(config, LLMConfig):
        context = config.context_window_tokens
        configured = config.screening_input_token_budget
    else:
        context = int(config.get("context_window_tokens") or 128_000)
        configured = int(config.get("screening_input_token_budget") or 48_000)
    return max(4_000, min(configured, context - 16_000))
