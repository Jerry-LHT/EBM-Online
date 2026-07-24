"""Use case for assessing study-level risk of bias."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from ebm_backend.online_pipeline.application.ports import RiskOfBiasPort
from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.risk_of_bias import (
    MAX_RISK_OF_BIAS_ITEMS_PER_RUN,
    RiskOfBiasAssessment,
    RiskOfBiasDomainConfig,
)


class RiskOfBiasArticleContentMissingError(ValueError):
    """One or more included studies have no usable article sections."""

    def __init__(self, *, study_ids: list[str]) -> None:
        super().__init__(
            "Missing usable full text for study_id(s): " + ", ".join(study_ids)
        )
        self.study_ids = study_ids


@dataclass(frozen=True)
class RunRiskOfBias:
    risk_of_bias_assessor: RiskOfBiasPort
    max_workers: int = 4

    def execute(
        self,
        *,
        included_studies: list[str],
        articles: list[CleanedArticle],
        domain_config: RiskOfBiasDomainConfig | None = None,
    ) -> list[RiskOfBiasAssessment]:
        resolved_domain_config = domain_config or RiskOfBiasDomainConfig()
        if self.max_workers <= 0:
            raise ValueError("max_workers must be positive")
        if len(included_studies) > MAX_RISK_OF_BIAS_ITEMS_PER_RUN:
            raise ValueError(
                "Risk of Bias accepts at most "
                f"{MAX_RISK_OF_BIAS_ITEMS_PER_RUN} included studies"
            )
        if len(articles) > MAX_RISK_OF_BIAS_ITEMS_PER_RUN:
            raise ValueError(
                f"Risk of Bias accepts at most {MAX_RISK_OF_BIAS_ITEMS_PER_RUN} articles"
            )
        if any(not str(study_id).strip() for study_id in included_studies):
            raise ValueError("included_studies must not contain empty study IDs")
        if len(set(included_studies)) != len(included_studies):
            raise ValueError("included_studies must not contain duplicate study IDs")
        articles_by_study: dict[str, CleanedArticle] = {}
        for article in articles:
            if article.study_id in articles_by_study:
                raise ValueError(
                    f"Multiple articles were provided for study_id '{article.study_id}'"
                )
            articles_by_study[article.study_id] = article

        missing = [study_id for study_id in included_studies if study_id not in articles_by_study]
        if missing:
            raise ValueError(
                f"Missing CleanedArticle for included study_id(s): {', '.join(missing)}"
            )
        included_set = set(included_studies)
        unexpected = [
            study_id for study_id in articles_by_study if study_id not in included_set
        ]
        if unexpected:
            raise ValueError(
                "CleanedArticle was provided for non-included study_id(s): "
                + ", ".join(unexpected)
            )
        if not included_studies:
            return []

        missing_full_text = [
            study_id
            for study_id in included_studies
            if not _has_usable_full_text(articles_by_study[study_id])
        ]
        if missing_full_text:
            raise RiskOfBiasArticleContentMissingError(study_ids=missing_full_text)

        workers = min(self.max_workers, len(included_studies))
        if workers == 1:
            return [
                self.risk_of_bias_assessor.assess(
                    study_id=study_id,
                    article=articles_by_study[study_id],
                    domain_config=resolved_domain_config,
                )
                for study_id in included_studies
            ]

        indexed_results: list[tuple[int, RiskOfBiasAssessment]] = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_index = {
                executor.submit(
                    self.risk_of_bias_assessor.assess,
                    study_id=study_id,
                    article=articles_by_study[study_id],
                    domain_config=resolved_domain_config,
                ): index
                for index, study_id in enumerate(included_studies)
            }
            for future in as_completed(future_to_index):
                indexed_results.append((future_to_index[future], future.result()))

        indexed_results.sort(key=lambda item: item[0])
        return [result for _, result in indexed_results]


def _has_usable_full_text(article: CleanedArticle) -> bool:
    return any(section.text.strip() for section in article.xml_content.sections)
