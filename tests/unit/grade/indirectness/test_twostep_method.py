from __future__ import annotations

from ebm_backend.online_pipeline.infrastructure.methods.grade.indirectness import method_llm_twostep
from ebm_backend.online_pipeline.infrastructure.methods.grade.indirectness.twostep import normalization, prompts


def test_twostep_prompts_require_strict_json_output() -> None:
    evidence_package = {
        "input_policy": "test",
        "review_question": {
            "question_text": "question",
            "population": ["adults"],
            "population_source": "question_pico.population",
            "intervention": ["intervention"],
            "comparator": ["comparator"],
            "outcome": ["mortality"],
        },
        "synthesis_target": {
            "population": {"value": "adults", "source": "question_pico.population"},
            "intervention": {"value": "intervention", "source": "analysis_setting.comparison.experimental"},
            "comparator": {"value": "comparator", "source": "analysis_setting.comparison.comparator"},
            "outcome": {"value": "mortality", "source": "analysis_setting.outcome.label"},
            "timepoint": {"value": "", "source": "analysis_setting.timepoint"},
            "subgroup": {"value": "", "source": "analysis_setting.subgroup"},
            "setting": {"value": "", "source": "not_provided"},
        },
        "included_study_evidence": {
            "included_study_ids": ["study-1"],
            "study_count": 1,
            "study_characteristics": [],
            "study_result_rows": [],
        },
    }

    extraction_prompt = prompts.extraction_prompt(evidence_package)
    threshold_prompt = prompts.threshold_prompt(
        evidence_package=evidence_package,
        extraction={"study_level_pico_profile": {}},
    )
    adjudication_prompt = prompts.adjudication_prompt(
        evidence_package=evidence_package,
        extraction={"study_level_pico_profile": {}},
        threshold_policy={"domain_thresholds": {}},
    )

    for prompt in (extraction_prompt, threshold_prompt, adjudication_prompt):
        assert "Return exactly one valid JSON object and nothing else." in prompt
        assert "Do not wrap the answer in Markdown fences." in prompt
        assert "Do not include comments, explanations outside JSON, trailing commas" in prompt

    assert "Dynamic threshold policy" in adjudication_prompt
    assert "threshold_posture" in threshold_prompt


def test_serious_limitation_check_is_preserved_in_debug() -> None:
    raw = {
        "downgraded": "yes",
        "severity": "serious",
        "levels": 1,
        "rationale": "Accepted intervention package mismatch.",
        "serious_limitation_check": {
            "accepted_serious_limitations": [
                {
                    "domain": "intervention",
                    "limitation": "Complex package changes the causal contrast.",
                    "applicability_mechanism": "The added component prevents isolating the target intervention effect.",
                    "supporting_evidence": ["package intervention"],
                }
            ],
            "rejected_or_minor_candidates": [
                {
                    "domain": "setting",
                    "candidate_difference": "single country",
                    "reason_rejected_or_minor": "No supported mechanism that it changes applicability.",
                    "supporting_evidence": ["one country"],
                }
            ],
            "threshold_rationale": "One accepted serious limitation meets the GRADE threshold.",
        },
    }

    threshold_policy = {
        "policy_summary": "Intervention threshold should be sensitive.",
        "domain_thresholds": {
            "intervention": {
                "threshold_posture": "sensitive",
                "downgrade_triggers": ["package changes causal contrast"],
                "non_downgrade_patterns": ["same-class dose variation"],
                "evidence_terms": ["package intervention"],
                "rationale": "Package effects are hard to isolate.",
            }
        },
        "cross_domain_integration": "Do not add minor concerns arithmetically.",
    }
    judgement = normalization._judgement_from_llm(
        raw=raw,
        evidence_package={"included_study_evidence": {"study_count": 1, "study_result_rows": []}},
        extraction=None,
        threshold_policy=threshold_policy,
    )

    check = judgement["debug"]["serious_limitation_check"]
    assert check["accepted_serious_limitations"][0]["domain"] == "intervention"
    assert check["rejected_or_minor_candidates"][0]["domain"] == "setting"
    assert "GRADE threshold" in check["threshold_rationale"]
    policy = judgement["debug"]["dynamic_threshold_policy"]
    assert policy["domain_thresholds"]["intervention"]["threshold_posture"] == "sensitive"


def test_twostep_compatibility_entrypoint_builds_method() -> None:
    method = method_llm_twostep.build_method()
    assert method.domain == "indirectness"
    assert hasattr(method, "run")
