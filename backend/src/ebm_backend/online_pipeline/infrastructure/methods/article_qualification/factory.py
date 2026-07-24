"""Factory for the production content-based article qualifier."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ebm_backend.online_pipeline.infrastructure.methods.article_qualification.content_llm.cache import (
    FileArticleQualificationCache,
)
from ebm_backend.online_pipeline.infrastructure.methods.article_qualification.content_llm.method import (
    ContentBasedArticleQualifier,
)


def build_production_article_qualifier(
    *,
    config: Any | None = None,
    cache_root: Path | None = None,
    debug_root: Path | None = None,
) -> ContentBasedArticleQualifier:
    return ContentBasedArticleQualifier(
        config=config,
        cache=(
            FileArticleQualificationCache(cache_root)
            if cache_root is not None
            else None
        ),
        debug_root=debug_root,
    )
