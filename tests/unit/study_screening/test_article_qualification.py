from __future__ import annotations

from dataclasses import dataclass

from ebm_backend.online_pipeline.application.use_cases.run_article_qualification import (
    RunArticleQualification,
)
from ebm_backend.online_pipeline.domain.article import (
    ArticleMetadata,
    ArticleSection,
    ArticleTable,
    ArticleXmlContent,
    CleanedArticle,
)
from ebm_backend.online_pipeline.domain.article_qualification import (
    ArticleQualificationDecision,
)
from ebm_backend.online_pipeline.domain.serialization import read_json
from ebm_backend.online_pipeline.infrastructure.methods.article_qualification.content_llm.evidence import (
    build_qualification_evidence,
)
from ebm_backend.online_pipeline.infrastructure.methods.article_qualification.content_llm.method import (
    ContentBasedArticleQualifier,
)
from ebm_backend.online_pipeline.infrastructure.methods.article_qualification.content_llm.cache import (
    FileArticleQualificationCache,
)


def _article(study_id: str = "study-1") -> CleanedArticle:
    return CleanedArticle(
        study_id=study_id,
        metadata=ArticleMetadata(
            title="Randomized trial",
            publication_types=["Systematic Review"],
            mesh_terms=["Randomized Controlled Trial"],
        ),
        xml_content=ArticleXmlContent(
            sections=[
                ArticleSection(
                    section_id="abstract",
                    title="Abstract",
                    text=(
                        "Participants were randomly assigned to treatment or control.\n\n"
                        "The primary outcome was measured after treatment."
                    ),
                ),
                ArticleSection(
                    section_id="results",
                    title="Results",
                    text="The trial results are reported for both groups.",
                ),
            ]
        ),
        tables=[
            ArticleTable(
                table_id="t1",
                caption="",
                raw_xml="<table-wrap><table><tr><td>Results 10/20 versus 5/20</td></tr></table></table-wrap>",
            )
        ],
    )


def _pass_payload() -> dict:
    return {
        "decision": "pass",
        "report_role": "primary_results",
        "randomization_status": "randomized",
        "trial_design": "individual_parallel",
        "results_report_status": "results_reported",
        "has_quantitative_results": True,
        "reason": "Primary randomized trial results are present.",
        "evidence_spans": ["Participants were randomly assigned to treatment or control."],
    }


def test_qualification_uses_content_without_pubmed_type_labels() -> None:
    calls = []

    def caller(**kwargs):
        calls.append(kwargs)
        assert "Systematic Review" not in kwargs["prompt"]
        assert "Randomized Controlled Trial" not in kwargs["prompt"]
        assert "partial_table_slice" in kwargs["prompt"] or "complete_table" in kwargs["prompt"]
        return _pass_payload()

    result = ContentBasedArticleQualifier(
        config={"api_mode": "responses", "screening_input_token_budget": 8_000},
        llm_caller=caller,
    ).run(article=_article())

    assert result.decision == ArticleQualificationDecision.PASS
    assert result.source_spans[0].source_id.startswith("section:abstract")
    assert len(calls) == 1


def test_qualification_evidence_marks_large_table_slice_as_partial() -> None:
    article = _article()
    article = CleanedArticle(
        study_id=article.study_id,
        metadata=article.metadata,
        xml_content=article.xml_content,
        tables=[
            ArticleTable(
                table_id="large",
                caption="",
                raw_xml="<table>" + ("<tr><td>result</td></tr>" * 5_000) + "</table>",
            )
        ],
    )
    evidence = build_qualification_evidence(
        article=article,
        input_token_budget=2_000,
    )

    table_blocks = [block for block in evidence.blocks if block.kind.startswith("raw_table")]
    assert table_blocks
    assert table_blocks[0].coverage == "partial_table_slice"
    assert table_blocks[0].text in article.tables[0].raw_xml
    assert evidence.coverage.partial_table_ids == ["large"]


def test_qualifier_retries_once_and_use_case_advances_technical_failure() -> None:
    attempts = 0

    def caller(**kwargs):
        nonlocal attempts
        attempts += 1
        raise RuntimeError("provider unavailable")

    qualifier = ContentBasedArticleQualifier(
        config={"api_mode": "responses"},
        llm_caller=caller,
    )
    result = RunArticleQualification(
        qualifier=qualifier,
        max_workers=1,
    ).execute(articles=[_article()])

    assert attempts == 2
    assert result.technical_failure_studies == ["study-1"]
    assert result.excluded_studies == []
    assert result.assessments[0].decision == ArticleQualificationDecision.TECHNICAL_FAILURE


@dataclass
class _OrderingQualifier:
    def run(self, *, article):
        payload = _pass_payload()
        return ContentBasedArticleQualifier(
            config={"api_mode": "responses"},
            llm_caller=lambda **kwargs: payload,
        ).run(article=article)


def test_qualification_concurrency_preserves_input_order() -> None:
    result = RunArticleQualification(
        qualifier=_OrderingQualifier(),
        max_workers=2,
    ).execute(articles=[_article("b"), _article("a")])

    assert [item.study_id for item in result.assessments] == ["b", "a"]


def test_successful_article_type_assessment_is_cached(tmp_path) -> None:
    calls = 0

    def caller(**kwargs):
        nonlocal calls
        calls += 1
        return _pass_payload()

    debug_root = tmp_path / "debug"
    qualifier = ContentBasedArticleQualifier(
        config={
            "api_mode": "responses",
            "model": "fake-model",
            "base_url": "https://example.invalid/v1",
        },
        llm_caller=caller,
        cache=FileArticleQualificationCache(tmp_path),
        debug_root=debug_root,
    )

    first = qualifier.run(article=_article())
    second = qualifier.run(article=_article())

    assert first == second
    assert calls == 1
    debug_files = list(debug_root.rglob("*.json"))
    assert len(debug_files) == 1
    debug = read_json(debug_files[0])
    assert debug["cache_hit"] is False
    assert debug["model_output"] == _pass_payload()
    assert debug["assessment"]["decision"] == "pass"
    assert debug["evidence_sources"]
    assert "api_key" not in debug["model"]


def test_invalid_model_output_is_retained_in_debug_artifact(tmp_path) -> None:
    invalid_payload = {"decision": "pass"}

    qualifier = ContentBasedArticleQualifier(
        config={"api_mode": "responses", "model": "fake-model"},
        llm_caller=lambda **kwargs: invalid_payload,
        debug_root=tmp_path,
    )

    result = RunArticleQualification(
        qualifier=qualifier,
        max_workers=1,
    ).execute(articles=[_article()])

    assert result.technical_failure_studies == ["study-1"]
    debug_files = list(tmp_path.rglob("*.json"))
    assert len(debug_files) == 1
    debug = read_json(debug_files[0])
    assert debug["model_output"] == invalid_payload
    assert [attempt["status"] for attempt in debug["attempts"]] == [
        "failed",
        "failed",
    ]
