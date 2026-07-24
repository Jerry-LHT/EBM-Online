from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.errors import (
    MetaAnalysisOutputError,
)

from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.synthesis_planning.synthesis_plan_llm.method import (
    Method as SynthesisPlanningMethod,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.analysis_method_selection.contextual.method import (
    Method as AnalysisMethod,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.subgroup_analysis.statistical.method import (
    Method as SubgroupMethod,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.overall_estimation.statistical.method import (
    Method as OverallMethod,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.study_evidence.article_evidence_agent.method import (
    _validate_targets,
)


FIXTURES = Path(__file__).resolve().parents[2] / "fixtures/meta_analysis"


def _fixture(name: str) -> dict:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    rows = []
    for row in payload.get("study_result_rows") or []:
        normalized = dict(row)
        normalized["data_row_id"] = normalized.get("data_row_id") or normalized.get("row_id")
        if normalized.get("data_type") == "Continuous":
            normalized.setdefault(
                "continuous_effect_alignment",
                {
                    "result_frame": "post_intervention",
                    "change_score_definition": "not_applicable",
                    "scale_direction": "higher_is_better",
                    "effect_multiplier": 1,
                    "status": "ready",
                },
            )
        rows.append(normalized)
    payload["meta_analysis_data_rows"] = rows
    return payload


def _setting_with_plan(
    setting: dict,
    *,
    effect_measure: str,
    model: str | None = None,
) -> dict:
    source_context = deepcopy(setting.get("source_context") or {})
    definition = deepcopy(source_context.get("setting_definition") or {})
    definition["planned_effect_measure"] = effect_measure
    if setting.get("data_type") == "Continuous":
        definition.setdefault("continuous_result_frame_priority", ["post_intervention"])
    if model is not None:
        definition["clinical_model_assumption"] = model
    source_context["setting_definition"] = definition
    return {**setting, "source_context": source_context}


def _selection_policy(
    measure: str,
    *,
    target_value: float,
    unit: str,
    statistic_type: str,
    basis: str = "screening_criteria",
) -> dict:
    continuous = "mean" in statistic_type.casefold()
    policy = {
        "acceptable_outcome_measures": [measure],
        "outcome_measure_priority": [measure],
        "analysis_population_priority": ["intention-to-treat"],
        "statistic_type_priority": [statistic_type],
        "source_priority": ["primary results table"],
        "continuous_result_frame_priority": ["post_intervention"] if continuous else [],
        "tie_policy": "unresolved",
        "decision_basis": {
            "outcome_measure": "Use the prespecified outcome definition.",
            "timepoint": "Use the prespecified clinical follow-up.",
            "analysis_population": "Estimate assignment to intervention.",
            "statistic_type": "Use directly estimable arm-level data.",
            "source": "Prefer the primary complete results source.",
        },
    }
    if continuous:
        policy["decision_basis"]["continuous_result_frame"] = (
            "Use post-intervention values for this planned analysis."
        )
    return policy


def _timepoint(
    label: str,
    *,
    target_value: float,
    unit: str,
    basis: str = "screening_criteria",
) -> dict:
    return {
        "label": label,
        "strategy": "closest_to_target",
        "target_value": target_value,
        "window_start": target_value,
        "window_end": target_value,
        "unit": unit,
        "anchor": "randomization",
        "basis": basis,
        "rationale": "Use the prespecified clinical follow-up.",
    }


def test_synthesis_plan_is_result_blind_and_frozen_before_extraction() -> None:
    calls = []
    system_prompts = []
    reasoning_efforts = []
    schemas = []

    def fake_llm(**kwargs):
        payload = json.loads(kwargs["prompt"])
        calls.append(payload)
        system_prompts.append(kwargs["system"])
        reasoning_efforts.append(kwargs["reasoning_effort"])
        schemas.append(kwargs["json_schema"])
        return {
            "targets": [
                {
                    "population_scope": "children",
                    "experimental": "antibiotics",
                    "comparator": "placebo",
                    "outcome_label": "pain",
                    "outcome_measure": "pain present",
                    "timepoint": _timepoint("3 days", target_value=3, unit="days"),
                    "subgroup_factor": None,
                    "subgroup_level": None,
                    "data_type": "Dichotomous",
                    "result_selection_policy": _selection_policy(
                        "pain present",
                        target_value=3,
                        unit="days",
                        statistic_type="events and total",
                    ),
                    "effect_measure_plan": "Risk Ratio",
                    "analysis_model_plan": "varying_effects",
                    "rationale": "Clinical settings and disease severity may vary.",
                }
            ],
            "unsupported_targets": [],
            "rationale": "Plan the primary pain outcome.",
        }

    method = SynthesisPlanningMethod(config={"model": "fake"}, llm_caller=fake_llm)
    plan = method.run(
        context={
            "review_id": "review-1",
            "question_text": "Do antibiotics reduce pain?",
            "question_pico": {"P": ["children"], "I": ["antibiotics"], "C": ["placebo"], "O": ["pain"]},
            "screening_criteria": {
                "inclusion_criteria": ["Randomized trials"],
                "exclusion_criteria": [],
            },
        },
    )

    assert [call["stage"] for call in calls] == ["meta_analysis_synthesis_planning"]
    assert "articles" not in calls[0]
    assert "included_studies" not in calls[0]
    assert "`Dichotomous`" in system_prompts[0]
    assert "`Continuous`" in system_prompts[0]
    assert "unsupported_targets" in system_prompts[0]
    assert "before any" in system_prompts[0]
    assert reasoning_efforts == ["none"]
    assert schemas[0]["additionalProperties"] is False
    assert schemas[0]["properties"]["targets"]["items"]["additionalProperties"] is False
    assert plan["status"] == "frozen"
    assert plan["plan_hash"]
    assert plan["version"] == "5"
    assert plan["targets"][0]["target_id"].startswith("setting::review-1::")
    assert plan["targets"][0]["analysis_model_plan"] == "varying_effects"
    assert "heterogeneity_plan" not in plan["targets"][0]
    assert "timepoint" not in plan["targets"][0]["result_selection_policy"]


def test_synthesis_plan_retries_one_invalid_llm_response() -> None:
    calls = 0
    prompts = []

    def fake_llm(**kwargs):
        nonlocal calls
        calls += 1
        prompts.append(json.loads(kwargs["prompt"]))
        if calls == 1:
            return {}
        return {
            "targets": [
                {
                    "population_scope": "adults",
                    "experimental": "treatment",
                    "comparator": "control",
                    "outcome_label": "response",
                    "outcome_measure": "clinical response",
                    "timepoint": _timepoint("12 weeks", target_value=12, unit="weeks"),
                    "subgroup_factor": None,
                    "subgroup_level": None,
                    "data_type": "Dichotomous",
                    "result_selection_policy": _selection_policy(
                        "clinical response",
                        target_value=12,
                        unit="weeks",
                        statistic_type="events and total",
                    ),
                    "effect_measure_plan": "Risk Ratio",
                    "analysis_model_plan": "varying_effects",
                    "rationale": "Prespecified primary analysis.",
                }
            ],
            "unsupported_targets": [],
            "rationale": "Retry recovered a valid plan.",
        }

    plan = SynthesisPlanningMethod(
        config={"model": "fake"},
        llm_caller=fake_llm,
    ).run(
        context={
            "review_id": "review-retry",
            "question_text": "Does treatment improve response?",
            "question_pico": {},
            "screening_criteria": {},
        }
    )

    assert calls == 2
    assert "repair" not in prompts[0]
    assert "must contain a targets list" in prompts[1]["repair"]["validation_error"]
    assert "previous_response" not in prompts[1]["repair"]
    assert prompts[1]["repair"]["previous_response_shape"] == {
        "type": "object",
        "keys": [],
        "omitted_key_count": 0,
    }
    assert plan["status"] == "frozen"


def test_synthesis_plan_uses_one_family_for_overall_and_subgroup_levels() -> None:
    base = {
        "population_scope": "adults",
        "experimental": "treatment",
        "comparator": "control",
        "outcome_label": "response",
        "outcome_measure": "clinical response",
        "timepoint": _timepoint("12 weeks", target_value=12, unit="weeks"),
        "data_type": "Dichotomous",
        "result_selection_policy": _selection_policy(
            "clinical response",
            target_value=12,
            unit="weeks",
            statistic_type="events and total",
        ),
        "effect_measure_plan": "Risk Ratio",
        "analysis_model_plan": "varying_effects",
        "rationale": "Prespecified clinical response analysis.",
    }
    targets = [
        {**base, "subgroup_factor": None, "subgroup_level": None},
        {**base, "subgroup_factor": "age", "subgroup_level": "under 65"},
        {**base, "subgroup_factor": "age", "subgroup_level": "65 or older"},
    ]
    for index, target in enumerate(targets):
        target["result_selection_policy"] = deepcopy(base["result_selection_policy"])
        target["timepoint"] = deepcopy(base["timepoint"])
        target["timepoint"]["rationale"] = (
            f"Equivalent prespecified follow-up explanation {index}."
        )
        target["result_selection_policy"]["decision_basis"]["timepoint"] = (
            f"Equivalent decision-basis wording {index}."
        )
    method = SynthesisPlanningMethod(
        config={"model": "fake"},
        llm_caller=lambda **kwargs: {
            "targets": targets,
            "unsupported_targets": [],
            "rationale": "Overall and prespecified age subgroup analyses.",
        },
    )

    plan = method.run(
        context={
            "review_id": "review-family",
            "question_text": "Does treatment improve response?",
            "question_pico": {},
            "screening_criteria": {},
        }
    )

    assert len({target["setting_family_id"] for target in plan["targets"]}) == 1
    assert len({target["target_id"] for target in plan["targets"]}) == 3


def test_synthesis_plan_closes_priority_items_into_acceptable_measures() -> None:
    policy = _selection_policy(
        "BDI total score",
        target_value=8,
        unit="weeks",
        statistic_type="mean, SD, and total",
    )
    policy["acceptable_outcome_measures"] = ["BDI total score"]
    policy["outcome_measure_priority"] = [
        "study-prespecified primary depression instrument",
        "BDI total score",
    ]
    plan = SynthesisPlanningMethod(
        config={"model": "fake"},
        llm_caller=lambda **kwargs: {
            "targets": [
                {
                    "population_scope": "adults with depression",
                    "experimental": "psychotherapy",
                    "comparator": "usual care",
                    "outcome_label": "depressive symptom severity",
                    "outcome_measure": "BDI total score",
                    "timepoint": _timepoint("8 weeks", target_value=8, unit="weeks"),
                    "subgroup_factor": None,
                    "subgroup_level": None,
                    "data_type": "Continuous",
                    "result_selection_policy": policy,
                    "effect_measure_plan": "Std. Mean Difference",
                    "analysis_model_plan": "varying_effects",
                    "rationale": "Use validated depression instruments.",
                }
            ],
            "unsupported_targets": [],
            "rationale": "Plan the depression-severity outcome.",
        },
    ).run(
        context={
            "review_id": "measure-closure",
            "question_text": "Does psychotherapy improve depression?",
            "question_pico": {},
            "screening_criteria": {},
        }
    )

    selection = plan["targets"][0]["result_selection_policy"]
    assert selection["outcome_measure_priority"] == [
        "study-prespecified primary depression instrument",
        "BDI total score",
    ]
    assert "study-prespecified primary depression instrument" in selection[
        "acceptable_outcome_measures"
    ]


def test_synthesis_plan_keeps_target_measure_first_when_model_uses_statistic_shape() -> None:
    policy = _selection_policy(
        "mean, standard deviation, and analyzed participant total",
        target_value=1,
        unit="days",
        statistic_type="mean, SD, and total",
    )
    plan = SynthesisPlanningMethod(
        config={"model": "fake"},
        llm_caller=lambda **kwargs: {
            "targets": [
                {
                    "population_scope": "adults undergoing surgery",
                    "experimental": "treatment",
                    "comparator": "control",
                    "outcome_label": "length of hospital stay",
                    "outcome_measure": "Days",
                    "timepoint": _timepoint(
                        "hospital discharge", target_value=1, unit="days"
                    ),
                    "subgroup_factor": None,
                    "subgroup_level": None,
                    "data_type": "Continuous",
                    "result_selection_policy": policy,
                    "effect_measure_plan": "Mean Difference",
                    "analysis_model_plan": "common_effect",
                    "rationale": "Use hospital-stay duration in days.",
                }
            ],
            "unsupported_targets": [],
            "rationale": "Plan hospital stay.",
        },
    ).run(
        context={
            "review_id": "measure-vs-statistic",
            "question_text": "Does treatment reduce hospital stay?",
            "question_pico": {},
            "screening_criteria": {},
        }
    )

    selection = plan["targets"][0]["result_selection_policy"]
    assert selection["outcome_measure_priority"][0] == "Days"
    assert selection["acceptable_outcome_measures"][0] == "Days"
    assert selection["statistic_type_priority"] == ["mean, SD, and total"]


def test_synthesis_plan_rejects_effect_measure_incompatible_with_data_type() -> None:
    method = SynthesisPlanningMethod(
        config={"model": "fake"},
        llm_caller=lambda **kwargs: {
            "targets": [
                {
                    "population_scope": "adults",
                    "experimental": "treatment",
                        "comparator": "control",
                        "outcome_label": "response",
                        "timepoint": _timepoint(
                            "12 weeks", target_value=12, unit="weeks"
                        ),
                        "data_type": "Dichotomous",
                    "effect_measure_plan": "Mean Difference",
                    "analysis_model_plan": "common_effect",
                    "rationale": "Invalid pairing.",
                }
            ],
            "unsupported_targets": [],
            "rationale": "",
        },
    )

    with pytest.raises(MetaAnalysisOutputError):
        method.run(
            context={
                "review_id": "review-invalid",
                "question_text": "question",
                "question_pico": {},
                "screening_criteria": {},
            }
        )


def test_synthesis_plan_keeps_distinct_outcome_measures_in_distinct_families() -> None:
    base = {
        "population_scope": "adults",
        "experimental": "treatment",
        "comparator": "control",
        "outcome_label": "pain",
        "timepoint": _timepoint("4 weeks", target_value=4, unit="weeks"),
        "data_type": "Continuous",
        "effect_measure_plan": "Mean Difference",
        "analysis_model_plan": "common_effect",
        "rationale": "Prespecified same-scale pain outcome.",
    }
    targets = [
        {
            **base,
            "outcome_measure": "0 to 10 pain scale",
            "result_selection_policy": _selection_policy(
                "0 to 10 pain scale",
                target_value=4,
                unit="weeks",
                statistic_type="mean, SD, and total",
            ),
        },
        {
            **base,
            "outcome_measure": "0 to 100 pain scale",
            "result_selection_policy": _selection_policy(
                "0 to 100 pain scale",
                target_value=4,
                unit="weeks",
                statistic_type="mean, SD, and total",
            ),
        },
    ]
    method = SynthesisPlanningMethod(
        config={"model": "fake"},
        llm_caller=lambda **kwargs: {
            "targets": targets,
            "unsupported_targets": [],
            "rationale": "Two separately prespecified units.",
        },
    )

    plan = method.run(
        context={
            "review_id": "review-measures",
            "question_text": "Does treatment reduce pain?",
            "question_pico": {},
            "screening_criteria": {},
        }
    )

    assert len(plan["targets"]) == 2
    assert len({target["setting_family_id"] for target in plan["targets"]}) == 2


def test_synthesis_planner_rejects_observed_study_inputs() -> None:
    method = SynthesisPlanningMethod(
        config={"model": "fake"},
        llm_caller=lambda **kwargs: {"targets": []},
    )

    with pytest.raises(ValueError, match="result-blind"):
        method.run(
            context={
                "review_id": "review-1",
                "question_text": "question",
                "question_pico": {},
                "screening_criteria": {},
                "included_studies": ["study-1"],
            }
        )


def test_synthesis_planner_records_unsupported_type_without_emitting_target() -> None:
    method = SynthesisPlanningMethod(
        config={"model": "fake"},
        llm_caller=lambda **kwargs: {
            "targets": [],
            "unsupported_targets": [
                {
                    "outcome_label": "overall survival",
                    "data_type": "Time-to-event",
                    "reason": "Hazard-ratio data are outside the current data model.",
                }
            ],
            "rationale": "The only outcome is unsupported.",
        },
    )

    plan = method.run(
        context={
            "review_id": "review-1",
            "question_text": "Does treatment improve overall survival?",
            "question_pico": {
                "P": ["adults"],
                "I": ["treatment"],
                "C": ["control"],
                "O": ["overall survival"],
            },
            "screening_criteria": {},
        }
    )

    assert plan["status"] == "not_plannable"
    assert plan["targets"] == []
    assert plan["unsupported_targets"][0]["data_type"] == "Time-to-event"


def test_synthesis_plan_records_a_result_blind_clinical_default() -> None:
    policy = _selection_policy(
        "clinical response",
        target_value=12,
        unit="weeks",
        statistic_type="events and total",
        basis="clinical_convention",
    )
    timepoint = _timepoint(
        "12 weeks",
        target_value=12,
        unit="weeks",
        basis="clinical_convention",
    )
    timepoint["rationale"] = (
        "Twelve weeks represents a clinically interpretable short-term response assessment."
    )
    method = SynthesisPlanningMethod(
        config={"model": "fake"},
        llm_caller=lambda **kwargs: {
            "targets": [
                {
                    "population_scope": "adults",
                    "experimental": "treatment",
                    "comparator": "control",
                    "outcome_label": "clinical response",
                    "outcome_measure": "clinical response",
                    "timepoint": timepoint,
                    "subgroup_factor": None,
                    "subgroup_level": None,
                    "data_type": "Dichotomous",
                    "result_selection_policy": policy,
                    "effect_measure_plan": "Risk Ratio",
                    "analysis_model_plan": "varying_effects",
                    "rationale": "Use a clinically conventional short-term target.",
                }
            ],
            "unsupported_targets": [],
            "rationale": "Result-blind clinical convention.",
        },
    )
    plan = method.run(
        context={
            "review_id": "clinical-default",
            "question_text": "Does treatment improve response?",
            "question_pico": {},
            "screening_criteria": {},
        }
    )
    timepoint = plan["targets"][0]["timepoint"]
    assert timepoint["basis"] == "clinical_convention"
    assert timepoint["strategy"] == "closest_to_target"


def test_synthesis_plan_rejects_an_invalid_timepoint_window() -> None:
    policy = _selection_policy(
        "clinical response",
        target_value=12,
        unit="weeks",
        statistic_type="events and total",
    )
    timepoint = _timepoint("12 weeks", target_value=12, unit="weeks")
    timepoint["window_start"] = 14
    with pytest.raises(MetaAnalysisOutputError):
        SynthesisPlanningMethod(
            config={"model": "fake"},
            llm_caller=lambda **kwargs: {
                "targets": [
                    {
                        "population_scope": "adults",
                        "experimental": "treatment",
                        "comparator": "control",
                        "outcome_label": "clinical response",
                        "outcome_measure": "clinical response",
                        "timepoint": timepoint,
                        "subgroup_factor": None,
                        "subgroup_level": None,
                        "data_type": "Dichotomous",
                        "result_selection_policy": policy,
                        "effect_measure_plan": "Risk Ratio",
                        "analysis_model_plan": "varying_effects",
                        "rationale": "Invalid window.",
                    }
                ],
                "unsupported_targets": [],
                "rationale": "",
            },
        ).run(
            context={
                "review_id": "invalid-window",
                "question_text": "question",
                "question_pico": {},
                "screening_criteria": {},
            }
        )


def test_supported_shape_can_stop_for_insufficient_planning_basis() -> None:
    plan = SynthesisPlanningMethod(
        config={"model": "fake"},
        llm_caller=lambda **kwargs: {
            "targets": [],
            "unsupported_targets": [
                {
                    "outcome_label": "symptom improvement",
                    "data_type": "Continuous",
                    "reason_code": "insufficient_planning_basis",
                    "reason": "No defensible outcome measure or follow-up convention can be frozen.",
                }
            ],
            "rationale": "Planning basis is insufficient.",
        },
    ).run(
        context={
            "review_id": "insufficient-plan",
            "question_text": "Does treatment improve symptoms?",
            "question_pico": {},
            "screening_criteria": {},
        }
    )
    assert plan["status"] == "not_plannable"
    assert plan["unsupported_targets"][0]["reason_code"] == "insufficient_planning_basis"


def test_study_result_extraction_rejects_unsupported_data_type() -> None:
    with pytest.raises(ValueError, match="Unsupported target data type"):
        _validate_targets([{"target_id": "target-1", "data_type": "Time-to-event"}])


def test_statistical_methods_reject_unsupported_data_type() -> None:
    setting = {
        "setting_id": "setting-1",
        "data_type": "Time-to-event",
        "subgroup": {"factor": None, "level": None},
    }

    with pytest.raises(ValueError, match="only Dichotomous or Continuous"):
        OverallMethod().run(instance={"analysis_setting": setting})
    with pytest.raises(ValueError, match="only Dichotomous or Continuous"):
        SubgroupMethod().run(
            instances=[{"instance_id": "instance-1", "analysis_setting": setting}]
        )


def test_analysis_method_selects_fixed_md_from_pre_pooling_context() -> None:
    fixture = _fixture("cd006689_birth_weight.json")
    setting = _setting_with_plan(
        fixture["setting"], effect_measure="Mean Difference"
    )
    methods = AnalysisMethod().run(
        instance={"analysis_setting": setting, "meta_analysis_data_rows": fixture["meta_analysis_data_rows"]}
    )

    assert methods[0]["method_status"] == "ready"
    assert methods[0]["effect_measure"] == "Mean Difference"
    assert methods[0]["analysis_model"] == "fixed_effect"
    assert methods[0]["analysis_included_study_ids"] == ["Denoeud-Ndam 2014a", "González 2014"]
    assert methods[0]["interval_method"] == "Wald"


def test_fixed_effect_md_matches_copied_cochrane_case() -> None:
    fixture = _fixture("cd006689_birth_weight.json")
    setting = _setting_with_plan(
        fixture["setting"], effect_measure="Mean Difference"
    )
    instance = {"analysis_setting": setting, "meta_analysis_data_rows": fixture["meta_analysis_data_rows"]}
    methods = AnalysisMethod().run(instance=instance)
    estimate = OverallMethod().run(instance={**instance, "analysis_methods": methods})["overall_estimates"][0]
    official = fixture["official_fixed_effect"]

    assert estimate["estimation_status"] == "computed"
    assert estimate["participant_count"] == 1220
    assert estimate["effect_value"] == pytest.approx(official["effect_value"], abs=1e-5)
    assert estimate["ci_lower"] == pytest.approx(official["ci_lower"], abs=1e-5)
    assert estimate["ci_upper"] == pytest.approx(official["ci_upper"], abs=1e-5)
    assert estimate["effect_test"]["statistic_name"] == "z"
    assert "candidate_id" not in estimate


def test_direct_and_arm_level_md_rows_share_inverse_variance_pooling() -> None:
    setting = {
        "setting_id": "setting::mixed-md",
        "setting_family_id": "family::mixed-md",
        "data_type": "Continuous",
        "subgroup": {"factor": None, "level": None},
        "source_context": {
            "setting_definition": {
                "planned_effect_measure": "Mean Difference",
                "clinical_model_assumption": "common_effect",
                "continuous_result_frame_priority": ["post_intervention"],
            }
        },
    }
    alignment = {
        "result_frame": "post_intervention",
        "change_score_definition": "not_applicable",
        "scale_direction": "higher_is_better",
        "effect_multiplier": 1,
        "status": "ready",
    }
    rows = [
        {
            "data_row_id": "row::arm",
            "study_id": "study::arm",
            "setting_id": setting["setting_id"],
            "data_type": "Continuous",
            "extraction_status": "extracted",
            "subgroup": {"factor": None, "level": None},
            "continuous_effect_alignment": alignment,
            "result_data": {
                "experimental_mean": 8.0,
                "experimental_sd": 2.0,
                "experimental_total": 50,
                "control_mean": 10.0,
                "control_sd": 2.0,
                "control_total": 50,
            },
        },
        {
            "data_row_id": "row::giv",
            "study_id": "study::giv",
            "setting_id": setting["setting_id"],
            "data_type": "Continuous",
            "extraction_status": "extracted",
            "subgroup": {"factor": None, "level": None},
            "continuous_effect_alignment": alignment,
            "result_data": {
                "effect_value": -1.5,
                "standard_error": 0.4,
                "effect_measure": "Mean Difference",
                "analysis_scale": "natural",
                "participant_count": 80,
            },
        },
    ]
    instance = {"analysis_setting": setting, "meta_analysis_data_rows": rows}
    methods = AnalysisMethod().run(instance=instance)
    result = OverallMethod().run(instance={**instance, "analysis_methods": methods})
    estimate = result["overall_estimates"][0]

    assert methods[0]["analysis_included_study_ids"] == ["study::arm", "study::giv"]
    assert estimate["estimation_status"] == "computed"
    assert estimate["study_count"] == 2
    assert estimate["participant_count"] == 180
    assert estimate["effect_value"] == pytest.approx(-1.75)
    assert {row["data_row_id"] for row in result["meta_analysis_data_rows"]} == {
        "row::arm",
        "row::giv",
    }


def test_double_zero_study_is_excluded_for_relative_effect() -> None:
    fixture = _fixture("cd000219_zero_events.json")
    setting = _setting_with_plan(
        fixture["setting"], effect_measure="Risk Ratio"
    )
    instance = {"analysis_setting": setting, "meta_analysis_data_rows": fixture["meta_analysis_data_rows"]}
    methods = AnalysisMethod().run(instance=instance)
    estimate = OverallMethod().run(instance={**instance, "analysis_methods": methods})["overall_estimates"][0]

    assert methods[0]["analysis_included_study_ids"] == ["Shahbaznejad 2021"]
    assert methods[0]["analysis_excluded_studies"][0]["note"] == "no_relative_effect_information"
    assert estimate["estimation_status"] == "computed"
    assert estimate["study_count"] == 1
    assert estimate["effect_direction_convention"] == (
        "experimental_relative_to_control"
    )


def test_subgroup_method_runs_formal_interaction_test_for_independent_levels() -> None:
    base = _fixture("cd001431_decisional_conflict.json")
    instances = []
    for index, (level, shift) in enumerate((("newer", 0.0), ("older", 8.0)), start=1):
        setting = {
            **base["setting"],
            "setting_id": f"setting::subgroup::{index}",
            "subgroup": {"factor": "study period", "level": level},
            "source_context": {
                "setting_definition": {
                    "planned_effect_measure": "Mean Difference",
                    "clinical_model_assumption": "common_effect",
                    "continuous_result_frame_priority": ["post_intervention"],
                }
            },
        }
        rows = []
        for row_index, row in enumerate(base["meta_analysis_data_rows"]):
            data = dict(row["result_data"])
            data["experimental_mean"] += shift
            rows.append({**row, "row_id": f"row::{index}::{row_index}", "setting_id": setting["setting_id"], "study_id": f"{level}-{row_index}", "extraction_status": "extracted", "subgroup": setting["subgroup"], "result_data": data})
        method = AnalysisMethod().run(instance={"analysis_setting": setting, "meta_analysis_data_rows": rows})
        instances.append({"instance_id": f"instance-{index}", "analysis_setting": setting, "meta_analysis_data_rows": rows, "analysis_methods": method})

    output = SubgroupMethod().run(instances=instances)
    test = output["instance-1"]["subgroup_difference_tests"][0]

    assert output["instance-1"]["subgroup_estimates"][0]["estimation_status"] == "computed"
    assert output["instance-2"]["subgroup_estimates"][0]["estimation_status"] == "computed"
    assert "candidate_id" not in output["instance-1"]["subgroup_estimates"][0]
    assert "candidate_id" not in test
    assert test["test_status"] == "computed"
    assert test["df"] == 1
    assert 0 <= test["p_value"] <= 1
