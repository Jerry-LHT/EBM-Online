"""Article-only Risk of Bias method."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import logging
from pathlib import Path

from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.risk_of_bias import (
    ROB1_DOMAINS,
    RiskOfBiasAssessment,
    RiskOfBiasDomainConfig,
    RoB1DomainJudgement,
    summarize_rob1_overall,
)
from ebm_backend.online_pipeline.infrastructure.llm import (
    LLMConfig,
    call_llm_json,
    load_llm_config,
)
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.errors import (
    RiskOfBiasConfigurationError,
)
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_onestep_llm.article_evidence import (
    build_article_evidence,
)
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_onestep_llm.domain_assessor import (
    LLMJSONCaller,
    assess_domain,
)
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_onestep_llm.cache import (
    RoBDomainJudgementCache,
    build_domain_cache_key,
)


LOGGER = logging.getLogger(__name__)


class Method:
    def __init__(
        self,
        *,
        caller: LLMJSONCaller = call_llm_json,
        domain_workers: int = 7,
        domain_cache: RoBDomainJudgementCache | None = None,
    ) -> None:
        if domain_workers <= 0:
            raise ValueError("domain_workers must be positive")
        self.caller = caller
        self.llm_config_path: Path | None = None
        self.workers = domain_workers
        self.domain_cache = domain_cache

    def configure_for_benchmark(
        self,
        *,
        llm_config: str | Path = "llm.local.json",
        workers: int = 1,
        run_dir: str | Path | None = None,
        resume: bool = False,
    ) -> None:
        self.llm_config_path = Path(llm_config)
        self.workers = max(1, int(workers or 1))

    def assess(
        self,
        *,
        study_id: str,
        article: CleanedArticle,
        domain_config: RiskOfBiasDomainConfig | None = None,
    ) -> RiskOfBiasAssessment:
        resolved_config = domain_config or RiskOfBiasDomainConfig()
        try:
            config = load_llm_config(self.llm_config_path or Path("llm.local.json"))
            if config is None:
                raise RuntimeError("Missing LLM config")
        except (FileNotFoundError, OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
            raise RiskOfBiasConfigurationError(
                "Risk of Bias LLM configuration is unavailable"
            ) from exc
        evidence = build_article_evidence(article)
        assessed_domains = [
            domain
            for domain in ROB1_DOMAINS
            if domain in set(resolved_config.assessed_domains)
        ]
        key_domains = [
            domain
            for domain in ROB1_DOMAINS
            if domain in set(resolved_config.overall_key_domains)
        ]
        judgements = self._run_domains(
            config=config,
            evidence=evidence,
            study_id=study_id,
            domains=assessed_domains,
        )
        return RiskOfBiasAssessment(
            study_id=study_id,
            domains=judgements,
            overall=summarize_rob1_overall(
                judgements=judgements,
                key_domains=key_domains,
            ),
            assessed_domains=assessed_domains,
            overall_key_domains=key_domains,
            unassessed_domains=[
                domain for domain in ROB1_DOMAINS if domain not in assessed_domains
            ],
            notes=(
                "Article-only LLM domain assessment using existing Cochrane RoB 1 "
                "criteria; overall summarized deterministically across configured key domains."
            ),
        )

    def _run_domains(
        self,
        *,
        config: LLMConfig,
        evidence: str,
        study_id: str,
        domains: list[str],
    ) -> list[RoB1DomainJudgement]:
        def assess_one(domain_id: str) -> RoB1DomainJudgement:
            cache_key = None
            if self.domain_cache is not None:
                cache_key = build_domain_cache_key(
                    config=config,
                    domain=domain_id,
                    evidence=evidence,
                )
                try:
                    cached = self.domain_cache.get(
                        key=cache_key,
                        domain=domain_id,
                    )
                except (OSError, UnicodeDecodeError, TypeError, ValueError, KeyError):
                    LOGGER.warning(
                        "Ignoring unreadable RoB domain cache entry for %s",
                        domain_id,
                        exc_info=True,
                    )
                else:
                    if cached is not None:
                        return cached
            judgement = assess_domain(
                config=config,
                domain_id=domain_id,
                evidence=evidence,
                study_id=study_id,
                caller=self.caller,
            )
            if self.domain_cache is not None and cache_key is not None:
                try:
                    self.domain_cache.put(
                        key=cache_key,
                        domain=domain_id,
                        judgement=judgement,
                    )
                except (OSError, UnicodeEncodeError, TypeError, ValueError):
                    LOGGER.warning(
                        "Unable to persist RoB domain cache entry for %s",
                        domain_id,
                        exc_info=True,
                    )
            return judgement

        if self.workers > 1:
            with ThreadPoolExecutor(max_workers=min(self.workers, len(domains))) as executor:
                return list(executor.map(assess_one, domains))
        return [assess_one(domain_id) for domain_id in domains]


def build_method(
    *,
    caller: LLMJSONCaller = call_llm_json,
    domain_workers: int = 7,
    domain_cache: RoBDomainJudgementCache | None = None,
) -> Method:
    return Method(
        caller=caller,
        domain_workers=domain_workers,
        domain_cache=domain_cache,
    )
