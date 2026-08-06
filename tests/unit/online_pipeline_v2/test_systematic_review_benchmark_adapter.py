from benchmark.online_pipeline_v2.SystematicReview.adapter.markdown import (
    render_systematic_review_markdown,
)
from benchmark.online_pipeline_v2.SystematicReview.adapter.html import (
    render_systematic_review_html,
)
import json


def test_markdown_renderer_preserves_all_scientific_fields() -> None:
    artifact = {
        "title": "Review title",
        "review_path": "evidence_review",
        "document_maturity": "scientific_draft",
        "sections": [
            {
                "name": "results",
                "content": "One outcome was not estimable.",
                "subsections": [
                    {"heading": "Mortality", "content": "No usable data."}
                ],
                "source_artifact_ids": ["grade-1"],
                "provenance": [],
            }
        ],
        "method_decisions": [
            {
                "decision_id": "decision-1",
                "topic": "reporting",
                "decision": "Report the no-evidence outcome.",
                "rationale": "It was planned in the Protocol.",
                "basis_status": "llm_fallback",
                "fallback_model": "provider/model-id",
                "fallback_note": "Official guidance was unavailable.",
                "authoritative_sources": [],
                "provenance": [],
            }
        ],
        "issues": [
            {
                "severity": "warning",
                "code": "report_unavailable",
                "message": "A report was unavailable.",
            }
        ],
    }

    rendered = render_systematic_review_markdown(
        instance_id="case-1",
        response={"status": "completed"},
        artifact=artifact,
    )

    for value in (
        "One outcome was not estimable.",
        "No usable data.",
        "grade-1",
        "Report the no-evidence outcome.",
        "provider/model-id",
        "Official guidance was unavailable.",
        "A report was unavailable.",
    ):
        assert value in rendered


def test_html_renderer_embeds_source_bound_sof_including_no_evidence(tmp_path) -> None:
    source = tmp_path / "certainty/summary-of-findings.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps(
            {
                "tables": [
                    {
                        "table_id": "sof-1",
                        "population": "Adults",
                        "intervention": "Intervention",
                        "comparison": "Comparator",
                        "rows": [
                            {
                                "evidence_body_id": "outcome-1",
                                "outcome": "Mortality",
                                "time_frame": "30 days",
                                "relative_effect": None,
                                "absolute_effects": [],
                                "study_count": 0,
                                "participant_count": None,
                                "certainty": None,
                                "explanation": "No eligible evidence was available.",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    artifact = {
        "title": "Review title",
        "sections": [],
        "displays": [
            {
                "display_id": "sof",
                "kind": "summary_of_findings",
                "title": "Summary of findings",
                "location": "before_background",
                "source_file": "certainty/summary-of-findings.json",
                "source_object_ids": ["sof-1"],
            }
        ],
        "method_decisions": [],
        "issues": [],
    }

    rendered = render_systematic_review_html(
        instance_id="case-1",
        response={"status": "completed"},
        artifact=artifact,
        review_data_root=tmp_path,
    )

    assert "Summary of findings" in rendered
    assert "Mortality" in rendered
    assert "No eligible evidence was available." in rendered
    assert "Not estimated" in rendered


def test_html_reader_combines_methods_pico_result_level_rob_and_references(
    tmp_path,
) -> None:
    study_path = tmp_path / "study-data/study-data-collection.json"
    risk_path = tmp_path / "study-data/risk-of-bias.json"
    index_path = tmp_path / "review-context/reporting-index.json"
    study_path.parent.mkdir(parents=True)
    index_path.parent.mkdir(parents=True)
    study_path.write_text(
        json.dumps(
            {
                "studies": [
                    {
                        "study_id": "study-1",
                        "display_name": "Example trial",
                        "characteristics": {
                            "methods": {
                                "design": {"status": "reported", "value": "Randomized trial"}
                            },
                            "population": {
                                "eligibility_criteria": {
                                    "status": "reported",
                                    "value": "Adults with condition X",
                                },
                                "sample_size": {"status": "reported", "value": "100"},
                            },
                            "funding": {"status": "not_reported"},
                            "conflicts_of_interest": {"status": "not_reported"},
                            "notes": {"status": "reported", "value": "Completed study"},
                        },
                        "arms": [
                            {
                                "role": "intervention",
                                "label": {"status": "reported", "value": "Treatment A"},
                                "description": {"status": "reported", "value": "Daily treatment"},
                            },
                            {
                                "role": "comparator",
                                "label": {"status": "reported", "value": "Usual care"},
                                "description": {"status": "reported", "value": "Standard care"},
                            },
                        ],
                        "targets": [
                            {
                                "outcome_name": "Mortality",
                                "timepoint": "30 days",
                                "comparison": "Treatment A versus usual care",
                                "analysis_population": "Randomized participants",
                                "unit_of_analysis": "Participant",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    risk_path.write_text(
        json.dumps(
            {
                "assessments": [
                    {
                        "assessment_id": "rob-1",
                        "study_id": "study-1",
                        "target_id": "mortality-30d",
                        "overall": "some_concerns",
                        "domains": [
                            {
                                "domain_name": "Randomization process",
                                "judgement": "low",
                                "support": "Sequence was generated appropriately.",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    index_path.write_text(
        json.dumps(
            {
                "schema_version": "systematic-review-reporting-index.v2",
                "stages": {
                    "selection": {
                        "study_references": [
                            {
                                "study_id": "study-1",
                                "display_name": "Example trial",
                                "classification": "included",
                                "reports": [
                                    {
                                        "report_id": "report-1",
                                        "citation": "Author. Example trial. 2024.",
                                        "external_identifiers": ["doi:10.1/example"],
                                        "locators": ["https://example.org/report"],
                                    }
                                ],
                            }
                        ]
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    artifact = {
        "title": "Review title",
        "sections": [
            {"name": "results", "content": "Results narrative.", "subsections": []},
            {"name": "references", "content": "Reference narrative.", "subsections": []},
        ],
        "displays": [
            {
                "display_id": "characteristics",
                "kind": "study_characteristics",
                "title": "Characteristics of included studies",
                "location": "results",
                "source_file": "study-data/study-data-collection.json",
                "source_object_ids": ["study-1"],
            },
            {
                "display_id": "risk",
                "kind": "risk_of_bias",
                "title": "Risk of bias",
                "location": "results",
                "source_file": "study-data/risk-of-bias.json",
                "source_object_ids": ["rob-1"],
            },
        ],
        "method_decisions": [],
        "issues": [],
    }

    rendered = render_systematic_review_html(
        instance_id="case-1",
        response={"status": "completed"},
        artifact=artifact,
        review_data_root=tmp_path,
    )

    for value in (
        "Randomized trial",
        "Adults with condition X",
        "Treatment A",
        "Usual care",
        "Mortality",
        "30 days",
        "mortality-30d",
        "Randomization process",
        "Author. Example trial. 2024.",
        "References to included studies",
    ):
        assert value in rendered
