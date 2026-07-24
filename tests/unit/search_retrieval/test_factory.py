from __future__ import annotations

from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.factory import (
    build_search_retrieval_source,
    build_search_retrieval_sources,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.method import (
    Method as PubMedPMCMethod,
)
import pytest


def test_factory_builds_pubmed_source_pipeline() -> None:
    method = build_search_retrieval_source(source_name="pubmed")

    assert isinstance(method, PubMedPMCMethod)
    assert method.mesh_mapping_method is not None
    assert method.textword_expansion_method is not None


def test_factory_builds_ordered_search_retrieval_sources() -> None:
    methods = build_search_retrieval_sources(source_names=["pubmed"])

    assert len(methods) == 1
    assert isinstance(methods[0], PubMedPMCMethod)


def test_factory_rejects_unimplemented_source() -> None:
    with pytest.raises(ValueError, match="Unknown search retrieval source"):
        build_search_retrieval_source(source_name="embase")
