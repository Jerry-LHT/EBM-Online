"""Official NLM MeSH mapping adapter."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from ebm_backend.online_pipeline.domain.search import SearchMeshHeading, SearchQueryConcept
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.shared.official_mesh_support import (
    OfficialMeshLookupClient,
)


@dataclass(frozen=True)
class Method:
    client: OfficialMeshLookupClient = field(default_factory=OfficialMeshLookupClient)

    def run(self, *, concepts: list[SearchQueryConcept]) -> list[SearchQueryConcept]:
        mapped: list[SearchQueryConcept] = []
        for concept in concepts:
            descriptor = self.client.resolve(label=concept.normalized_concept)
            if descriptor is None:
                mapped.append(concept)
                continue
            mapped.append(
                replace(
                    concept,
                    mesh_terms=[
                        SearchMeshHeading(
                            descriptor_ui=descriptor.descriptor_ui,
                            heading=descriptor.heading,
                            explode=True,
                        )
                    ],
                    mesh_entry_terms=list(descriptor.entry_terms),
                )
            )
        return mapped


def build_method() -> Method:
    return Method()
