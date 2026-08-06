from pathlib import Path

from ebm_backend.online_pipeline.infrastructure.llm import LLMConfig

from benchmark.ebm_application.beyond_abstracts.methods import run_method
from benchmark.ebm_application.beyond_abstracts.models import BeyondArticle, BeyondCase


def _case() -> BeyondCase:
    return BeyondCase(
        case_id=33,
        title="Review",
        question="Does treatment help?",
        pico={"P": [], "I": [], "C": [], "O": [], "O_expanded": []},
        inclusion_criteria=[],
        exclusion_criteria=[],
        articles=[BeyondArticle(1, "10", "Trial", "Trial abstract", None, study_ref="A")],
        oracle_evidence={"included_studies": [{"ref": "A", "outcomes": "Benefit"}], "comparisons": []},
        gold={"abstract_conclusion": "secret"},
    )


def _config() -> LLMConfig:
    return LLMConfig(api_key="x", base_url="https://example.invalid/v1", model="fake")


def test_closed_book_persists_request_response_and_never_exposes_gold(tmp_path, monkeypatch) -> None:
    seen = {}

    def fake_call_json(**kwargs):
        seen.update(kwargs)
        return {"conclusion": "Evidence was not supplied, so no conclusion can be drawn."}

    monkeypatch.setattr("benchmark.ebm_application.beyond_abstracts.methods.call_json", fake_call_json)
    result = run_method(case=_case(), method="closed_book", config=_config(), artifact_dir=tmp_path)

    assert result["method"] == "closed_book"
    assert "secret" not in seen["prompt"]
    assert "Benefit" not in seen["prompt"]
    assert (tmp_path / "synthesis/conclusion_generation/request.json").exists()
    assert (tmp_path / "synthesis/conclusion_generation/response.json").exists()
    assert (tmp_path / "events.jsonl").exists()


def test_evidence_package_exposes_oracle_evidence_but_not_gold(tmp_path, monkeypatch) -> None:
    prompts = []

    def fake_call_json(**kwargs):
        prompts.append(kwargs["prompt"])
        return {"conclusion": "The evidence suggests benefit, with uncertainty."}

    monkeypatch.setattr("benchmark.ebm_application.beyond_abstracts.methods.call_json", fake_call_json)
    run_method(case=_case(), method="evidence_package", config=_config(), artifact_dir=tmp_path)

    assert "Benefit" in prompts[-1]
    assert "secret" not in prompts[-1]


def test_bm25_rag_persists_source_catalog_and_retrieval(tmp_path, monkeypatch) -> None:
    responses = iter([
        {"queries": ["treatment", "outcome", "trial", "effect"]},
        {"conclusion": "The abstract alone provides insufficient evidence."},
    ])
    monkeypatch.setattr(
        "benchmark.ebm_application.beyond_abstracts.methods.call_json",
        lambda **_kwargs: next(responses),
    )

    run_method(case=_case(), method="bm25_rag", config=_config(), artifact_dir=tmp_path)

    assert (tmp_path / "rag/source_catalog.json").exists()
    assert (tmp_path / "rag/retrieval.json").exists()
    assert "Trial abstract" in (tmp_path / "synthesis/evidence.txt").read_text()

