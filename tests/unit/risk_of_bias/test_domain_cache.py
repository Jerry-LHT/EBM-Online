from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

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
from ebm_backend.online_pipeline.infrastructure.llm import LLMConfig
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.errors import (
    RiskOfBiasDomainInvocationError,
)
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_onestep_llm import (
    method as method_module,
)
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_onestep_llm.cache import (
    FileRoBDomainJudgementCache,
    build_domain_cache_key,
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
                    text="Participants were randomized and followed through study end.",
                )
            ]
        ),
    )


def _config(*, model: str = "model-a") -> LLMConfig:
    return LLMConfig(
        api_key="not-persisted",
        base_url="https://provider.example/v1",
        model=model,
        api_mode="chat",
    )


def _success_response(kwargs):
    return {
        "domain": kwargs["json_schema"]["properties"]["domain"]["enum"][0],
        "judgement": "Low risk",
        "support_text": "Article evidence supported the judgement.",
    }


def test_five_domain_cache_is_reused_when_later_requesting_seven_domains(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: Counter[str] = Counter()

    def caller(**kwargs):
        domain = kwargs["json_schema_name"].removeprefix("risk_of_bias_")
        calls[domain] += 1
        return _success_response(kwargs)

    monkeypatch.setattr(method_module, "load_llm_config", lambda path: _config())
    cache = FileRoBDomainJudgementCache(tmp_path / "rob-cache")
    first_five = DEFAULT_ROB1_DOMAINS[:5]
    method_module.build_method(
        caller=caller,
        domain_workers=5,
        domain_cache=cache,
    ).assess(
        study_id="study-1",
        article=_article(),
        domain_config=RiskOfBiasDomainConfig(
            assessed_domains=first_five,
            overall_key_domains=first_five,
        ),
    )

    result = method_module.build_method(
        caller=caller,
        domain_workers=7,
        domain_cache=cache,
    ).assess(study_id="study-1", article=_article())

    assert len(result.domains) == 7
    assert all(calls[domain] == 1 for domain in DEFAULT_ROB1_DOMAINS)
    assert result.overall.judgement == "low_risk"


def test_failed_domain_is_not_cached(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(method_module, "load_llm_config", lambda path: _config())
    cache = FileRoBDomainJudgementCache(tmp_path / "rob-cache")
    config = RiskOfBiasDomainConfig(
        assessed_domains=["random_sequence_generation"],
        overall_key_domains=["random_sequence_generation"],
    )
    failed_calls = 0

    def failing_caller(**kwargs):
        nonlocal failed_calls
        failed_calls += 1
        raise TimeoutError("provider timeout")

    with pytest.raises(RiskOfBiasDomainInvocationError):
        method_module.build_method(
            caller=failing_caller,
            domain_workers=1,
            domain_cache=cache,
        ).assess(
            study_id="study-1",
            article=_article(),
            domain_config=config,
        )
    assert failed_calls == 2

    successful_calls = 0

    def successful_caller(**kwargs):
        nonlocal successful_calls
        successful_calls += 1
        return _success_response(kwargs)

    result = method_module.build_method(
        caller=successful_caller,
        domain_workers=1,
        domain_cache=cache,
    ).assess(
        study_id="study-1",
        article=_article(),
        domain_config=config,
    )

    assert successful_calls == 1
    assert result.domains[0].domain == "random_sequence_generation"


def test_cache_key_changes_with_model_evidence_and_domain() -> None:
    base = build_domain_cache_key(
        config=_config(model="model-a"),
        domain="random_sequence_generation",
        evidence="article evidence",
    )
    changed_model = build_domain_cache_key(
        config=_config(model="model-b"),
        domain="random_sequence_generation",
        evidence="article evidence",
    )
    changed_evidence = build_domain_cache_key(
        config=_config(model="model-a"),
        domain="random_sequence_generation",
        evidence="updated evidence",
    )
    changed_domain = build_domain_cache_key(
        config=_config(model="model-a"),
        domain="allocation_concealment",
        evidence="article evidence",
    )

    assert len({base, changed_model, changed_evidence, changed_domain}) == 4
