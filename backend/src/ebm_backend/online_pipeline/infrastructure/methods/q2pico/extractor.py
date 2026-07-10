"""LLM-backed Question-to-PICO split-slot extractor."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.infrastructure.llm import LLMConfig, call_llm_json, load_llm_config


PICO_LABELS: tuple[str, ...] = ("P", "I", "C", "O")
LABEL_TO_OUTPUT_KEY: dict[str, str] = {
    "P": "participants",
    "I": "interventions",
    "C": "comparators",
    "O": "outcomes",
}
LABEL_PROMPT_VERSIONS: dict[str, str] = {
    "P": "question_slot_split_v1_p_only",
    "I": "question_slot_split_v1_i_only",
    "C": "question_slot_split_v1_c_only",
    "O": "question_slot_split_v1_o_only",
}
OUTCOME_EXPANSION_PROMPT_VERSION = "question_slot_outcome_planning_v1"
SYSTEM_PROMPT = (
    "You extract structured PICO slots from clinical questions. "
    "Use only information inferable from the question text and return JSON only."
)
OUTCOME_EXPANSION_SYSTEM_PROMPT = (
    "You plan patient-important review outcomes for intervention questions in evidence-based medicine. "
    "Use only the clinical question and structured PIC context provided. Return JSON only."
)

LLMJsonCaller = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class Q2PICOSplitLLMExtractor:
    """Extract P/I/C/O by making one scoped LLM call per slot."""

    config: LLMConfig | dict[str, Any] | None = None
    llm_caller: LLMJsonCaller = call_llm_json
    prompt_dir: Path = Path(__file__).resolve().parent / "prompts"
    labels: tuple[str, ...] = PICO_LABELS
    max_workers: int = 4

    def run(self, *, question_text: str, expand_outcomes: bool = False) -> QuestionPICO:
        clean_question = question_text.strip()
        if not clean_question:
            raise ValueError("question_text is required")
        if not self.labels:
            raise ValueError("labels must not be empty")
        unknown_labels = set(self.labels) - set(PICO_LABELS)
        if unknown_labels:
            raise ValueError(f"unsupported Q2PICO labels: {sorted(unknown_labels)}")
        if self.max_workers <= 0:
            raise ValueError("max_workers must be positive")

        slots: dict[str, list[str]] = {label: [] for label in PICO_LABELS}
        config = self._config()
        workers = min(self.max_workers, len(self.labels))
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_label = {
                executor.submit(self._extract_label, label=label, question_text=clean_question, config=config): label
                for label in self.labels
            }
            for future in as_completed(future_to_label):
                label, values = future.result()
                slots[label] = values
        expanded_outcomes: list[str] = []
        if expand_outcomes:
            expanded_outcomes = self._expand_outcomes(
                question_text=clean_question,
                participants=slots["P"],
                interventions=slots["I"],
                comparators=slots["C"],
                explicit_outcomes=slots["O"],
                config=config,
            )
        return QuestionPICO(
            P=slots["P"],
            I=slots["I"],
            C=slots["C"],
            O=slots["O"],
            O_expanded=expanded_outcomes,
        )

    def _extract_label(
        self,
        *,
        label: str,
        question_text: str,
        config: LLMConfig | dict[str, Any],
    ) -> tuple[str, list[str]]:
        output_key = LABEL_TO_OUTPUT_KEY[label]
        payload = self.llm_caller(
            config=config,
            system=SYSTEM_PROMPT,
            prompt=self._render_prompt(label=label, question_text=question_text),
            temperature=_temperature(config),
        )
        return label, _extract_slot_values(payload, output_key=output_key)

    def _config(self) -> LLMConfig | dict[str, Any]:
        if self.config is not None:
            return _normalize_method_config(self.config)
        config = load_llm_config()
        if config is None:
            raise RuntimeError("Missing required LLM config")
        return _normalize_method_config(config)

    def _render_prompt(self, *, label: str, question_text: str) -> str:
        prompt_version = LABEL_PROMPT_VERSIONS[label]
        template = (self.prompt_dir / f"{prompt_version}.txt").read_text(encoding="utf-8")
        return template.format(question_text=question_text)

    def _expand_outcomes(
        self,
        *,
        question_text: str,
        participants: list[str],
        interventions: list[str],
        comparators: list[str],
        explicit_outcomes: list[str],
        config: LLMConfig | dict[str, Any],
    ) -> list[str]:
        payload = self.llm_caller(
            config=config,
            system=OUTCOME_EXPANSION_SYSTEM_PROMPT,
            prompt=self._render_outcome_expansion_prompt(
                question_text=question_text,
                participants=participants,
                interventions=interventions,
                comparators=comparators,
                explicit_outcomes=explicit_outcomes,
            ),
            temperature=_temperature(config),
        )
        return _extract_slot_values(payload, output_key="expanded_outcomes")

    def _render_outcome_expansion_prompt(
        self,
        *,
        question_text: str,
        participants: list[str],
        interventions: list[str],
        comparators: list[str],
        explicit_outcomes: list[str],
    ) -> str:
        template = (self.prompt_dir / f"{OUTCOME_EXPANSION_PROMPT_VERSION}.txt").read_text(encoding="utf-8")
        return template.format(
            question_text=question_text,
            participants=_json_list(participants),
            interventions=_json_list(interventions),
            comparators=_json_list(comparators),
            explicit_outcomes=_json_list(explicit_outcomes),
        )


def _extract_slot_values(payload: dict[str, Any], *, output_key: str) -> list[str]:
    if output_key not in payload:
        raise ValueError(f"Q2PICO response missing required key: {output_key}")
    raw_values = payload[output_key]
    if not isinstance(raw_values, list):
        raise ValueError(f"Q2PICO response key '{output_key}' must be a list")
    return _normalize_slot_values(raw_values)


def _normalize_slot_values(values: list[Any]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            raise ValueError(f"Q2PICO slot values must be strings; got {type(value).__name__}")
        clean = value.strip()
        if not clean or clean in seen:
            continue
        normalized.append(clean)
        seen.add(clean)
    return normalized


def _json_list(values: list[str]) -> str:
    return json.dumps(values, ensure_ascii=False)


def _temperature(config: LLMConfig | dict[str, Any]) -> float | None:
    if isinstance(config, LLMConfig):
        return config.temperature
    value = config.get("temperature")
    return float(value) if value is not None and str(value).strip() else None


def _normalize_method_config(config: LLMConfig | dict[str, Any]) -> LLMConfig | dict[str, Any]:
    api_mode = config.api_mode if isinstance(config, LLMConfig) else str(config.get("api_mode") or "")
    if api_mode.strip().lower() != "auto":
        return config
    normalized = config.to_dict() if isinstance(config, LLMConfig) else dict(config)
    normalized["api_mode"] = "responses"
    return normalized
