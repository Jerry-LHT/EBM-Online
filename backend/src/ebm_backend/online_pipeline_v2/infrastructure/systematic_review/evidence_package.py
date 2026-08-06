"""Build the immutable evidence package for final Review composition."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import TypeAdapter

from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactEnvelope,
    CompletedArtifactRef,
)
from ebm_backend.online_pipeline_v2.domain.protocol import ProtocolDraft
from ebm_backend.online_pipeline_v2.domain.review_run import ReviewRun
from ebm_backend.online_pipeline_v2.domain.risk_of_bias import RiskOfBiasArtifact
from ebm_backend.online_pipeline_v2.domain.search import EvidenceSearchArtifact
from ebm_backend.online_pipeline_v2.domain.selection import StudySelectionArtifact
from ebm_backend.online_pipeline_v2.domain.systematic_review import (
    EmptyReviewContext,
    ReviewPath,
)
from ebm_backend.online_pipeline_v2.infrastructure.persistence.filesystem import jsonable
from ebm_backend.online_pipeline_v2.infrastructure.systematic_review.reporting_index import (
    build_reporting_index,
)


_COMPLETED = TypeAdapter(CompletedArtifactRef)
_PROTOCOL = TypeAdapter(ArtifactEnvelope[ProtocolDraft])
_SEARCH = TypeAdapter(ArtifactEnvelope[EvidenceSearchArtifact])
_SELECTION = TypeAdapter(ArtifactEnvelope[StudySelectionArtifact])
_ROB = TypeAdapter(ArtifactEnvelope[RiskOfBiasArtifact])


class FileSystematicReviewEvidencePackageBuilder:
    def __init__(
        self,
        *,
        data_collection_store,
        synthesis_store,
        grade_artifact_store,
        evidence_store,
        selection_store,
    ) -> None:
        self._data_collection_store = data_collection_store
        self._synthesis_store = synthesis_store
        self._grade_artifact_store = grade_artifact_store
        self._evidence_store = evidence_store
        self._selection_store = selection_store

    def build(
        self,
        *,
        run: ReviewRun,
        protocol: ProtocolDraft,
        empty_review: EmptyReviewContext | None,
    ):
        search = _SEARCH.validate_python(run.artifacts["evidence_search"])
        selection = _SELECTION.validate_python(run.artifacts["study_selection"])
        if selection.data is None:
            raise ValueError("Study Selection data are missing")
        selection_data = self._selection_document(selection.data)
        files = {
            "review-context/protocol.json": _json_bytes(protocol),
            "review-context/search.json": _json_bytes(search.data),
            "review-context/selection.json": _json_bytes(selection_data),
        }
        if empty_review is not None:
            review_path = ReviewPath.EMPTY_REVIEW
            files["review-context/empty-review.json"] = _json_bytes(empty_review)
            artifact_keys = ("q2protocol", "evidence_search", "study_selection")
        else:
            review_path = ReviewPath.EVIDENCE_REVIEW
            collection_ref = _COMPLETED.validate_python(
                run.artifacts["study_data_collection"]
            )
            collection = self._data_collection_store.resolve(collection_ref)
            synthesis_ref = _COMPLETED.validate_python(
                run.artifacts["evidence_synthesis"]
            )
            synthesis = self._synthesis_store.resolve(synthesis_ref.artifact_id)
            grade_ref = _COMPLETED.validate_python(
                run.artifacts["grade_summary_of_findings"]
            )
            grade = self._grade_artifact_store.resolve(grade_ref.artifact_id)
            rob = _ROB.validate_python(run.artifacts["risk_of_bias"])
            files.update(
                {
                    "study-data/study-data-collection.json": collection.document_path.read_bytes(),
                    "study-data/risk-of-bias.json": _json_bytes(rob.data.document),
                    "analysis-data/synthesis.json": synthesis.document_path.read_bytes(),
                    "certainty/evidence-profiles.jsonl": (
                        grade.public_directory / "evidence-profiles.jsonl"
                    ).read_bytes(),
                    "certainty/summary-of-findings.json": (
                        grade.public_directory / "summary-of-findings.json"
                    ).read_bytes(),
                }
            )
            self._copy_optional_public(files, collection.public_directory, run.request.review_id)
            self._copy_optional_synthesis(files, synthesis.public_directory, run.request.review_id)
            artifact_keys = (
                "q2protocol",
                "evidence_search",
                "study_selection",
                "study_data_collection",
                "risk_of_bias",
                "evidence_synthesis",
                "grade_summary_of_findings",
            )
        files["review-context/artifact-index.json"] = _json_bytes(
            {
                "schema_version": "systematic-review-artifact-index.v1",
                "artifacts": [
                    _artifact_identity(run.artifacts[key]) for key in artifact_keys
                ],
            }
        )
        files["review-context/reporting-index.json"] = _json_bytes(
            build_reporting_index(files, review_path=review_path.value)
        )
        return self._evidence_store.persist(
            package_id=f"{run.run_id}:systematic-review-evidence",
            review_id=run.request.review_id,
            protocol_version=run.request.protocol_version,
            review_path=review_path,
            files=files,
        ).package

    def _selection_document(self, artifact: StudySelectionArtifact):
        package = self._selection_store.validate(artifact.package_ref)
        root = self._selection_store.resolve_manifest(artifact.package_ref).parent
        collections = {
            name: _jsonl(root / descriptor["path"])
            for name, descriptor in package["collections"].items()
        }
        return {"artifact": artifact, "collections": collections}

    @staticmethod
    def _copy_optional_public(files, root: Path, review_id: str) -> None:
        names = {
            "study-characteristics.jsonl": "study-data/study-characteristics.jsonl",
            "study-arms.csv": "study-data/study-arms.csv",
            "study-results.csv": "study-data/study-results.csv",
        }
        for suffix, target in names.items():
            path = root / f"{review_id}-{suffix}"
            if path.is_file():
                files[target] = path.read_bytes()

    @staticmethod
    def _copy_optional_synthesis(files, root: Path, review_id: str) -> None:
        for suffix in (
            "data-rows.csv",
            "subgroup-estimates.csv",
            "overall-estimates-and-settings.csv",
        ):
            path = root / f"{review_id}-{suffix}"
            if path.is_file():
                files[f"analysis-data/{suffix}"] = path.read_bytes()


def _artifact_identity(value) -> dict[str, object]:
    artifact_id = str(value.artifact_id)
    content_digest = getattr(value, "content_digest", None)
    return {
        "artifact_id": artifact_id,
        "schema_version": str(value.schema_version),
        "task": value.task.value,
        "content_digest": content_digest,
    }


def _jsonl(path: Path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(jsonable(value), ensure_ascii=False, sort_keys=True) + "\n"
    ).encode()
