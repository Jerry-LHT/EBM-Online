"""Build leakage-controlled method inputs for GRADE inconsistency evaluation."""

from __future__ import annotations

from typing import Any


def build_method_instance(instance: dict[str, Any]) -> dict[str, Any]:
    """Return the benchmark instance with only upstream analysis evidence.

    The source benchmark rows carry SoF context for alignment and gold construction.
    That context is intentionally excluded here because SoF row text and footnotes
    can directly reveal the GRADE downgrade decision.
    """

    evidence_body = _dict_value(instance.get("evidence_body"))
    domain_evidence = _dict_value(instance.get("domain_evidence"))
    analysis_setting = _clean_analysis_setting(
        _dict_value(instance.get("analysis_setting"), evidence_body.get("analysis_setting"))
    )
    effect_estimate = _clean_effect_estimate(
        _dict_value(domain_evidence.get("effect_estimate"), instance.get("effect_estimate"), evidence_body.get("effect_estimate"))
    )
    study_result_rows = _clean_study_result_rows(
        _list_value(domain_evidence.get("study_result_rows") or instance.get("study_result_rows") or evidence_body.get("study_result_rows"))
    )
    method_domain_evidence = {
        "analysis_setting": analysis_setting,
        "population_context": _population_context(instance=instance, analysis_setting=analysis_setting),
        "effect_estimate": effect_estimate,
        "study_count": effect_estimate.get("study_count"),
        "participant_count": effect_estimate.get("participant_count"),
        "analysis_method": _clean_analysis_method(
            _dict_value(domain_evidence.get("analysis_method"), instance.get("analysis_method"), evidence_body.get("analysis_method"))
        ),
        "included_study_ids": _list_value(
            domain_evidence.get("included_study_ids") or instance.get("included_study_ids") or evidence_body.get("included_study_ids")
        ),
        "heterogeneity": _clean_heterogeneity(
            _dict_value(domain_evidence.get("heterogeneity"), effect_estimate.get("heterogeneity"))
        ),
        "subgroup_estimates": _clean_estimate_rows(
            _list_value(domain_evidence.get("subgroup_estimates") or evidence_body.get("subgroup_estimates"))
        ),
        "subgroup_difference_tests": _clean_subgroup_tests(
            _list_value(domain_evidence.get("subgroup_difference_tests") or evidence_body.get("subgroup_difference_tests"))
        ),
        "study_result_rows": study_result_rows,
        "study_characteristics": _clean_study_characteristics(
            _list_value(
                domain_evidence.get("study_characteristics")
                or evidence_body.get("study_characteristics")
                or instance.get("study_characteristics")
            )
        ),
        "study_characteristics_missing_study_ids": _list_value(
            domain_evidence.get("study_characteristics_missing_study_ids")
            or evidence_body.get("study_characteristics_missing_study_ids")
            or instance.get("study_characteristics_missing_study_ids")
        ),
    }
    return {
        "instance_id": instance.get("instance_id"),
        "sof_row_id": instance.get("sof_row_id"),
        "review_id": instance.get("review_id"),
        "domain": instance.get("domain"),
        "domain_evidence": method_domain_evidence,
        "evidence_body": {
            "analysis_setting": analysis_setting,
            "population_context": method_domain_evidence["population_context"],
            "effect_estimate": effect_estimate,
            "included_study_ids": method_domain_evidence["included_study_ids"],
            "study_result_rows": study_result_rows,
            "analysis_method": method_domain_evidence["analysis_method"],
            "subgroup_estimates": method_domain_evidence["subgroup_estimates"],
            "subgroup_difference_tests": method_domain_evidence["subgroup_difference_tests"],
            "study_characteristics": method_domain_evidence["study_characteristics"],
            "study_characteristics_missing_study_ids": method_domain_evidence["study_characteristics_missing_study_ids"],
        },
    }


def _clean_analysis_setting(setting: dict[str, Any]) -> dict[str, Any]:
    outcome = _dict_value(setting.get("outcome"))
    return {
        "setting_id": setting.get("setting_id"),
        "setting_family_id": setting.get("setting_family_id"),
        "candidate_id": setting.get("candidate_id"),
        "review_id": setting.get("review_id"),
        "analysis_name": setting.get("analysis_name"),
        "analysis_group_name": setting.get("analysis_group_name"),
        "comparison": _dict_value(setting.get("comparison")),
        "outcome": {
            "label": outcome.get("label"),
            "measure": outcome.get("measure"),
            "benefit_direction": outcome.get("benefit_direction"),
            "population": _first_present(
                outcome.get("population"),
                outcome.get("outcome_population"),
                outcome.get("population_label"),
                outcome.get("target_population"),
            ),
        },
        "timepoint": _dict_value(setting.get("timepoint")),
        "subgroup": _dict_value(setting.get("subgroup")),
        "data_type": setting.get("data_type"),
        "effect_measure": setting.get("effect_measure"),
    }


def _population_context(*, instance: dict[str, Any], analysis_setting: dict[str, Any]) -> dict[str, Any]:
    outcome = _dict_value(analysis_setting.get("outcome"))
    outcome_population = _clean_text(outcome.get("population"))
    if outcome_population:
        return {"text": outcome_population, "source": "analysis_setting.outcome.population"}
    question_population = _clean_question_population(_dict_value(instance.get("question_pico")))
    if question_population:
        return {"text": question_population, "source": "question_pico.population"}
    return {"text": "", "source": "missing"}


def _clean_effect_estimate(estimate: dict[str, Any]) -> dict[str, Any]:
    return {
        "setting_id": estimate.get("setting_id"),
        "setting_family_id": estimate.get("setting_family_id"),
        "included_study_ids": _list_value(estimate.get("included_study_ids")),
        "study_count": estimate.get("study_count"),
        "participant_count": estimate.get("participant_count"),
        "data_type": estimate.get("data_type"),
        "effect_measure": estimate.get("effect_measure"),
        "analysis_model": estimate.get("analysis_model"),
        "statistical_method": estimate.get("statistical_method"),
        "ci_level": estimate.get("ci_level"),
        "effect_value": estimate.get("effect_value", estimate.get("effect")),
        "ci_lower": estimate.get("ci_lower"),
        "ci_upper": estimate.get("ci_upper"),
        "prediction_interval": _dict_value(estimate.get("prediction_interval")),
        "heterogeneity": _clean_heterogeneity(_dict_value(estimate.get("heterogeneity"))),
        "effect_test": _dict_value(estimate.get("effect_test")),
        "estimation_status": estimate.get("estimation_status"),
    }


def _clean_heterogeneity(heterogeneity: dict[str, Any]) -> dict[str, Any]:
    return {
        "tau2": heterogeneity.get("tau2"),
        "chi2": heterogeneity.get("chi2"),
        "df": heterogeneity.get("df"),
        "p_value": _first_present(heterogeneity.get("p_value"), heterogeneity.get("p")),
        "i2": heterogeneity.get("i2"),
    }


def _clean_analysis_method(method: dict[str, Any]) -> dict[str, Any]:
    return {
        "effect_measure": method.get("effect_measure"),
        "analysis_model": method.get("analysis_model"),
        "statistical_method": method.get("statistical_method"),
        "ci_level": method.get("ci_level"),
        "subgroup_estimates_enabled": method.get("subgroup_estimates_enabled"),
        "overall_estimates_enabled": method.get("overall_estimates_enabled"),
        "test_for_subgroup_differences": method.get("test_for_subgroup_differences"),
        "analysis_included_study_ids": _list_value(method.get("analysis_included_study_ids")),
    }


def _clean_study_result_rows(rows: list[Any]) -> list[dict[str, Any]]:
    clean_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        clean_rows.append(
            {
                "row_id": row.get("row_id"),
                "setting_id": row.get("setting_id"),
                "study_id": row.get("study_id"),
                "study_year": row.get("study_year"),
                "extraction_status": row.get("extraction_status"),
                "data_type": row.get("data_type"),
                "comparison": _dict_value(row.get("comparison")),
                "outcome": _dict_value(row.get("outcome")),
                "subgroup": _dict_value(row.get("subgroup")),
                "result_data": _clean_result_data(_dict_value(row.get("result_data"))),
                "effect": _dict_value(row.get("effect")),
            }
        )
    return clean_rows


def _clean_result_data(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "experimental_events": data.get("experimental_events"),
        "experimental_total": data.get("experimental_total"),
        "control_events": data.get("control_events"),
        "control_total": data.get("control_total"),
        "experimental_mean": data.get("experimental_mean"),
        "experimental_sd": data.get("experimental_sd"),
        "control_mean": data.get("control_mean"),
        "control_sd": data.get("control_sd"),
    }


def _clean_estimate_rows(rows: list[Any]) -> list[dict[str, Any]]:
    return [_clean_effect_estimate(row) for row in rows if isinstance(row, dict)]


def _clean_subgroup_tests(rows: list[Any]) -> list[dict[str, Any]]:
    clean_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        clean_rows.append(
            {
                "setting_family_id": row.get("setting_family_id"),
                "chi2": row.get("chi2"),
                "df": row.get("df"),
                "p_value": _first_present(row.get("p_value"), row.get("p")),
                "i2": row.get("i2"),
            }
        )
    return clean_rows


def _clean_study_characteristics(rows: list[Any]) -> list[dict[str, Any]]:
    clean_rows = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        clean_rows.append(
            {
                "study_id": row.get("study_id"),
                "matched_study_id": row.get("matched_study_id"),
                "population": row.get("population"),
                "intervention_comparator": row.get("intervention_comparator"),
                "outcomes": row.get("outcomes"),
                "methods": row.get("methods"),
                "notes": row.get("notes"),
            }
        )
    return clean_rows


def _dict_value(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _list_value(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_present(*values: Any) -> Any:
    for value in values:
        if value is not None and value != "":
            return value
    return None


def _clean_question_population(question_pico: dict[str, Any]) -> str:
    population = _first_present(question_pico.get("population"), question_pico.get("P"))
    if isinstance(population, list):
        return ", ".join(_clean_text(item) for item in population if _clean_text(item))
    return _clean_text(population)


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()
