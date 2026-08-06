from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from benchmark.ebm_application.beyond_abstracts.dataset import build_pilot_dataset
from benchmark.ebm_application.beyond_abstracts.io import load_case, load_gold, read_json


ARTICLE_XML = """<article><front><article-meta><abstract><p>XML abstract</p></abstract></article-meta></front>
<body><sec><title>Results</title><p>Useful full text.</p>
<table-wrap id="t1"><label>Table 1</label><caption><p>Outcome</p></caption>
<table><tbody><tr><td>Arm</td><td>10</td></tr></tbody></table></table-wrap>
</sec></body></article>"""

NO_TABLE_XML = """<article><front><article-meta/></front><body>
<sec><title>Methods</title><p>Randomised study methods.</p></sec></body></article>"""

ABSTRACT_ONLY_XML = """<article><front><article-meta>
<abstract><p>Only an abstract.</p></abstract></article-meta></front></article>"""


def _review(case_id: int) -> dict:
    studies = pd.DataFrame([
        {
            "ref": f"Study {case_id} A", "title": "Full table article", "abstract": "A",
            "methods": "RCT", "participants": "Adults", "interventions_and_control": "Drug vs placebo",
            "outcomes": "Mortality", "risk_of_bias": {"random": "low"},
        },
        {"ref": f"Study {case_id} B", "title": "Full no-table article", "abstract": "B"},
        {"ref": f"Study {case_id} C", "title": "Abstract article", "abstract": "C"},
    ])
    comparisons = pd.DataFrame([{"Comparator PICO text": "RR 0.8 [0.6, 1.0]", "SVG Data": "<svg/>"}])
    return {
        "case_id": case_id, "title": f"Review {case_id}", "P": "Adults", "I": "Drug",
        "C": "Placebo", "O": "Mortality", "Included Reviews DF": studies,
        "Comparator DF": comparisons, "abs_conclusion": f"Gold {case_id}",
        "full_conclusions": f"Full gold {case_id}",
    }


def test_builds_only_selected_cases_and_routes_three_evidence_tiers(tmp_path: Path) -> None:
    source = tmp_path / "Dataset.pickle"
    pd.DataFrame([_review(1), _review(7), _review(12), _review(44)]).to_pickle(source)
    xml_dir = tmp_path / "xml"
    xml_dir.mkdir()
    (xml_dir / "PMC1201.xml").write_text(ARTICLE_XML, encoding="utf-8")
    (xml_dir / "PMC1202.xml").write_text(NO_TABLE_XML, encoding="utf-8")
    manifest_rows = []
    for case_id in (1, 7, 12):
        manifest_rows.extend([
            {"case_id": case_id, "study_index": 1, "study_ref": f"Study {case_id} A", "pmid": str(case_id * 100 + 1), "pmcid": "PMC1201"},
            {"case_id": case_id, "study_index": 2, "study_ref": f"Study {case_id} B", "pmid": str(case_id * 100 + 2), "pmcid": "PMC1202"},
            {"case_id": case_id, "study_index": 3, "study_ref": f"Study {case_id} C", "pmid": str(case_id * 100 + 3)},
        ])
    sources = tmp_path / "sources.json"
    sources.write_text(json.dumps(manifest_rows), encoding="utf-8")
    output = tmp_path / "pilot"

    result = build_pilot_dataset(dataset_path=source, output_dir=output,
                                 article_source_manifest=sources, xml_dir=xml_dir)

    assert result["case_ids"] == [1, 7, 12]
    assert not (output / "cases" / "44.json").exists()
    case = load_case(output, 12)
    assert [article.evidence_tier for article in case.articles] == [
        "full_text_with_tables", "full_text_without_tables", "abstract_only"
    ]
    assert case.included_corpus_ids == [1, 2, 3]
    assert case.articles[0].benchmark_study["participants"] == "Adults"
    assert case.oracle_evidence["comparisons"][0]["Comparator PICO text"].startswith("RR")


def test_gold_is_physically_separated_and_opt_in(tmp_path: Path) -> None:
    source = tmp_path / "Dataset.pickle"
    pd.DataFrame([_review(case_id) for case_id in (1, 7, 12)]).to_pickle(source)
    output = tmp_path / "pilot"
    build_pilot_dataset(dataset_path=source, output_dir=output)

    generation_payload = read_json(output / "cases" / "12.json")
    assert "gold" not in generation_payload
    assert "Gold 12" not in json.dumps(generation_payload)
    assert load_case(output, 12).gold == {}
    assert load_gold(output, 12)["abstract_conclusion"] == "Gold 12"
    assert load_case(output, 12, include_gold=True).gold["full_conclusions"] == "Full gold 12"


def test_injected_fetcher_is_optional_and_local_build_does_not_require_network(tmp_path: Path) -> None:
    source = tmp_path / "Dataset.pickle"
    pd.DataFrame([_review(case_id) for case_id in (1, 7, 12)]).to_pickle(source)
    sources = tmp_path / "sources.json"
    sources.write_text(json.dumps([
        {"case_id": case_id, "study_index": 1, "study_ref": f"Study {case_id} A", "pmcid": "PMC999"}
        for case_id in (1, 7, 12)
    ]), encoding="utf-8")
    calls: list[str] = []

    build_pilot_dataset(
        dataset_path=source, output_dir=tmp_path / "pilot", article_source_manifest=sources,
        xml_fetcher=lambda pmcid: calls.append(pmcid) or ARTICLE_XML,
    )

    assert calls == ["PMC999", "PMC999", "PMC999"]
    assert load_case(tmp_path / "pilot", 7).articles[0].evidence_tier == "full_text_with_tables"


def test_missing_selected_case_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "Dataset.pickle"
    pd.DataFrame([_review(1), _review(7)]).to_pickle(source)
    with pytest.raises(ValueError, match="12"):
        build_pilot_dataset(dataset_path=source, output_dir=tmp_path / "pilot")


def test_parseable_pmc_abstract_without_body_stays_abstract_only(tmp_path: Path) -> None:
    source = tmp_path / "Dataset.pickle"
    pd.DataFrame([_review(case_id) for case_id in (1, 7, 12)]).to_pickle(source)
    sources = tmp_path / "sources.json"
    sources.write_text(json.dumps([
        {"case_id": case_id, "study_index": 1, "pmcid": "PMC999"}
        for case_id in (1, 7, 12)
    ]), encoding="utf-8")

    build_pilot_dataset(
        dataset_path=source,
        output_dir=tmp_path / "pilot",
        article_source_manifest=sources,
        xml_fetcher=lambda _pmcid: ABSTRACT_ONLY_XML,
    )

    article = load_case(tmp_path / "pilot", 12).articles[0]
    assert article.cleaned_article is None
    assert article.evidence_tier == "abstract_only"
