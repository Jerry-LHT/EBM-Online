from __future__ import annotations

from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.factory import (
    build_search_mesh_mapping_method,
    build_search_retrieval_method,
    build_search_textword_expansion_method,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.mesh_mapping.official.method import (
    Method as OfficialMeshMappingMethod,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.method import (
    Method as PubMedPMCMethod,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.textword_expansion.official.method import (
    Method as OfficialTextwordExpansionMethod,
)


def test_factory_builds_search_retrieval_method() -> None:
    method = build_search_retrieval_method(method_name="pubmed_pmc")

    assert isinstance(method, PubMedPMCMethod)


def test_factory_builds_search_retrieval_capability_methods() -> None:
    mesh_method = build_search_mesh_mapping_method(method_name="official")
    textword_method = build_search_textword_expansion_method(method_name="official")

    assert isinstance(mesh_method, OfficialMeshMappingMethod)
    assert isinstance(textword_method, OfficialTextwordExpansionMethod)
