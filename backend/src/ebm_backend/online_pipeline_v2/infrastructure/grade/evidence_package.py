"""Deterministic GRADE evidence-package construction from persisted artifacts."""

from __future__ import annotations

import json

from pydantic import TypeAdapter

from ebm_backend.online_pipeline_v2.domain.common import (
    ArtifactEnvelope,
    CompletedArtifactRef,
)
from ebm_backend.online_pipeline_v2.domain.grade import GradeProtocol
from ebm_backend.online_pipeline_v2.domain.protocol import ProtocolDraft
from ebm_backend.online_pipeline_v2.domain.review_run import ReviewRun
from ebm_backend.online_pipeline_v2.domain.risk_of_bias import RiskOfBiasArtifact
from ebm_backend.online_pipeline_v2.domain.search import EvidenceSearchArtifact
from ebm_backend.online_pipeline_v2.domain.selection import StudySelectionArtifact
from ebm_backend.online_pipeline_v2.infrastructure.persistence.filesystem import (
    jsonable,
)


_COMPLETED = TypeAdapter(CompletedArtifactRef)
_ROB_ENVELOPE = TypeAdapter(ArtifactEnvelope[RiskOfBiasArtifact])
_SEARCH_ENVELOPE = TypeAdapter(ArtifactEnvelope[EvidenceSearchArtifact])
_SELECTION_ENVELOPE = TypeAdapter(ArtifactEnvelope[StudySelectionArtifact])


class FileGradeEvidencePackageBuilder:
    def __init__(
        self,
        *,
        data_collection_store,
        synthesis_store,
        grade_evidence_store,
        selection_store,
    ) -> None:
        self._data_collection_store = data_collection_store
        self._synthesis_store = synthesis_store
        self._grade_evidence_store = grade_evidence_store
        self._selection_store = selection_store

    def build(self, *, run: ReviewRun, protocol: ProtocolDraft):
        collection_ref = _COMPLETED.validate_python(
            run.artifacts["study_data_collection"]
        )
        collection = self._data_collection_store.resolve(collection_ref)
        synthesis_ref = _COMPLETED.validate_python(run.artifacts["evidence_synthesis"])
        synthesis = self._synthesis_store.resolve(synthesis_ref.artifact_id)
        selected = _SELECTION_ENVELOPE.validate_python(run.artifacts["study_selection"])
        if selected.data is None:
            raise ValueError("Study Selection data are missing")
        selection = self._selection_store.validate(selected.data.package_ref)
        selection_manifest = self._selection_store.resolve_manifest(
            selected.data.package_ref
        )
        selection_root = selection_manifest.parent
        selection_collections = {
            name: _jsonl(selection_root / descriptor["path"])
            for name, descriptor in selection["collections"].items()
        }
        characteristics_path = (
            collection.public_directory
            / f"{run.request.review_id}-study-characteristics.jsonl"
        )
        rob = _ROB_ENVELOPE.validate_python(run.artifacts["risk_of_bias"])
        search = _SEARCH_ENVELOPE.validate_python(run.artifacts["evidence_search"])
        files = {
            "protocol.json": _json_bytes(GradeProtocol.from_protocol(protocol)),
            "search.json": _json_bytes(search.data),
            "selection.json": _json_bytes(
                {
                    "artifact": selected.data,
                    "collections": selection_collections,
                }
            ),
            "study-characteristics.jsonl": characteristics_path.read_bytes(),
            "risk-of-bias.json": _json_bytes(rob.data.document),
            "synthesis.json": (synthesis.document_path.read_bytes()),
        }
        for name in (
            "data-rows.csv",
            "subgroup-estimates.csv",
            "overall-estimates-and-settings.csv",
        ):
            path = synthesis.public_directory / f"{run.request.review_id}-{name}"
            if path.is_file():
                files[f"meta-analysis/{name}"] = path.read_bytes()
        return self._grade_evidence_store.persist(
            package_id=f"{run.run_id}:grade-evidence",
            review_id=run.request.review_id,
            protocol_version=run.request.protocol_version,
            files=files,
        ).package


def _jsonl(path) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(jsonable(value), ensure_ascii=False, sort_keys=True) + "\n"
    ).encode()
