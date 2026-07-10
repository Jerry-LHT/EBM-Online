from __future__ import annotations

import pytest

from ebm_backend.online_pipeline.application.use_cases.run_search_retrieval import (
    TRIAL_FILTER,
    _assemble_search_query,
    _select_search_concepts,
)
from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.search import SearchMeshHeading, SearchQueryConcept


def test_select_search_concepts_prefers_population_and_intervention_and_ignores_outcome() -> None:
    concepts = _select_search_concepts(
        question_pico=QuestionPICO(
            P=["Adults with depression"],
            I=["SSRI"],
            C=["placebo"],
            O=["remission"],
        )
    )

    assert [concept.slot for concept in concepts] == ["P", "I"]
    assert concepts[0].normalized_concept == "depression"
    assert concepts[1].normalized_concept == "ssri"


def test_select_search_concepts_uses_comparator_when_intervention_missing() -> None:
    concepts = _select_search_concepts(question_pico=QuestionPICO(P=["Children with asthma"], C=["usual care"]))

    assert [concept.slot for concept in concepts] == ["P", "C"]
    assert concepts[1].normalized_concept == "usual care"


def test_assemble_search_query_adds_mesh_text_terms_and_rct_filter() -> None:
    concepts = [
        SearchQueryConcept(
            slot="P",
            source_text="Adults with hypertension",
            normalized_concept="hypertension",
            base_text_terms=["hypertension"],
            expanded_text_terms=["high blood pressure"],
            mesh_terms=[SearchMeshHeading(descriptor_ui="D006973", heading="Hypertension")],
        ),
        SearchQueryConcept(
            slot="I",
            source_text="Aerobic exercise",
            normalized_concept="aerobic exercise",
            base_text_terms=["aerobic exercise"],
        ),
    ]

    plan = _assemble_search_query(concepts=concepts, constraints=WorkflowConstraints())

    assert "Hypertension[MeSH Terms]" in plan.search_query
    assert '"high blood pressure"[Title/Abstract]' in plan.search_query
    assert '"aerobic exercise"[Title/Abstract]' in plan.search_query
    assert TRIAL_FILTER in plan.search_query


def test_select_search_concepts_rejects_empty_searchable_terms() -> None:
    with pytest.raises(ValueError, match="requires at least one searchable"):
        _select_search_concepts(question_pico=QuestionPICO(O=["mortality"]))
