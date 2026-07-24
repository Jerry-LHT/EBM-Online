from __future__ import annotations

from dataclasses import dataclass

from ebm_backend.online_pipeline.domain.search import SearchQueryConcept
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.mesh_mapping_official.method import (
    Method,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.official_mesh import (
    OfficialMeshDescriptor,
)


@dataclass(frozen=True)
class _FakeMeshClient:
    def resolve(self, *, label: str) -> OfficialMeshDescriptor | None:
        if label == "hypertension":
            return OfficialMeshDescriptor(
                descriptor_ui="D006973",
                heading="Hypertension",
                entry_terms=["Blood Pressure, High"],
            )
        return None


def test_mesh_mapping_method_adds_heading_and_entry_terms() -> None:
    method = Method(client=_FakeMeshClient())

    concepts = method.run(
        concepts=[
            SearchQueryConcept(
                slot="P",
                source_text="Adults with hypertension",
                normalized_concept="hypertension",
                base_text_terms=["hypertension"],
            )
        ]
    )

    assert concepts[0].mesh_terms[0].heading == "Hypertension"
    assert concepts[0].mesh_entry_terms == ["Blood Pressure, High"]
