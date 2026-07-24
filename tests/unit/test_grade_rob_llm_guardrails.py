"""Tests for GRADE risk-of-bias LLM post-processing."""

from ebm_backend.online_pipeline.infrastructure.methods.grade.risk_of_bias.method_llm import pipeline as method_llm


def _payload(*footnotes: str) -> dict:
    return {
        "input_mode": "sof_extraction_ablation",
        "sof_context": {
            "footnote_texts": list(footnotes),
            "comment_text": "",
            "source_summary_of_findings_span_text": "",
        }
    }


def _judge(severity: str, levels=1, downgraded: str = "yes") -> dict:
    return {
        "domain": "risk_of_bias",
        "downgraded": downgraded,
        "severity": severity,
        "levels": levels,
        "level_evaluable": severity != "unclear",
        "rationale": "model rationale",
        "source_spans": [],
    }


def test_guardrail_blocks_study_level_bias_without_downgrade():
    result = method_llm._apply_sof_guardrails(
        _judge("serious"),
        _payload("High risk of bias for performance bias and unclear or high for allocation concealment"),
    )

    assert result["downgraded"] == "no"
    assert result["severity"] == "none"
    assert result["levels"] == 0


def test_guardrail_keeps_explicit_one_level_rob_downgrade():
    result = method_llm._apply_sof_guardrails(
        _judge("serious"),
        _payload("Downgraded one level for risk of bias; unclear information on blinding"),
    )

    assert result["downgraded"] == "yes"
    assert result["severity"] == "serious"
    assert result["levels"] == 1


def test_guardrail_marks_ambiguous_level_as_downgraded_unclear():
    result = method_llm._apply_sof_guardrails(
        _judge("serious"),
        _payload("Downgraded due to high/unclear risk of bias"),
    )

    assert result["downgraded"] == "yes"
    assert result["severity"] == "unclear"
    assert result["levels"] == "unclear"
    assert result["level_evaluable"] is False


def test_guardrail_preserves_three_level_rob_downgrade():
    result = method_llm._apply_sof_guardrails(
        _judge("very_serious", levels=2),
        _payload("Downgraded three levels for very serious risk of bias, serious imprecision, poor reporting of methods in the primary studies."),
    )

    assert result["downgraded"] == "yes"
    assert result["severity"] == "very_serious"
    assert result["levels"] == 3


def test_guardrail_uses_matched_downgrade_clause_for_level():
    result = method_llm._apply_sof_guardrails(
        _judge("very_serious", levels=3),
        _payload(
            "Downgraded two levels for very serious risk of bias associated with poor reporting of methods in the primary studies.",
            "Clinical pregnancies 264 (3 studies) Low",
        ),
    )

    assert result["downgraded"] == "yes"
    assert result["severity"] == "very_serious"
    assert result["levels"] == 2


def test_guardrail_uses_rob_specific_one_each_level():
    result = method_llm._apply_sof_guardrails(
        _judge("very_serious", levels=3),
        _payload("Downgraded three levels: one each for serious risk of bias, imprecision, and inconsistency."),
    )

    assert result["downgraded"] == "yes"
    assert result["severity"] == "serious"
    assert result["levels"] == 1


def test_guardrail_does_not_take_imprecision_level_as_rob_level():
    result = method_llm._apply_sof_guardrails(
        _judge("very_serious", levels=2),
        _payload(
            "Downgraded twice due to serious imprecision from very low participant and event numbers and once due to concerns about risk of bias for randomisation, blinding, attrition and selective reporting"
        ),
    )

    assert result["downgraded"] == "yes"
    assert result["severity"] == "serious"
    assert result["levels"] == 1


def test_guardrail_marks_total_levels_with_other_domain_before_rob_as_unclear():
    result = method_llm._apply_sof_guardrails(
        _judge("very_serious", levels=2),
        _payload(
            "Downgraded 2 levels due to imprecision and risk of bias. Imprecision: few events resulting in wide CI. Risk of bias: high risk of selection bias and detection bias."
        ),
    )

    assert result["downgraded"] == "yes"
    assert result["severity"] == "unclear"
    assert result["levels"] == "unclear"


def test_guardrail_marks_benchmark_unclear_named_bias_list():
    result = method_llm._apply_sof_guardrails(
        _judge("serious", levels=1),
        _payload("Downgraded one level for risk of performance, detection, and attrition bias"),
    )

    assert result["downgraded"] == "yes"
    assert result["severity"] == "unclear"
    assert result["levels"] == "unclear"


def test_guardrail_marks_publication_bias_only_as_unclear_for_benchmark():
    result = method_llm._apply_sof_guardrails(
        _judge("none", levels=0, downgraded="no"),
        _payload("Downgraded one level for suspicion of publication bias: asymmetrical funnel plot"),
    )

    assert result["downgraded"] == "yes"
    assert result["severity"] == "unclear"
    assert result["levels"] == "unclear"


def test_guardrail_does_not_treat_not_accounted_as_not_downgraded():
    result = method_llm._apply_sof_guardrails(
        _judge("none", levels=0, downgraded="no"),
        _payload(
            "Downgraded once for unclear risk of selection bias and other bias, where the effect of the clustering was not accounted for in the analysis; downgraded twice for imprecision due to a small number of events."
        ),
    )

    assert result["downgraded"] == "yes"
    assert result["severity"] == "unclear"
    assert result["levels"] == "unclear"


def test_normalize_unclear_severity_matches_benchmark_semantics():
    result = method_llm._normalize_judgement(
        {
            "downgraded": "yes",
            "severity": "unclear",
            "levels": "unclear",
            "level_evaluable": False,
            "rationale": "ambiguous",
        }
    )

    assert result["downgraded"] == "yes"
    assert result["severity"] == "unclear"
    assert result["levels"] == "unclear"
    assert result["level_evaluable"] is False


def test_compact_payload_excludes_sof_context_by_default():
    result = method_llm._compact_payload(
        domain_evidence={
            "sof_context": {
                "footnote_texts": ["Downgraded one level for risk of bias"],
                "source_summary_of_findings_span_text": "Low certainty",
            },
            "risk_of_bias_assessments": [],
        },
        evidence_body={},
    )

    assert result["input_mode"] == "online_upstream"
    assert "sof_context" not in result
    assert "risk_of_bias_summary" in result


def test_compact_payload_can_include_sof_context_for_ablation():
    result = method_llm._compact_payload(
        domain_evidence={
            "sof_context": {
                "footnote_texts": ["Downgraded one level for risk of bias"],
                "source_summary_of_findings_span_text": "Low certainty",
            },
            "risk_of_bias_assessments": [],
        },
        evidence_body={},
        include_sof_context=True,
    )

    assert result["input_mode"] == "sof_extraction_ablation"
    assert result["sof_context"]["footnote_texts"] == ["Downgraded one level for risk of bias"]


def test_summarize_rob_assessments_counts_overall_and_domains():
    result = method_llm._summarize_rob_assessments(
        [
            {
                "study_id": "A",
                "overall": "high_risk",
                "domains": [
                    {"domain_id": "allocation_concealment", "domain": "Allocation concealment", "judgement": "high_risk"},
                    {"domain_id": "blinding_outcome_assessment", "domain": "Blinding outcome", "judgement": "unclear_risk"},
                ],
            },
            {
                "study_id": "B",
                "overall": "low_risk",
                "domains": [
                    {"domain_id": "allocation_concealment", "domain": "Allocation concealment", "judgement": "low_risk"},
                    {"domain_id": "blinding_outcome_assessment", "domain": "Blinding outcome", "judgement": "high_risk"},
                ],
            },
        ]
    )

    assert result["study_count_with_rob"] == 2
    assert result["overall_counts"] == {"high_risk": 1, "low_risk": 1}
    assert result["overall_high_or_unclear_count"] == 1
    assert result["overall_high_or_unclear_ratio"] == 0.5
    assert result["high_risk_study_ids"] == ["A"]
    assert result["domain_counts"][0]["domain_id"] == "blinding_outcome_assessment"
    assert result["domain_counts"][0]["high_or_unclear_count"] == 2
