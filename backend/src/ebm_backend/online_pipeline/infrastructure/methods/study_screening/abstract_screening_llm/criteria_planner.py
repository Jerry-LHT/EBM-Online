"""LLM-backed criteria planning paired with abstract screening."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.screening import ScreeningCriteria, ScreeningPolicy
from ebm_backend.online_pipeline.infrastructure.llm import LLMConfig, call_llm_json
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.llm_support import (
    call_with_one_retry,
    screening_llm_config,
)


SYSTEM_PROMPT = (
    "You plan operational eligibility criteria for title-and-abstract screening in evidence-based medicine. "
    "Use only the provided review question, structured PICO, and workflow constraints. Return JSON only."
)
PROMPT_VERSION = "abstract_screening_criteria_planning_v1"


@dataclass(frozen=True)
class AbstractScreeningCriteriaPlanner:
    config: LLMConfig | dict[str, Any] | None = None
    llm_caller: Any = call_llm_json
    prompt_dir: Path = Path(__file__).resolve().parent / "prompts"

    def run(
        self,
        *,
        question_text: str,
        question_pico: QuestionPICO,
        constraints: WorkflowConstraints,
        policy: ScreeningPolicy = ScreeningPolicy(),
    ) -> ScreeningCriteria:
        clean_question = question_text.strip()
        if not clean_question:
            raise ValueError("question_text is required")
        config = self._config()
        return call_with_one_retry(
            stage="criteria_planning",
            evidence_scope="abstract",
            action=lambda: _parse_screening_criteria(
                self.llm_caller(
                    config=config,
                    system=SYSTEM_PROMPT,
                    prompt=self._render_prompt(
                        question_text=clean_question,
                        question_pico=question_pico,
                        constraints=constraints,
                        policy=policy,
                    ),
                    temperature=_temperature(config),
                    json_schema=_criteria_response_schema(),
                    json_schema_name="study_screening_abstract_criteria",
                )
            ),
        )

    def _config(self) -> LLMConfig | dict[str, Any]:
        return screening_llm_config(self.config)

    def _render_prompt(
        self,
        *,
        question_text: str,
        question_pico: QuestionPICO,
        constraints: WorkflowConstraints,
        policy: ScreeningPolicy,
    ) -> str:
        template = (self.prompt_dir / f"{PROMPT_VERSION}.txt").read_text(encoding="utf-8")
        return template.format(
            question_text=question_text,
            participants=_json_list(question_pico.P),
            interventions=_json_list(question_pico.I),
            comparators=_json_list(question_pico.C),
            outcomes=_json_list(
                question_pico.O if policy.outcome_eligibility_enabled else []
            ),
            outcome_eligibility=(
                "enabled" if policy.outcome_eligibility_enabled else "disabled"
            ),
            study_design=(
                "Handled by system RCT and individually randomized parallel-group criteria"
                if policy.rct_only and policy.pairwise_parallel_individual_only
                else "Handled by a system RCT criterion"
                if policy.rct_only
                else "No system study-design restriction"
            ),
            publication_year_range="Handled deterministically outside the LLM",
            evidence_scope=constraints.evidence_scope or "",
        )


def _parse_screening_criteria(
    payload: dict[str, Any],
) -> ScreeningCriteria:
    inclusion = _normalize_string_list(
        payload.get("inclusion_criteria"),
        field_name="inclusion_criteria",
    )
    exclusion = _normalize_string_list(
        payload.get("exclusion_criteria"),
        field_name="exclusion_criteria",
    )
    rationale = str(payload.get("rationale") or "").strip()
    if not inclusion:
        raise ValueError("study_screening criteria planning requires at least one inclusion criterion")
    return ScreeningCriteria(
        inclusion_criteria=inclusion,
        exclusion_criteria=exclusion,
        rationale=rationale,
    )


def _normalize_string_list(value: Any, *, field_name: str) -> list[str]:
    if not isinstance(value, list):
        raise ValueError(f"study_screening criteria planning field '{field_name}' must be a list")
    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError(
                f"study_screening criteria planning field '{field_name}' must contain strings"
            )
        clean = item.strip()
        if not clean or clean.casefold() in seen:
            continue
        normalized.append(clean)
        seen.add(clean.casefold())
    return normalized


def _criteria_response_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "inclusion_criteria": {
                "type": "array",
                "items": {"type": "string"},
            },
            "exclusion_criteria": {
                "type": "array",
                "items": {"type": "string"},
            },
            "rationale": {"type": "string"},
        },
        "required": ["inclusion_criteria", "exclusion_criteria", "rationale"],
        "additionalProperties": False,
    }


def _json_list(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)


def _temperature(config: LLMConfig | dict[str, Any]) -> float | None:
    value = config.temperature if isinstance(config, LLMConfig) else config.get("temperature")
    return float(value) if value is not None and str(value).strip() else None
