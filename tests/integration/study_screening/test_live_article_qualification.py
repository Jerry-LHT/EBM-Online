from __future__ import annotations

import os
from pathlib import Path

import pytest

from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.article_qualification import (
    ArticleQualificationDecision,
)
from ebm_backend.online_pipeline.domain.serialization import from_jsonable, read_json
from ebm_backend.online_pipeline.infrastructure.methods.article_qualification.factory import (
    build_production_article_qualifier,
)


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_LLM_TESTS") != "1",
    reason="Set RUN_LIVE_LLM_TESTS=1 to call the configured LLM provider.",
)


def test_live_content_classifier_advances_real_primary_rct(tmp_path: Path) -> None:
    fixture = Path(
        "benchmark/online_pipeline/raw_data/cleaned_articles/pmc__PMC6323346.json"
    )
    article = from_jsonable(read_json(fixture), CleanedArticle)

    result = build_production_article_qualifier(
        cache_root=tmp_path / "article_qualification_cache"
    ).run(article=article)

    assert result.study_id == article.study_id
    assert result.decision in {
        ArticleQualificationDecision.PASS,
        ArticleQualificationDecision.ADVANCE_UNCERTAIN,
    }
    assert result.reason
    assert result.evidence_coverage.input_token_estimate > 0

