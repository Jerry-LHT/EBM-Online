"""Execution failures for Search Retrieval provider stages."""

from __future__ import annotations


class SearchRetrievalStageError(RuntimeError):
    """A required provider stage failed within its bounded retry policy."""

    def __init__(self, *, stage: str, attempts: int) -> None:
        super().__init__(f"Search Retrieval stage '{stage}' failed after {attempts} attempt(s)")
        self.stage = stage
        self.attempts = attempts
