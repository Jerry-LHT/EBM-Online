"""Production expert-threshold plus deterministic-CI imprecision method."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ebm_backend.online_pipeline.domain.grade import GRADEImprecisionInput
from ebm_backend.online_pipeline.domain.serialization import to_jsonable
from ebm_backend.online_pipeline.infrastructure.llm import (
    LLMAPIError,
    LLMConfig,
    call_llm_json,
    load_llm_config,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_expert_threshold_ci.calculator import (
    build_numeric_profile,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_expert_threshold_ci.decision import (
    decide_imprecision,
    unclear_judgement,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_expert_threshold_ci.errors import (
    GRADEImprecisionConfigurationError,
    GRADEImprecisionInvocationError,
    GRADEImprecisionThresholdError,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.imprecision.method_expert_threshold_ci.threshold import (
    ThresholdProfile,
    expected_effect_direction_convention,
    expected_threshold_scale,
    parse_threshold,
    threshold_schema,
)


MAX_ATTEMPTS = 2
LLMCaller = Callable[..., dict[str, Any]]
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "threshold_system.txt"


class Method:
    domain = "imprecision"

    def __init__(
        self,
        *,
        config: LLMConfig | dict[str, Any] | None = None,
        caller: LLMCaller = call_llm_json,
    ) -> None:
        try:
            loaded = config if config is not None else load_llm_config()
            if loaded is None:
                raise RuntimeError("Missing required LLM configuration")
            self.config = _disable_implicit_retries(loaded)
            self.system_prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
        except (FileNotFoundError, OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
            raise GRADEImprecisionConfigurationError(
                "GRADE imprecision LLM configuration is unavailable"
            ) from exc
        self.caller = caller

    def run(self, *, grade_input: GRADEImprecisionInput) -> dict[str, Any]:
        numeric_profile = build_numeric_profile(grade_input)
        if numeric_profile.get("status") != "usable":
            return unclear_judgement(
                str(numeric_profile.get("reason") or "numeric_evidence_unavailable"),
                numeric_profile=numeric_profile,
            )
        scale = expected_threshold_scale(grade_input.setting.effect_measure)
        if scale is None:
            return unclear_judgement(
                "unsupported_effect_measure",
                numeric_profile=numeric_profile,
            )
        effect_direction_convention = expected_effect_direction_convention(
            grade_input.setting.effect_measure
        )
        if effect_direction_convention is None:
            return unclear_judgement(
                "effect_direction_convention_unavailable",
                numeric_profile=numeric_profile,
            )
        threshold = self._generate_threshold(
            grade_input=grade_input,
            expected_scale=scale,
            effect_direction_convention=effect_direction_convention,
        )
        if threshold.status == "unavailable":
            return unclear_judgement(
                "threshold_unavailable",
                numeric_profile=numeric_profile,
                threshold=threshold,
            )
        if threshold.confidence == "low":
            return unclear_judgement(
                "threshold_low_confidence",
                numeric_profile=numeric_profile,
                threshold=threshold,
            )
        return decide_imprecision(
            numeric_profile=numeric_profile,
            threshold=threshold,
        )

    def _generate_threshold(
        self,
        *,
        grade_input: GRADEImprecisionInput,
        expected_scale: str,
        effect_direction_convention: str,
    ) -> ThresholdProfile:
        prompt = threshold_prompt(
            grade_input=grade_input,
            expected_scale=expected_scale,
            effect_direction_convention=effect_direction_convention,
        )
        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                tools = (
                    [{"type": "web_search"}]
                    if str(self.config.get("api_mode") or "responses") == "responses"
                    else None
                )
                raw = self.caller(
                    config=self.config,
                    system=self.system_prompt,
                    prompt=prompt,
                    tools=tools,
                    temperature=0,
                    json_schema=threshold_schema(),
                    json_schema_name="grade_imprecision_clinical_threshold",
                )
                return parse_threshold(
                    raw,
                    expected_scale=expected_scale,
                    effect_direction_convention=effect_direction_convention,
                )
            except LLMAPIError as exc:
                last_error = exc
                if not exc.retryable:
                    raise GRADEImprecisionInvocationError(
                        setting_id=grade_input.setting.setting_id,
                        attempts=attempt,
                        retry_exhausted=False,
                    ) from exc
                if attempt == MAX_ATTEMPTS:
                    raise GRADEImprecisionInvocationError(
                        setting_id=grade_input.setting.setting_id,
                        attempts=attempt,
                        retry_exhausted=True,
                    ) from exc
            except ValueError as exc:
                last_error = exc
                if attempt == MAX_ATTEMPTS:
                    raise GRADEImprecisionThresholdError(
                        setting_id=grade_input.setting.setting_id,
                        attempts=attempt,
                    ) from exc
        raise GRADEImprecisionInvocationError(
            setting_id=grade_input.setting.setting_id,
            attempts=MAX_ATTEMPTS,
            retry_exhausted=True,
        ) from last_error


def build_method(
    *,
    config: LLMConfig | dict[str, Any] | None = None,
    caller: LLMCaller = call_llm_json,
) -> Method:
    return Method(config=config, caller=caller)


def threshold_prompt(
    *,
    grade_input: GRADEImprecisionInput,
    expected_scale: str,
    effect_direction_convention: str,
) -> str:
    payload = {
        "task": (
            "Act as a GRADE methods expert and establish result-blind clinical "
            "importance thresholds for this evidence body."
        ),
        "certainty_target": "important_effect",
        "setting": to_jsonable(grade_input.setting),
        "required_threshold_scale": expected_scale,
        "analysis_effect_direction_convention": effect_direction_convention,
        "threshold_value_contract": (
            "Return positive magnitudes only. Engineering code maps each magnitude "
            "to the signed meta-analysis effect scale."
        ),
        "result_blinding": {
            "pooled_effect_provided": False,
            "confidence_interval_provided": False,
            "participant_count_provided": False,
            "event_counts_provided": False,
            "study_pio_provided": False,
            "risk_of_bias_provided": False,
        },
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _disable_implicit_retries(
    config: LLMConfig | dict[str, Any],
) -> dict[str, Any]:
    payload = config.to_dict() if isinstance(config, LLMConfig) else dict(config)
    payload["sdk_max_retries"] = 0
    payload["json_marker_retry_enabled"] = False
    return payload
