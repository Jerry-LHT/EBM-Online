from __future__ import annotations

from ebm_backend.online_pipeline.domain.article import (
    ArticleMetadata,
    ArticleSection,
    ArticleXmlContent,
    CleanedArticle,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.section_selector import (
    select_screening_sections,
)


def test_select_screening_sections_prioritizes_relevant_titles() -> None:
    article = CleanedArticle(
        study_id="pmc::1",
        metadata=ArticleMetadata(title="Trial"),
        xml_content=ArticleXmlContent(
            sections=[
                ArticleSection(section_id="s1", title="Background", text="Background"),
                ArticleSection(section_id="s2", title="Methods", text="Methods text"),
                ArticleSection(section_id="s3", title="Participants", text="Participants text"),
                ArticleSection(section_id="s4", title="Results", text="Results text"),
            ]
        ),
    )

    selected = select_screening_sections(article, max_sections=4)

    assert [item.label for item in selected[:3]] == ["methods", "participants", "results"]


def test_select_screening_sections_falls_back_to_remaining_sections() -> None:
    article = CleanedArticle(
        study_id="pmc::2",
        metadata=ArticleMetadata(title="Trial"),
        xml_content=ArticleXmlContent(
            sections=[
                ArticleSection(section_id="s1", title="Intro", text="Intro text"),
                ArticleSection(section_id="s2", title="Misc", text="Misc text"),
            ]
        ),
    )

    selected = select_screening_sections(article, max_sections=2)

    assert len(selected) == 2
    assert selected[0].label == "other"
