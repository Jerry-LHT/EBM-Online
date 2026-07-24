"""Hybrid risk-of-bias method for prompt-evolution experiments."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.risk_of_bias import (
    ROB1_DOMAINS,
    RiskOfBiasAssessment,
    RoB1DomainJudgement,
    summarize_rob1_overall,
)
from ebm_backend.online_pipeline.infrastructure.llm import LLMConfig, load_llm_config
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_hybrid_slots.article_evidence import build_article_evidence
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_hybrid_slots.domain_assessor import assess_domain
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_hybrid_slots.domain_specs import LLM_DOMAINS


class Method:
    def __init__(self) -> None:
        self.llm_config_path: Path | None = None
        self.workers = 1

    def configure_for_benchmark(self, *, llm_config: str | Path = "llm.local.json", workers: int = 1, run_dir: str | Path | None = None, resume: bool = False) -> None:
        self.llm_config_path = Path(llm_config)
        self.workers = max(1, int(workers or 1))

    def assess(self, *, study_id: str, article: CleanedArticle) -> RiskOfBiasAssessment:
        config = load_llm_config(self.llm_config_path or Path("llm.local.json"))
        if config is None:
            raise RuntimeError("Missing LLM config for risk_of_bias.method_hybrid_slots")
        judgements = self._run_domains(config=config, evidence=build_article_evidence(article))
        return RiskOfBiasAssessment(
            study_id=study_id,
            domains=judgements,
            overall=summarize_rob1_overall(
                judgements=judgements,
                key_domains=list(ROB1_DOMAINS),
            ),
            assessed_domains=list(ROB1_DOMAINS),
            overall_key_domains=list(ROB1_DOMAINS),
            notes="Hybrid seven-domain RoB method using calibrated prompts for selected high-recall domains.",
        )

    def _run_domains(self, *, config: LLMConfig, evidence: str) -> list[RoB1DomainJudgement]:
        if self.workers > 1:
            with ThreadPoolExecutor(max_workers=min(self.workers, len(LLM_DOMAINS))) as executor:
                return list(executor.map(lambda domain_id: assess_domain(config=config, domain_id=domain_id, evidence=evidence), LLM_DOMAINS))
        return [assess_domain(config=config, domain_id=domain_id, evidence=evidence) for domain_id in LLM_DOMAINS]


def build_method() -> Method:
    return Method()
