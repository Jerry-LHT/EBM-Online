from __future__ import annotations

from ebm_backend.online_pipeline.domain.article import (
    ArticleMetadata,
    ArticleSection,
    ArticleXmlContent,
    CleanedArticle,
)
from ebm_backend.online_pipeline.domain.risk_of_bias import (
    DEFAULT_ROB1_DOMAINS,
    RiskOfBiasDomainConfig,
)
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_onestep_llm import (
    method as method_module,
)


def _article() -> CleanedArticle:
    return CleanedArticle(
        study_id="study-1",
        metadata=ArticleMetadata(title="RCT"),
        xml_content=ArticleXmlContent(
            sections=[
                ArticleSection(
                    section_id="methods",
                    title="Methods",
                    text="Participants were randomly allocated.",
                )
            ]
        ),
    )


def test_method_defaults_to_seven_domains_and_deterministic_overall(monkeypatch) -> None:
    schema_names: list[str] = []

    def caller(**kwargs):
        schema_names.append(kwargs["json_schema_name"])
        domain_label = kwargs["json_schema"]["properties"]["domain"]["enum"][0]
        return {
            "domain": domain_label,
            "judgement": "Low risk",
            "support_text": "The supplied article supported a low-risk judgement.",
        }

    monkeypatch.setattr(method_module, "load_llm_config", lambda path: object())
    method = method_module.build_method(caller=caller, domain_workers=7)

    result = method.assess(study_id="study-1", article=_article())

    assert [item.domain for item in result.domains] == DEFAULT_ROB1_DOMAINS
    assert result.assessed_domains == DEFAULT_ROB1_DOMAINS
    assert result.overall_key_domains == DEFAULT_ROB1_DOMAINS
    assert result.unassessed_domains == []
    assert result.overall.judgement == "low_risk"
    assert set(schema_names) == {
        f"risk_of_bias_{domain}" for domain in DEFAULT_ROB1_DOMAINS
    }


def test_method_runs_only_configured_domains_and_preserves_canonical_order(monkeypatch) -> None:
    called: list[str] = []

    def caller(**kwargs):
        schema_name = kwargs["json_schema_name"]
        called.append(schema_name.removeprefix("risk_of_bias_"))
        label = kwargs["json_schema"]["properties"]["domain"]["enum"][0]
        judgement = "High risk" if "allocation concealment" in label.lower() else "Low risk"
        return {
            "domain": label,
            "judgement": judgement,
            "support_text": "Article evidence.",
        }

    monkeypatch.setattr(method_module, "load_llm_config", lambda path: object())
    method = method_module.build_method(caller=caller, domain_workers=3)
    config = RiskOfBiasDomainConfig(
        assessed_domains=[
            "selective_reporting",
            "allocation_concealment",
            "random_sequence_generation",
        ],
        overall_key_domains=[
            "allocation_concealment",
            "random_sequence_generation",
        ],
    )

    result = method.assess(
        study_id="study-1",
        article=_article(),
        domain_config=config,
    )

    assert [item.domain for item in result.domains] == [
        "random_sequence_generation",
        "allocation_concealment",
        "selective_reporting",
    ]
    assert set(called) == set(config.assessed_domains)
    assert result.overall.judgement == "high_risk"
    assert result.overall.driving_domains == [
        "allocation_concealment"
    ]
