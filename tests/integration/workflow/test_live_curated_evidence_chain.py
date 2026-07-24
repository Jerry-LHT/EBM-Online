"""Opt-in complete evidence-chain run over two manually curated real RCTs."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path

import pytest

from ebm_backend.online_pipeline.application.use_cases.run_online_ebm_workflow import (
    RunOnlineEBMWorkflow,
)
from ebm_backend.online_pipeline.application.use_cases.run_article_qualification import (
    RunArticleQualification,
)
from ebm_backend.online_pipeline.domain.article import (
    ArticleMetadata,
    ArticleSection,
    ArticleSource,
    ArticleTable,
    ArticleXmlContent,
    CleanedArticle,
    SearchRetrievalResult,
    SearchSourceResult,
)
from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.module_config import ModuleRunConfig
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.screening import (
    ScreeningCriteria,
    ScreeningDecision,
    StudyScreeningResult,
)
from ebm_backend.online_pipeline.domain.serialization import to_jsonable
from ebm_backend.online_pipeline.infrastructure.methods.article_qualification.factory import (
    build_production_article_qualifier,
)
from ebm_backend.online_pipeline.interfaces.api.dependencies import (
    get_grade_use_case_for_api,
    get_meta_analysis_use_case_for_api,
    get_risk_of_bias_use_case_for_api,
    get_study_pio_use_case_for_api,
)


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_CURATED_WORKFLOW") != "1",
    reason="Set RUN_LIVE_CURATED_WORKFLOW=1 to run the curated evidence-chain case.",
)

REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_ROOT = REPO_ROOT / "tests/fixtures/meta_analysis/live_e2e_koos_quality_of_life"
ARTICLE_PATHS = (
    FIXTURE_ROOT / "janyacharoen_2018.json",
    FIXTURE_ROOT / "li_2020.json",
)
FULL_TEXT_PATHS = (
    REPO_ROOT / "benchmark/online_pipeline/raw_data/cleaned_articles/pmc__PMC6323346.json",
    REPO_ROOT / "benchmark/online_pipeline/raw_data/cleaned_articles/pmc__PMC7367519.json",
)
QUESTION_TEXT = (
    "In adults with knee osteoarthritis, does a structured exercise or "
    "physiotherapist-supported physical activity programme, compared with an "
    "inactive or delayed-programme control, improve knee-related quality of life "
    "on the KOOS 0-to-100 scale at the end of 12 to 13 weeks?"
)
QUESTION_PICO = QuestionPICO(
    P=["adults with knee osteoarthritis"],
    I=["structured exercise or physiotherapist-supported physical activity programme"],
    C=["inactive control or delayed-programme control"],
    O=["KOOS knee-related quality of life at 12 to 13 weeks"],
)
SCREENING_CRITERIA = ScreeningCriteria(
    inclusion_criteria=[
        "Individually randomized parallel-group trials in adults with knee osteoarthritis.",
        "Compare structured exercise or supported physical activity with an inactive or delayed-programme control.",
        "Report KOOS knee-related quality of life on its 0-to-100 scale.",
        "Report post-intervention means, standard deviations, and assessed participants at 12 to 13 weeks.",
    ],
    exclusion_criteria=[
        "Exclude active-comparator-only trials.",
        "Exclude reports without arm-level KOOS quality-of-life data.",
    ],
    rationale="Two manually reviewed primary RCT reports form this curated integration case.",
)


@dataclass(frozen=True)
class _ProtocolQ2PICO:
    def execute(self, **_kwargs) -> QuestionPICO:
        return QUESTION_PICO


@dataclass(frozen=True)
class _CuratedRetrieval:
    articles: list[CleanedArticle]

    def execute(self, **_kwargs) -> SearchRetrievalResult:
        source_result = SearchSourceResult(
            source_name="curated_real_rct_fixture",
            search_query="manual integration-case selection from previously retrieved PMC RCTs",
            query_used="manual integration-case selection",
            total_hits=len(self.articles),
            returned_count=len(self.articles),
            articles=self.articles,
        )
        return SearchRetrievalResult(
            returned_count=len(self.articles),
            source_results=[source_result],
            articles=self.articles,
        )


@dataclass(frozen=True)
class _CuratedScreening:
    articles: list[CleanedArticle]

    def prepare_criteria(self, **_kwargs) -> ScreeningCriteria:
        return SCREENING_CRITERIA

    def execute(self, **_kwargs) -> StudyScreeningResult:
        included = [article.study_id for article in self.articles]
        return StudyScreeningResult(
            screening_criteria=SCREENING_CRITERIA,
            decisions=[
                ScreeningDecision(
                    study_id=study_id,
                    decision="include",
                    rationale=(
                        "Manual integration-case review confirmed primary parallel RCT design, "
                        "eligible PICO, and an extractable KOOS result table."
                    ),
                )
                for study_id in included
            ],
            included_studies=included,
            included_articles=included,
            meta_ready_studies=included,
        )


def test_curated_real_rcts_run_to_computed_meta_and_grade(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_dir = Path(
        os.getenv("CURATED_WORKFLOW_ARTIFACT_DIR") or tmp_path / "artifacts"
    )
    artifact_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("EBM_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.setenv("SUBTASK2_TARGETED_DEBUG_DIR", str(artifact_dir / "subtask2_debug"))
    monkeypatch.setenv("SUBTASK2_TARGETED_TASK_WORKERS", "1")
    monkeypatch.setenv("SUBTASK2_TARGETED_SOURCE_WORKERS", "2")
    monkeypatch.setenv("SUBTASK2_TARGETED_SOURCE_SKILL_WORKERS", "2")
    monkeypatch.setenv("SUBTASK2_TARGETED_INITIAL_SOURCE_WORKERS", "1")
    monkeypatch.setenv("SUBTASK2_TARGETED_CANDIDATE_WORKERS", "1")

    articles = [
        _cleaned_article(table_path, full_text_path)
        for table_path, full_text_path in zip(
            ARTICLE_PATHS,
            FULL_TEXT_PATHS,
            strict=True,
        )
    ]
    result = RunOnlineEBMWorkflow(
        q2pico=_ProtocolQ2PICO(),  # type: ignore[arg-type]
        search_retrieval=_CuratedRetrieval(articles),  # type: ignore[arg-type]
        article_qualification=RunArticleQualification(
            qualifier=build_production_article_qualifier(
                cache_root=tmp_path / "runtime" / "cache" / "article_qualification_content_v1"
            )
        ),
        study_screening=_CuratedScreening(articles),  # type: ignore[arg-type]
        study_pio=get_study_pio_use_case_for_api(),
        risk_of_bias=get_risk_of_bias_use_case_for_api(),
        meta_analysis=get_meta_analysis_use_case_for_api(),
        grade=get_grade_use_case_for_api(),
    ).execute(
        review_id="curated-koos-evidence-chain-v1",
        question_text=QUESTION_TEXT,
        constraints=WorkflowConstraints(study_design="RCT"),
        retrieval_config=ModuleRunConfig(
            max_candidates_per_source=2,
            max_results_per_source=2,
        ),
    )

    serialized = to_jsonable(result)
    (artifact_dir / "result.json").write_text(
        json.dumps(serialized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    assert result.status == "succeeded"
    assert len(result.study_pio) == 2
    assert len(result.risk_of_bias) == 2
    assert result.meta_analysis is not None
    included_rows = [
        row
        for row in result.meta_analysis.meta_analysis_data_rows
        if row.analysis_status == "included"
    ]
    assert len(included_rows) == 2
    assert math.isclose(
        sum(float(row.weight_fraction) for row in included_rows),
        1.0,
        rel_tol=0.0,
        abs_tol=1e-12,
    )
    computed = [
        estimate
        for estimate in result.meta_analysis.overall_estimates
        if estimate.estimation_status.value == "computed"
    ]
    assert len(computed) == 1
    assert computed[0].study_count == 2
    assert computed[0].participant_count == 88
    assert result.grade is not None
    assert len(result.grade.sof_rows) == 1
    judgements = result.grade.sof_rows[0].domain_judgements
    assert set(to_jsonable(judgements)) == {
        "risk_of_bias",
        "inconsistency",
        "indirectness",
        "imprecision",
    }
    assert "articles" not in serialized["search_retrieval"]


def _cleaned_article(table_path: Path, full_text_path: Path) -> CleanedArticle:
    payload = json.loads(table_path.read_text(encoding="utf-8"))
    full_text_payload = json.loads(full_text_path.read_text(encoding="utf-8"))
    metadata = payload.get("metadata") or {}
    source = payload.get("source") or {}
    xml = full_text_payload.get("xml_content") or {}
    tables = []
    for index, table in enumerate(payload.get("tables") or [], start=1):
        rows = [dict(row) for row in table.get("rows") or [] if isinstance(row, dict)]
        raw_xml = table.get("raw_xml")
        if raw_xml and not any(row.get("_raw_xml") for row in rows):
            rows.append({"_raw_xml": str(raw_xml)})
        tables.append(
            ArticleTable(
                table_id=str(table.get("table_id") or f"t{index}"),
                caption=str(table.get("caption") or ""),
                rows=rows,
            )
        )
    return CleanedArticle(
        study_id=str(payload["study_id"]),
        metadata=ArticleMetadata(
            title=str(metadata.get("title") or ""),
            pmid=_optional_text(metadata.get("pmid")),
            pmc_id=_optional_text(metadata.get("pmc_id")),
            source_type=_optional_text(metadata.get("source_type")),
            publication_year=_optional_text(metadata.get("publication_year")),
            mesh_terms=[str(item) for item in metadata.get("mesh_terms") or []],
            doi=_optional_text(metadata.get("doi")),
        ),
        xml_content=ArticleXmlContent(
            sections=[
                ArticleSection(
                    section_id=str(section.get("section_id") or f"section-{index}"),
                    title=str(section.get("title") or ""),
                    text=str(section.get("text") or ""),
                )
                for index, section in enumerate(xml.get("sections") or [], start=1)
                if isinstance(section, dict)
            ]
        ),
        tables=tables,
        source=ArticleSource(
            database=str(source.get("database") or "copied-real-rct-fixture"),
            retrieval_rank=source.get("retrieval_rank"),
            retrieval_score=source.get("retrieval_score"),
            raw_source_url=_optional_text(source.get("raw_source_url")),
            raw_record_id=_optional_text(source.get("raw_record_id")),
        ),
    )


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
