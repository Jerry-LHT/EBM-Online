"""Application ports for synthesis and certainty assessment."""

from __future__ import annotations

from typing import Any, Protocol

from ebm_backend.online_pipeline.domain.grade import (
    GRADEImprecisionInput,
    GRADEIndirectnessInput,
    GRADEInconsistencyInput,
    GRADERiskOfBiasInput,
)


class SynthesisPlanningPort(Protocol):
    def run(
        self,
        *,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        ...



class StudyEvidencePort(Protocol):
    def run(
        self,
        *,
        review_id: str,
        targets: list[dict[str, Any]],
        study_id: str,
        article: dict[str, Any],
        plan_hash: str,
    ) -> dict[str, Any]:
        ...


class AnalysisMethodsPort(Protocol):
    def run(self, *, instance: dict[str, Any]) -> list[dict[str, Any]]:
        ...


class SubgroupAnalysisPort(Protocol):
    def run(self, *, instances: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        ...


class OverallEstimatesPort(Protocol):
    def run(self, *, instance: dict[str, Any]) -> dict[str, Any]:
        ...


class GRADERiskOfBiasPort(Protocol):
    def run(self, *, grade_input: GRADERiskOfBiasInput) -> dict[str, Any]:
        ...


class GRADEInconsistencyPort(Protocol):
    def run(self, *, grade_input: GRADEInconsistencyInput) -> dict[str, Any]:
        ...


class GRADEIndirectnessPort(Protocol):
    def run(self, *, grade_input: GRADEIndirectnessInput) -> dict[str, Any]:
        ...


class GRADEImprecisionPort(Protocol):
    def run(self, *, grade_input: GRADEImprecisionInput) -> dict[str, Any]:
        ...
