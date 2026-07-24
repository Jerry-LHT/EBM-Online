"""Shared runtime configuration for independently executed modules."""

from __future__ import annotations

from dataclasses import dataclass, field

from ebm_backend.online_pipeline.domain.common import WorkflowConstraints


DEFAULT_MAX_CANDIDATES_PER_SOURCE: int | None = None
DEFAULT_MAX_RESULTS_PER_SOURCE = 500
MAX_CANDIDATES_PER_SOURCE = 10_000
MAX_RESULTS_PER_SOURCE = 500


@dataclass(frozen=True)
class ModuleRunConfig:
    # None means retain the provider inventory up to the service safety cap.
    max_candidates_per_source: int | None = DEFAULT_MAX_CANDIDATES_PER_SOURCE
    max_results_per_source: int = DEFAULT_MAX_RESULTS_PER_SOURCE
    constraints: WorkflowConstraints = field(default_factory=WorkflowConstraints)

    def __post_init__(self) -> None:
        if self.max_candidates_per_source is not None and not (
            1 <= self.max_candidates_per_source <= MAX_CANDIDATES_PER_SOURCE
        ):
            raise ValueError(
                f"max_candidates_per_source must be between 1 and {MAX_CANDIDATES_PER_SOURCE}"
            )
        if not 1 <= self.max_results_per_source <= MAX_RESULTS_PER_SOURCE:
            raise ValueError(
                f"max_results_per_source must be between 1 and {MAX_RESULTS_PER_SOURCE}"
            )
        if (
            self.max_candidates_per_source is not None
            and self.max_candidates_per_source < self.max_results_per_source
        ):
            raise ValueError(
                "max_candidates_per_source must be greater than or equal to max_results_per_source"
            )
