from __future__ import annotations

from dataclasses import dataclass

from ebm_backend.online_pipeline.domain.search import SearchQueryConcept
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.shared.official_mesh_support import (
    OfficialMeshDescriptor,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.textword_expansion.official.method import (
    Method,
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


def test_textword_expansion_uses_official_entry_terms() -> None:
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

    assert concepts[0].expanded_text_terms == ["high blood pressure"]
