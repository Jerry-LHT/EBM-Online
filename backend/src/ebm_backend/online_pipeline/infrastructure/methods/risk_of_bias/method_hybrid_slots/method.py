"""Hybrid risk-of-bias method for prompt-evolution experiments."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.risk_of_bias import ROB1_DOMAINS, RiskOfBiasAssessment, RoB1DomainJudgement
from ebm_backend.online_pipeline.infrastructure.llm import LLMConfig, call_llm_json, load_llm_config
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_calibrated_slots.method import (
    SPECS_BY_ID,
    build_system_prompt as build_calibrated_system_prompt,
)
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_onestep_llm.method import (
    DOMAIN_LABELS,
    _article_evidence,
    _system_prompt as build_current_system_prompt,
)


CALIBRATED_DOMAINS = {
    "blinding_participants_personnel",
    "blinding_outcome_assessment",
    "other_bias",
}
LLM_DOMAINS = list(ROB1_DOMAINS)


class Method:
    def __init__(self) -> None:
        self.llm_config_path: Path | None = None
        self.workers = 1

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

    def run(self, *, included_studies: list[str], articles: list[CleanedArticle]) -> list[RiskOfBiasAssessment]:
        config = load_llm_config(self.llm_config_path or Path("llm.local.json"))
        if config is None:
            raise RuntimeError("Missing LLM config for risk_of_bias.method_hybrid_slots")

        articles_by_study = {article.study_id: article for article in articles}
        results: list[RiskOfBiasAssessment] = []
        for study_id in included_studies:
            article = articles_by_study.get(study_id)
            if article is None and len(articles) == 1:
                article = articles[0]
            if article is None:
                continue
            judgements = self._run_domains(config=config, evidence=_article_evidence(article))
            results.append(
                RiskOfBiasAssessment(
                    study_id=study_id,
                    domains=judgements,
                    overall="unclear",
                    notes="Hybrid seven-domain RoB method using calibrated prompts for selected high-recall domains.",
                )
            )
        return results

    def _run_domains(self, *, config: LLMConfig, evidence: str) -> list[RoB1DomainJudgement]:
        if self.workers > 1:
            with ThreadPoolExecutor(max_workers=min(self.workers, len(LLM_DOMAINS))) as executor:
                return list(executor.map(lambda domain_id: _run_llm_domain(config=config, domain_id=domain_id, evidence=evidence), LLM_DOMAINS))
        return [_run_llm_domain(config=config, domain_id=domain_id, evidence=evidence) for domain_id in LLM_DOMAINS]


def build_method() -> Method:
    return Method()


def _run_llm_domain(*, config: LLMConfig, domain_id: str, evidence: str) -> RoB1DomainJudgement:
    system_prompt = _system_prompt(domain_id)
    user_prompt = f"{evidence}\n\nAssess {DOMAIN_LABELS[domain_id]}. Output JSON only."
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            parsed = call_llm_json(config=config, system=system_prompt, prompt=user_prompt)
            return RoB1DomainJudgement(
                domain=domain_id,
                judgement=_normalize_judgement(parsed.get("judgement")),
                rationale=str(parsed.get("support_text") or parsed.get("rationale") or ""),
            )
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt == 0:
                user_prompt = (
                    f"{evidence}\n\nAssess {DOMAIN_LABELS[domain_id]} again. "
                    "Your previous response could not be parsed. Return exactly one strict JSON object "
                    'with double-quoted keys and string values for "domain", "judgement", and "support_text".'
                )
            else:
                break
        except Exception as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            break
    return RoB1DomainJudgement(
        domain=domain_id,
        judgement="unclear_risk",
        rationale=f"LLM call failed or returned invalid JSON for {DOMAIN_LABELS[domain_id]}: {last_error}",
    )


def _system_prompt(domain_id: str) -> str:
    if domain_id in CALIBRATED_DOMAINS:
        return build_calibrated_system_prompt(SPECS_BY_ID[domain_id])
    return build_current_system_prompt(domain_id)


def _normalize_judgement(value: Any) -> str:
    text = str(value or "").lower().strip()
    if "low" in text:
        return "low_risk"
    if "high" in text:
        return "high_risk"
    return "unclear_risk"
