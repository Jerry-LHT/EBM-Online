from benchmark.ebm_application.metasyn.evidence import EvidenceSource
from benchmark.ebm_application.metasyn.rag import bm25_study_balanced


def _source(source_id: str, study_id: str, text: str) -> EvidenceSource:
    return EvidenceSource(
        source_id=source_id,
        corpus_id=int(study_id),
        study_id=study_id,
        source_type="section",
        title=source_id,
        text=text,
    )


def test_bm25_guarantees_each_study_and_caps_repetition() -> None:
    sources = [
        _source("a1", "1", "blood pressure effect estimate"),
        _source("a2", "1", "blood pressure result"),
        _source("a3", "1", "blood pressure confidence interval"),
        _source("a4", "1", "blood pressure outcome"),
        _source("b1", "2", "trial methods unrelated wording"),
    ]

    ranked = bm25_study_balanced(
        sources=sources,
        queries=["blood pressure effect"],
        global_extras=10,
        max_per_study=3,
    )

    study_ids = [item.source.study_id for item in ranked]
    assert set(study_ids) == {"1", "2"}
    assert study_ids.count("1") == 3
    assert study_ids.count("2") == 1

