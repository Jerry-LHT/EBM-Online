"""Factories for search retrieval infrastructure methods."""

from __future__ import annotations

from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.mesh_mapping.official.method import (
    build_method as build_official_mesh_mapping_method,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.method import (
    build_method as build_pubmed_pmc_method,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.textword_expansion.official.method import (
    build_method as build_official_textword_expansion_method,
)


def build_search_retrieval_method(*, method_name: str):
    if method_name != "pubmed_pmc":
        raise ValueError(f"Unknown method '{method_name}' for module 'search_retrieval'")
    return build_pubmed_pmc_method()


def build_search_mesh_mapping_method(*, method_name: str | None):
    if method_name is None:
        return None
    if method_name != "official":
        raise ValueError(f"Unknown method '{method_name}' for module 'search_retrieval_mesh_mapping'")
    return build_official_mesh_mapping_method()


def build_search_textword_expansion_method(*, method_name: str | None):
    if method_name is None:
        return None
    if method_name != "official":
        raise ValueError(f"Unknown method '{method_name}' for module 'search_retrieval_textword_expansion'")
    return build_official_textword_expansion_method()
