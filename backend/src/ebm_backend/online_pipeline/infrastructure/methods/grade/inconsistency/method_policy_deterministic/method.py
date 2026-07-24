"""Automated GRADE inconsistency policy generation and bounded judgement."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from ebm_backend.online_pipeline.domain.grade import GRADEInconsistencyInput
from ebm_backend.online_pipeline.domain.serialization import to_jsonable
from ebm_backend.online_pipeline.infrastructure.llm import (
    LLMAPIError,
    LLMConfig,
    call_llm_json,
    load_llm_config,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.method_policy_deterministic.decision import (
    judged_inconsistency,
    same_range_judgement,
    single_study_judgement,
    unavailable_judgement,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.method_policy_deterministic.errors import (
    GRADEInconsistencyConfigurationError,
    GRADEInconsistencyInvocationError,
    GRADEInconsistencyJudgementError,
    GRADEInconsistencyPolicyError,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.method_policy_deterministic.evidence import (
    build_evidence_profile,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.method_policy_deterministic.judgement import (
    judgement_schema,
    parse_judgement,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.method_policy_deterministic.policy import (
    no_effect_value,
    parse_policy,
    policy_schema,
)


MAX_ATTEMPTS = 2
LLMCaller = Callable[..., dict[str, Any]]
PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
POLICY_PROMPT_PATH = PROMPTS_DIR / "system.txt"
JUDGE_PROMPT_PATH = PROMPTS_DIR / "judge_system.txt"


class Method:
    domain = "inconsistency"

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
            self.config = _disable_sdk_retry(loaded)
            self.policy_system_prompt = POLICY_PROMPT_PATH.read_text(
                encoding="utf-8"
            ).strip()
            self.judge_system_prompt = JUDGE_PROMPT_PATH.read_text(
                encoding="utf-8"
            ).strip()
        except (FileNotFoundError, OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
            raise GRADEInconsistencyConfigurationError(
                "GRADE inconsistency LLM configuration is unavailable"
            ) from exc
        self.caller = caller

    def run(self, *, grade_input: GRADEInconsistencyInput) -> dict[str, Any]:
        if grade_input.estimate.study_count == 1:
            return single_study_judgement()
        if len(grade_input.study_effects) < 2:
            return unavailable_judgement(
                "At least two available study effects are required to assess inconsistency."
            )
        if grade_input.coverage.missing_data_row_ids:
            return unavailable_judgement(
                "The matched estimate has incomplete DataRow coverage."
            )

        expected_no_effect = no_effect_value(grade_input.setting.effect_measure)
        policy_prompt = (
            "Generate a result-blind executable policy for this GRADE inconsistency "
            "assessment. Input JSON:\n"
            + json.dumps(
                _result_blind_payload(
                    grade_input,
                    expected_no_effect=expected_no_effect,
                ),
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        policy = self._generate_policy(
            grade_input=grade_input,
            prompt=policy_prompt,
            expected_no_effect=expected_no_effect,
        )
        evidence_profile = build_evidence_profile(
            grade_input=grade_input,
            policy=policy,
        )
        serialized_policy = to_jsonable(policy)
        if len(evidence_profile["observed_ranges"]) == 1:
            return same_range_judgement(
                policy=serialized_policy,
                evidence_profile=evidence_profile,
            )
        judge_prompt = (
            "Apply the frozen policy to the deterministic evidence profile and "
            "make the final GRADE inconsistency judgement. Input JSON:\n"
            + json.dumps(
                {
                    "frozen_policy": serialized_policy,
                    "evidence_profile": evidence_profile,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        judge_output = self._judge(
            grade_input=grade_input,
            prompt=judge_prompt,
            evidence_profile=evidence_profile,
        )
        return judged_inconsistency(
            judge_output=judge_output,
            policy=serialized_policy,
            evidence_profile=evidence_profile,
        )

    def _generate_policy(
        self,
        *,
        grade_input: GRADEInconsistencyInput,
        prompt: str,
        expected_no_effect: float,
    ):
        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                parsed = self.caller(
                    config=self.config,
                    system=self.policy_system_prompt,
                    prompt=prompt,
                    json_schema=policy_schema(),
                    json_schema_name="grade_inconsistency_result_blind_policy",
                )
                return parse_policy(
                    parsed,
                    expected_no_effect=expected_no_effect,
                )
            except LLMAPIError as exc:
                last_error = exc
                if not exc.retryable:
                    raise GRADEInconsistencyInvocationError(
                        setting_id=grade_input.setting.setting_id,
                        stage="policy_generation",
                        attempts=attempt,
                        retry_exhausted=False,
                    ) from exc
            except ValueError as exc:
                last_error = exc
                if attempt == MAX_ATTEMPTS:
                    raise GRADEInconsistencyPolicyError(
                        setting_id=grade_input.setting.setting_id,
                        attempts=attempt,
                    ) from exc
        raise GRADEInconsistencyInvocationError(
            setting_id=grade_input.setting.setting_id,
            stage="policy_generation",
            attempts=MAX_ATTEMPTS,
            retry_exhausted=True,
        ) from last_error

    def _judge(
        self,
        *,
        grade_input: GRADEInconsistencyInput,
        prompt: str,
        evidence_profile: dict[str, Any],
    ) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                parsed = self.caller(
                    config=self.config,
                    system=self.judge_system_prompt,
                    prompt=prompt,
                    json_schema=judgement_schema(),
                    json_schema_name="grade_inconsistency_bounded_judgement",
                )
                return parse_judgement(
                    parsed,
                    evidence_profile=evidence_profile,
                )
            except LLMAPIError as exc:
                last_error = exc
                if not exc.retryable:
                    raise GRADEInconsistencyInvocationError(
                        setting_id=grade_input.setting.setting_id,
                        stage="judgement",
                        attempts=attempt,
                        retry_exhausted=False,
                    ) from exc
            except ValueError as exc:
                last_error = exc
                if attempt == MAX_ATTEMPTS:
                    raise GRADEInconsistencyJudgementError(
                        setting_id=grade_input.setting.setting_id,
                        attempts=attempt,
                    ) from exc
        raise GRADEInconsistencyInvocationError(
            setting_id=grade_input.setting.setting_id,
            stage="judgement",
            attempts=MAX_ATTEMPTS,
            retry_exhausted=True,
        ) from last_error


def build_method(
    *,
    config: LLMConfig | dict[str, Any] | None = None,
    caller: LLMCaller = call_llm_json,
) -> Method:
    return Method(config=config, caller=caller)


def _result_blind_payload(
    grade_input: GRADEInconsistencyInput,
    *,
    expected_no_effect: float,
) -> dict[str, Any]:
    subgroup_candidates: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for estimate in grade_input.subgroup_estimates:
        key = (estimate.subgroup.factor or "", estimate.subgroup.level or "")
        if key == ("", "") or key in seen:
            continue
        seen.add(key)
        subgroup_candidates.append({"factor": key[0], "level": key[1]})
    planned_factors = sorted(
        {
            test.subgroup_factor.strip()
            for test in grade_input.subgroup_difference_tests
            if test.subgroup_factor.strip()
        }
    )
    return {
        "task": (
            "Before seeing study effects, define clinically meaningful effect "
            "ranges and plausible effect modifiers for GRADE inconsistency."
        ),
        "setting": to_jsonable(grade_input.setting),
        "required_no_effect_value": expected_no_effect,
        "study_pio": [
            to_jsonable(item) for item in grade_input.study_characteristics
        ],
        "planned_subgroups": {
            "factors": planned_factors,
            "factor_levels": subgroup_candidates,
        },
        "result_blinding": {
            "observed_study_effects_provided": False,
            "pooled_effect_provided": False,
            "heterogeneity_statistics_provided": False,
            "subgroup_results_provided": False,
        },
    }


def _disable_sdk_retry(config: LLMConfig | dict[str, Any]) -> dict[str, Any]:
    payload = config.to_dict() if isinstance(config, LLMConfig) else dict(config)
    payload["sdk_max_retries"] = 0
    payload["json_marker_retry_enabled"] = False
    return payload
