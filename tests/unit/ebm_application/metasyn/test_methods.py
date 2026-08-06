from benchmark.ebm_application.metasyn.methods import protocol_payload, report_markdown
from benchmark.ebm_application.metasyn.models import PilotArticle, PilotCase
from benchmark.ebm_application.metasyn.agent import agent_core_fingerprint
from ebm_backend.online_pipeline.infrastructure.llm import LLMConfig


def _case() -> PilotCase:
    return PilotCase(
        case_id=223,
        title="Review title",
        question="Does treatment help?",
        pico={"P": ["adults"], "I": ["treatment"], "C": ["control"], "O": ["outcome"], "O_expanded": []},
        inclusion_criteria=["RCTs"],
        exclusion_criteria=["Animal studies"],
        articles=[PilotArticle(1, "10", "Trial", "Abstract", None)],
        gold={"Effect_Size_Value": 99.9, "conclusion_paragraph": "secret gold"},
    )


def test_protocol_payload_cannot_expose_gold() -> None:
    payload = protocol_payload(_case())
    serialized = str(payload)
    assert "gold" not in payload
    assert "99.9" not in serialized
    assert "secret gold" not in serialized
    assert payload["fixed_included_corpus_ids"] == [1]


def test_agent_core_fingerprint_does_not_depend_on_gold() -> None:
    case = _case()
    other_gold = PilotCase(
        case_id=case.case_id,
        title=case.title,
        question=case.question,
        pico=case.pico,
        inclusion_criteria=case.inclusion_criteria,
        exclusion_criteria=case.exclusion_criteria,
        articles=case.articles,
        gold={"Effect_Size_Value": -123, "conclusion_paragraph": "different"},
    )
    config = LLMConfig(api_key="test", base_url="https://example.invalid/v1", model="gpt-5.6-terra")
    assert agent_core_fingerprint(case=case, config=config) == agent_core_fingerprint(
        case=other_gold,
        config=config,
    )


def test_report_markdown_has_official_evaluator_sections() -> None:
    markdown = report_markdown(
        {
            "title": "T",
            "methods": "M",
            "results": "R",
            "key_findings": ["K"],
            "limitations": ["L"],
            "conclusion": "C",
            "conclusion_direction": "Mixed",
        }
    )
    assert "## Methods" in markdown
    assert "## Results" in markdown
    assert "## Conclusion" in markdown
