"""Application port for review-independent article-type qualification."""

from __future__ import annotations

from typing import Protocol

from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.article_qualification import (
    ArticleQualificationAssessment,
)


class ArticleQualificationPort(Protocol):
    def run(self, *, article: CleanedArticle) -> ArticleQualificationAssessment:
        ...

