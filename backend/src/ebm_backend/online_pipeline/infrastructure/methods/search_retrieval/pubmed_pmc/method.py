"""PubMed/PMC retrieval method."""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from ebm_backend.online_pipeline.domain.article import (
    SearchRetrievalWarning,
    SearchSourceResult,
)
from ebm_backend.online_pipeline.domain.module_config import ModuleRunConfig
from ebm_backend.online_pipeline.domain.search import SearchQueryPlan
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.mesh_mapping_official.method import (
    Method as OfficialMeshMappingMethod,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.errors import (
    SearchRetrievalStageError,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.service import SearchRetrievalService
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.cache import (
    PubMedPmcFileCache,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.textword_expansion_official.method import (
    Method as OfficialTextwordExpansionMethod,
)
@dataclass(frozen=True)
class Method:
    service: SearchRetrievalService = field(default_factory=SearchRetrievalService)
    mesh_mapping_method: OfficialMeshMappingMethod | None = None
    textword_expansion_method: OfficialTextwordExpansionMethod | None = None

    def run(self, *, query_plan: SearchQueryPlan, config: ModuleRunConfig) -> SearchSourceResult:
        concepts = list(query_plan.concepts)
        warnings: list[SearchRetrievalWarning] = []
        if self.mesh_mapping_method is not None:
            mapped_concepts = []
            for concept in concepts:
                try:
                    mapped_concepts.extend(
                        self.mesh_mapping_method.run(concepts=[concept])
                    )
                except SearchRetrievalStageError as exc:
                    mapped_concepts.append(concept)
                    warnings.append(
                        SearchRetrievalWarning(
                            code="mesh_enrichment_failed",
                            message="MeSH enrichment failed; base text terms were retained.",
                            stage=exc.stage,
                            concept_slot=concept.slot,
                            concept_text=concept.source_text,
                            attempts=exc.attempts,
                        )
                    )
            concepts = mapped_concepts
        if self.textword_expansion_method is not None:
            concepts = self.textword_expansion_method.run(concepts=concepts)
        return self.service.run(
            query_plan=replace(query_plan, concepts=concepts),
            config=config,
            warnings=warnings,
        )


def build_method(*, cache: PubMedPmcFileCache | None = None) -> Method:
    return Method(
        service=SearchRetrievalService(cache=cache),
        mesh_mapping_method=OfficialMeshMappingMethod(),
        textword_expansion_method=OfficialTextwordExpansionMethod(),
    )
