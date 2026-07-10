"""LLM-backed criteria planning for study screening."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.screening import ScreeningCriteria
from ebm_backend.online_pipeline.infrastructure.llm import LLMConfig, call_llm_json, load_llm_config


SYSTEM_PROMPT = (
    "You plan operational eligibility criteria for evidence-based medicine study screening. "
    "Use only the provided review question, structured PICO, and workflow constraints. Return JSON only."
)
PROMPT_VERSION = "study_screening_criteria_planning_v1"


@dataclass(frozen=True)
class ScreeningCriteriaPlanner:
    config: LLMConfig | dict[str, Any] | None = None
    llm_caller: Any = call_llm_json
    prompt_dir: Path = Path(__file__).resolve().parent / "prompts"

    def run(
        self,
        *,
        question_text: str,
        question_pico: QuestionPICO,
        constraints: WorkflowConstraints,
    ) -> ScreeningCriteria:
        clean_question = question_text.strip()
        if not clean_question:
            raise ValueError("question_text is required")
        config = self._config()
        payload = self.llm_caller(
            config=config,
            system=SYSTEM_PROMPT,
            prompt=self._render_prompt(
                question_text=clean_question,
                question_pico=question_pico,
                constraints=constraints,
            ),
            temperature=_temperature(config),
        )
        return _parse_screening_criteria(
            payload,
            publication_year_range=constraints.publication_year_range,
        )

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
        question_text: str,
        question_pico: QuestionPICO,
        constraints: WorkflowConstraints,
    ) -> str:
        template = (self.prompt_dir / f"{PROMPT_VERSION}.txt").read_text(encoding="utf-8")
        return template.format(
            question_text=question_text,
            participants=_json_list(question_pico.P),
            interventions=_json_list(question_pico.I),
            comparators=_json_list(question_pico.C),
            outcomes=_json_list(question_pico.O),
            study_design=constraints.study_design,
            publication_year_range=constraints.publication_year_range or "None provided",
            evidence_scope=constraints.evidence_scope or "",
        )


def _parse_screening_criteria(
    payload: dict[str, Any],
    *,
    publication_year_range: str | None = None,
) -> ScreeningCriteria:
    inclusion = _normalize_string_list(payload.get("inclusion_criteria"), field_name="inclusion_criteria")
    exclusion = _normalize_string_list(payload.get("exclusion_criteria"), field_name="exclusion_criteria")
    inclusion = _drop_outcome_reporting_requirements(inclusion)
    exclusion = _drop_outcome_reporting_requirements(exclusion)
    inclusion = _ensure_publication_year_criterion(inclusion, publication_year_range=publication_year_range)
    rationale = str(payload.get("rationale") or "").strip()
    if not inclusion:
        raise ValueError("study_screening criteria planning requires at least one inclusion criterion")
    return ScreeningCriteria(
        inclusion_criteria=inclusion,
        exclusion_criteria=exclusion,
        rationale=rationale,
    )


def _ensure_publication_year_criterion(
    criteria: list[str],
    *,
    publication_year_range: str | None,
) -> list[str]:
    clean_range = str(publication_year_range or "").strip()
    if not clean_range:
        return criteria
    if any("publication year" in criterion.casefold() for criterion in criteria):
        return criteria
    return [*criteria, f"Publication year is within {clean_range}."]


def _normalize_string_list(value: Any, *, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"study_screening criteria planning field '{field_name}' must be a list")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError(f"study_screening criteria planning field '{field_name}' must contain strings")
        clean = item.strip()
        if not clean or clean.casefold() in seen:
            continue
        normalized.append(clean)
        seen.add(clean.casefold())
    return normalized


def _drop_outcome_reporting_requirements(criteria: list[str]) -> list[str]:
    kept: list[str] = []
    for criterion in criteria:
        if _looks_like_outcome_reporting_requirement(criterion):
            continue
        kept.append(criterion)
    return kept


def _looks_like_outcome_reporting_requirement(text: str) -> bool:
    lowered = re.sub(r"\s+", " ", text.strip().casefold())
    if not lowered:
        return False
    has_outcome_signal = any(
        token in lowered
        for token in (
            "outcome",
            "quality of life",
            "disease activity",
            "flare",
            "relapse",
            "endpoint",
        )
    )
    has_reporting_signal = any(
        token in lowered
        for token in (
            "reported",
            "report",
            "planned",
            "provides",
            "provide",
            "availability",
            "data are",
            "data is",
            "extractable",
            "incompleteness",
            "completeness",
        )
    )
    if has_outcome_signal and has_reporting_signal:
        return True
    if lowered.startswith("outcomes ") or lowered.startswith("outcome "):
        if "not an exclusion criterion" in lowered:
            return True
    return False


def _json_list(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)


def _temperature(config: LLMConfig | dict[str, Any]) -> float | None:
    value = config.temperature if isinstance(config, LLMConfig) else config.get("temperature")
    return float(value) if value is not None and str(value).strip() else None
