from __future__ import annotations

import os
from pathlib import Path
import time
from xml.etree import ElementTree

import pytest

from ebm_backend.online_pipeline.application.use_cases.run_meta_analysis import (
    RunMetaAnalysis,
)
from ebm_backend.online_pipeline.application.use_cases.run_study_screening import (
    RunStudyScreening,
)
from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.serialization import to_jsonable
from ebm_backend.online_pipeline.infrastructure.llm import load_llm_config
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.factory import (
    build_production_analysis_methods_selector,
    build_production_overall_estimates_calculator,
    build_production_study_evidence_agent,
    build_production_subgroup_analyzer,
    build_production_synthesis_planner,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.cache import (
    PubMedPmcFileCache,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.models import (
    PubMedArticleMetadata,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.pmc_client import (
    PmcClient,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.pubmed_client import (
    PubMedClient,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.xml_cleaner import (
    clean_article_xml,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.factory import (
    build_production_staged_study_screening,
)
from ebm_backend.online_pipeline.infrastructure.persistence.atomic_io import (
    atomic_write_json,
)


PMC_IDS = (
    "PMC13366800",
    "PMC13292499",
    "PMC13283522",
    "PMC13225549",
    "PMC13110886",
    "PMC13092434",
    "PMC13092002",
    "PMC13084466",
    "PMC13067538",
    "PMC12986947",
    "PMC12983056",
    "PMC13093945",
    "PMC12951634",
    "PMC12864078",
    "PMC12841921",
    "PMC12829467",
    "PMC12799615",
    "PMC12748713",
    "PMC12853788",
    "PMC12714805",
    "PMC12699666",
    "PMC12692818",
)
QUESTION = (
    "In adults with knee osteoarthritis, does exercise, compared with attention "
    "control, placebo, no treatment, usual care, or limited education, reduce "
    "knee pain immediately after the intervention?"
)
PICO = QuestionPICO(
    P=["adults with knee osteoarthritis"],
    I=["exercise"],
    C=[
        "attention control",
        "placebo",
        "no treatment",
        "usual care",
        "limited education",
    ],
    O=["knee pain", "immediately after the intervention"],
)


pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_STAGED_SCREENING") != "1",
    reason="Set RUN_LIVE_STAGED_SCREENING=1 for real PMC and LLM calls.",
)


def test_live_staged_screening_on_real_pmc_articles() -> None:
    config = load_llm_config().to_dict()
    config["model"] = os.getenv("LIVE_STAGED_MODEL", "gpt-5.4-mini")
    config["sdk_max_retries"] = 0
    config["json_marker_retry_enabled"] = False
    cache = PubMedPmcFileCache(Path(".runtime/online_pipeline/cache"))
    articles = _load_articles(cache=cache)
    methods = build_production_staged_study_screening(config=config)
    screening = RunStudyScreening(
        criteria_planner=methods.criteria_planner,
        coarse_screener=methods.coarse_screener,
        synthesis_ready_screener=methods.synthesis_ready_screener,
        max_workers=int(os.getenv("LIVE_STAGED_WORKERS", "4")),
    )
    meta = RunMetaAnalysis(
        synthesis_planner=build_production_synthesis_planner(config=config),
        study_evidence_agent=build_production_study_evidence_agent(config=config),
        analysis_methods_selector=build_production_analysis_methods_selector(),
        subgroup_analyzer=build_production_subgroup_analyzer(),
        overall_estimates_calculator=build_production_overall_estimates_calculator(),
    )
    constraints = WorkflowConstraints()

    started = time.monotonic()
    criteria_started = time.monotonic()
    criteria = screening.prepare_criteria(
        question_text=QUESTION,
        question_pico=PICO,
        constraints=constraints,
    )
    criteria_seconds = time.monotonic() - criteria_started
    plan_started = time.monotonic()
    plan = meta.plan(
        review_id="live-knee-exercise-screening",
        question_text=QUESTION,
        question_pico=PICO,
        screening_criteria=criteria,
    )
    plan_seconds = time.monotonic() - plan_started
    screening_started = time.monotonic()
    result = screening.execute(
        question_text=QUESTION,
        question_pico=PICO,
        constraints=constraints,
        articles=articles,
        criteria=criteria,
        synthesis_plan=plan,
    )
    screening_seconds = time.monotonic() - screening_started

    assert len(result.coarse_decisions) == len(PMC_IDS)
    assert len(result.decisions) == len(PMC_IDS)
    assert [row.study_id for row in result.decisions] == [
        f"pmc::{pmcid}" for pmcid in PMC_IDS
    ]
    assert all(row.evidence_char_count <= 18_000 for row in result.coarse_decisions)
    assert all(
        row.evidence_char_count <= 64_000
        for row in result.decisions
        if row.evidence_char_count
    )

    output_path = Path(
        os.getenv(
            "LIVE_STAGED_OUTPUT",
            "/tmp/ebm_live_staged_screening_22.json",
        )
    )
    atomic_write_json(
        output_path,
        {
            "model": config["model"],
            "question": QUESTION,
            "question_pico": PICO,
            "criteria": criteria,
            "synthesis_plan": plan,
            "screening_result": result,
            "article_source_summary": [
                {
                    "study_id": article.study_id,
                    "title": article.metadata.title,
                    "section_count": len(article.xml_content.sections),
                    "table_count": len(article.tables),
                    "section_chars": sum(
                        len(section.text) for section in article.xml_content.sections
                    ),
                    "raw_table_chars": sum(
                        len(table.raw_xml or "") for table in article.tables
                    ),
                }
                for article in articles
            ],
            "timing_seconds": {
                "criteria": criteria_seconds,
                "planning": plan_seconds,
                "screening": screening_seconds,
                "total": time.monotonic() - started,
            },
        },
    )
    print(
        to_jsonable(
            {
                "output": str(output_path),
                "coarse_advanced": sum(
                    row.decision == "advance" for row in result.coarse_decisions
                ),
                "included": result.included_studies,
                "methodologically_eligible_unsupported": (
                    result.methodologically_eligible_unsupported_studies
                ),
                "timing_seconds": {
                    "criteria": criteria_seconds,
                    "planning": plan_seconds,
                    "screening": screening_seconds,
                },
            }
        )
    )


def _load_articles(*, cache: PubMedPmcFileCache):
    pmc_client = PmcClient(timeout=60, retries=1)
    xml_by_pmcid: dict[str, str] = {}
    missing: list[str] = []
    for pmcid in PMC_IDS:
        xml_text = cache.get_xml(pmcid=pmcid)
        if xml_text is None:
            missing.append(pmcid)
        else:
            xml_by_pmcid[pmcid] = xml_text
    for start in range(0, len(missing), 5):
        fetched = pmc_client.fetch_full_text_xml(pmcids=missing[start : start + 5])
        for pmcid, xml_text in fetched.items():
            cache.put_xml(pmcid=pmcid, xml_text=xml_text)
            xml_by_pmcid[pmcid] = xml_text
    unresolved = [pmcid for pmcid in PMC_IDS if pmcid not in xml_by_pmcid]
    if unresolved:
        raise AssertionError(f"PMC full text unavailable for: {unresolved}")

    pmid_by_pmcid = {
        pmcid: _article_id(xml_by_pmcid[pmcid], id_type="pmid")
        for pmcid in PMC_IDS
    }
    pmids = [pmid for pmid in pmid_by_pmcid.values() if pmid]
    metadata_by_pmid: dict[str, PubMedArticleMetadata] = {}
    pubmed = PubMedClient(timeout=60, retries=1)
    for start in range(0, len(pmids), 10):
        metadata_by_pmid.update(pubmed.fetch_metadata(pmids=pmids[start : start + 10]))

    articles = []
    for rank, pmcid in enumerate(PMC_IDS, start=1):
        xml_text = xml_by_pmcid[pmcid]
        pmid = pmid_by_pmcid[pmcid]
        metadata = metadata_by_pmid.get(pmid or "") or PubMedArticleMetadata(
            pmid=pmid or pmcid,
            title=_article_title(xml_text) or pmcid,
            publication_year=_article_year(xml_text),
        )
        articles.append(
            clean_article_xml(
                xml_text=xml_text,
                metadata=metadata,
                pmcid=pmcid,
                retrieval_rank=rank,
            )
        )
    return articles


def _article_id(xml_text: str, *, id_type: str) -> str | None:
    root = ElementTree.fromstring(xml_text)
    node = root.find(f".//article-id[@pub-id-type='{id_type}']")
    text = "".join(node.itertext()).strip() if node is not None else ""
    return text or None


def _article_title(xml_text: str) -> str:
    root = ElementTree.fromstring(xml_text)
    node = root.find(".//article-title")
    return " ".join("".join(node.itertext()).split()) if node is not None else ""


def _article_year(xml_text: str) -> str | None:
    root = ElementTree.fromstring(xml_text)
    for node in root.findall(".//pub-date/year"):
        text = "".join(node.itertext()).strip()
        if len(text) == 4 and text.isdigit():
            return text
    return None
