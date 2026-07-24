"""Production GRADE risk-of-bias judgement over one evidence body."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ebm_backend.online_pipeline.domain.grade import GRADERiskOfBiasInput
from ebm_backend.online_pipeline.infrastructure.llm import (
    LLMConfig,
    LLMAPIError,
    call_llm_json,
    load_llm_config,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.risk_of_bias.method_evidence_body_llm.decision import (
    judgement_from_llm,
    not_evaluable_judgement,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.risk_of_bias.method_evidence_body_llm.errors import (
    GRADERiskOfBiasConfigurationError,
    GRADERiskOfBiasInvocationError,
    GRADERiskOfBiasJudgementError,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.risk_of_bias.method_evidence_body_llm.evidence import (
    build_payload,
    lacks_assessable_rob,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.risk_of_bias.method_evidence_body_llm.schema import (
    response_schema,
)


MAX_ATTEMPTS = 2
LLMCaller = Callable[..., dict[str, Any]]
PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "system.txt"


class Method:
    domain = "risk_of_bias"

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
            raise GRADERiskOfBiasConfigurationError(
                "GRADE risk-of-bias LLM configuration is unavailable"
            ) from exc
        self.caller = caller

    def run(self, *, grade_input: GRADERiskOfBiasInput) -> dict[str, Any]:
        if lacks_assessable_rob(grade_input):
            return not_evaluable_judgement(
                "No study-level risk-of-bias assessment is available for the "
                "studies contributing to this evidence body."
            )
        payload = build_payload(grade_input)
        prompt = (
            "Assess this GRADE risk-of-bias evidence body. Input JSON:\n"
            + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        )
        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                parsed = self.caller(
                    config=self.config,
                    system=self.system_prompt,
                    prompt=prompt,
                    json_schema=response_schema(),
                    json_schema_name="grade_risk_of_bias_evidence_body",
                )
                return judgement_from_llm(parsed, grade_input=grade_input)
            except LLMAPIError as exc:
                last_error = exc
                if not exc.retryable:
                    raise GRADERiskOfBiasInvocationError(
                        setting_id=grade_input.setting.setting_id,
                        attempts=attempt,
                        retry_exhausted=False,
                    ) from exc
                if attempt == MAX_ATTEMPTS:
                    raise GRADERiskOfBiasInvocationError(
                        setting_id=grade_input.setting.setting_id,
                        attempts=attempt,
                        retry_exhausted=True,
                    ) from exc
            except ValueError as exc:
                last_error = exc
                if attempt == MAX_ATTEMPTS:
                    raise GRADERiskOfBiasJudgementError(
                        setting_id=grade_input.setting.setting_id,
                        attempts=attempt,
                    ) from exc
        raise GRADERiskOfBiasInvocationError(
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


def _disable_implicit_retries(
    config: LLMConfig | dict[str, Any],
) -> dict[str, Any]:
    payload = config.to_dict() if isinstance(config, LLMConfig) else dict(config)
    payload["sdk_max_retries"] = 0
    payload["json_marker_retry_enabled"] = False
    return payload
