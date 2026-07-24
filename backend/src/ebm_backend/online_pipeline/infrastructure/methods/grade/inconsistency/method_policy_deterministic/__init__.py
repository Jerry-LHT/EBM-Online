"""Result-blind policy plus deterministic GRADE inconsistency method."""

from ebm_backend.online_pipeline.infrastructure.methods.grade.inconsistency.method_policy_deterministic.method import (
    Method,
    build_method,
)

__all__ = ["Method", "build_method"]
