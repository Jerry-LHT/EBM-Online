from benchmark.ebm_application.beyond_abstracts.models import BeyondArticle, BeyondCase


def test_protocol_payload_omits_gold_and_contract_is_metasyn_compatible() -> None:
    article = BeyondArticle(1, "123", "Title", "Abstract", None)
    case = BeyondCase(12, "Review", "Question", {"P": [], "I": [], "C": [], "O": []}, [], [],
                      articles=[article], oracle_evidence={"hidden": "oracle"},
                      gold={"abstract_conclusion": "secret"})

    assert article.evidence_tier == "abstract_only"
    assert case.included_corpus_ids == [1]
    assert "gold" not in case.protocol_payload()
    assert "oracle_evidence" not in case.protocol_payload()
