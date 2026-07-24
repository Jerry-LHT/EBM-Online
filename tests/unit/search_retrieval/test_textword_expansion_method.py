from __future__ import annotations

from ebm_backend.online_pipeline.domain.search import SearchQueryConcept
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.textword_expansion_official.method import (
    Method,
)


def test_textword_expansion_uses_official_entry_terms() -> None:
    method = Method()

    concepts = method.run(
        concepts=[
            SearchQueryConcept(
                slot="P",
                source_text="Adults with hypertension",
                normalized_concept="hypertension",
                base_text_terms=["hypertension"],
                mesh_entry_terms=["Blood Pressure, High"],
            )
        ]
    )

    assert concepts[0].expanded_text_terms == ["high blood pressure"]
