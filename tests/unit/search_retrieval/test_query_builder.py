from __future__ import annotations

import pytest

from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.search import SearchQueryConcept, SearchQueryPlan
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.query_builder import (
    TRIAL_FILTER,
    build_pubmed_query,
)


def test_pubmed_query_ors_values_within_slot_and_ands_across_slots() -> None:
    query = build_pubmed_query(
        query_plan=SearchQueryPlan(
            concepts=[
                _concept(slot="P", term="depression"),
                _concept(slot="P", term="major depressive disorder"),
                _concept(slot="I", term="ssri"),
            ]
        ),
        constraints=WorkflowConstraints(study_design=""),
    )

    assert (
        '(("depression"[Title/Abstract]) OR '
        '("major depressive disorder"[Title/Abstract]))'
    ) in query
    assert ') AND (("ssri"[Title/Abstract]))' in query
    assert TRIAL_FILTER not in query


def test_pubmed_query_adds_rct_filter_only_when_requested() -> None:
    plan = SearchQueryPlan(concepts=[_concept(slot="P", term="depression")])

    rct_query = build_pubmed_query(
        query_plan=plan,
        constraints=WorkflowConstraints(study_design="RCT"),
    )
    unrestricted_query = build_pubmed_query(
        query_plan=plan,
        constraints=WorkflowConstraints(study_design=""),
    )

    assert TRIAL_FILTER in rct_query
    assert TRIAL_FILTER not in unrestricted_query


def test_pubmed_query_sanitizes_user_controlled_syntax() -> None:
    query = build_pubmed_query(
        query_plan=SearchQueryPlan(
            concepts=[
                _concept(
                    slot="P",
                    term='depression" OR review[pt]',
                )
            ]
        ),
        constraints=WorkflowConstraints(study_design=""),
    )

    assert "review[pt]" not in query
    assert '"depression OR review pt"[Title/Abstract]' in query


def test_pubmed_query_adds_publication_year_range() -> None:
    query = build_pubmed_query(
        query_plan=SearchQueryPlan(
            concepts=[_concept(slot="P", term="knee osteoarthritis")]
        ),
        constraints=WorkflowConstraints(
            study_design="RCT",
            publication_year_range="2018-2020",
        ),
    )

    assert '("2018"[Date - Publication] : "2020"[Date - Publication])' in query


@pytest.mark.parametrize("value", ["2020", "2021-2020", "abcd-2020"])
def test_pubmed_query_rejects_invalid_publication_year_range(value: str) -> None:
    with pytest.raises(ValueError, match="publication_year_range"):
        build_pubmed_query(
            query_plan=SearchQueryPlan(
                concepts=[_concept(slot="P", term="knee osteoarthritis")]
            ),
            constraints=WorkflowConstraints(
                study_design="RCT",
                publication_year_range=value,
            ),
        )


def _concept(*, slot: str, term: str) -> SearchQueryConcept:
    return SearchQueryConcept(
        slot=slot,
        source_text=term,
        normalized_concept=term,
        base_text_terms=[term],
    )
