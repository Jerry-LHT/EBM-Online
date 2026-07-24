"""Stable failures for article-type qualification."""

from __future__ import annotations


class ArticleQualificationError(RuntimeError):
    failure_code = "article_qualification_error"


class ArticleQualificationConfigurationError(ArticleQualificationError):
    failure_code = "article_qualification_configuration_error"


class ArticleQualificationInvocationError(ArticleQualificationError):
    failure_code = "article_qualification_invocation_error"

    def __init__(self, *, article_id: str, attempts: int) -> None:
        super().__init__(
            f"Article qualification failed for {article_id} after {attempts} attempts"
        )
        self.article_id = article_id
        self.attempts = attempts

