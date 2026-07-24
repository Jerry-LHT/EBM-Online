from __future__ import annotations

import pytest

from ebm_backend.online_pipeline.application.use_cases.run_search_retrieval import (
    _build_search_query_plan,
    _select_search_concepts,
)
from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.search import SearchMeshHeading, SearchQueryConcept
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.query_builder import (
    TRIAL_FILTER,
    build_pubmed_query,
)


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

    plan = _build_search_query_plan(concepts=concepts)
    query = build_pubmed_query(
        query_plan=plan,
        constraints=WorkflowConstraints(),
    )

    assert '"Hypertension"[MeSH Terms]' in query
    assert '"high blood pressure"[Title/Abstract]' in query
    assert '"aerobic exercise"[Title/Abstract]' in query
    assert TRIAL_FILTER in query


def test_pubmed_query_ors_values_within_slot_and_ands_across_slots() -> None:
    query = build_pubmed_query(
        query_plan=_build_search_query_plan(
            concepts=[
                SearchQueryConcept(
                    slot="P",
                    source_text="depression",
                    normalized_concept="depression",
                    base_text_terms=["depression"],
                ),
                SearchQueryConcept(
                    slot="P",
                    source_text="major depressive disorder",
                    normalized_concept="major depressive disorder",
                    base_text_terms=["major depressive disorder"],
                ),
                SearchQueryConcept(
                    slot="I",
                    source_text="SSRI",
                    normalized_concept="ssri",
                    base_text_terms=["ssri"],
                ),
            ]
        ),
        constraints=WorkflowConstraints(study_design=""),
    )

    assert '(("depression"[Title/Abstract]) OR ("major depressive disorder"[Title/Abstract]))' in query
    assert ') AND (("ssri"[Title/Abstract]))' in query
    assert TRIAL_FILTER not in query


def test_pubmed_query_sanitizes_user_controlled_syntax() -> None:
    query = build_pubmed_query(
        query_plan=_build_search_query_plan(
            concepts=[
                SearchQueryConcept(
                    slot="P",
                    source_text='depression" OR review[pt]',
                    normalized_concept='depression" OR review[pt]',
                    base_text_terms=['depression" OR review[pt]'],
                )
            ]
        ),
        constraints=WorkflowConstraints(study_design=""),
    )

    assert 'review[pt]' not in query
    assert '"depression OR review pt"[Title/Abstract]' in query


def test_select_search_concepts_rejects_empty_searchable_terms() -> None:
    with pytest.raises(ValueError, match="requires at least one searchable"):
        _select_search_concepts(question_pico=QuestionPICO(O=["mortality"]))
