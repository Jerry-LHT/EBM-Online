"""Application orchestration for article-level study screening."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from dataclasses import replace

from ebm_backend.online_pipeline.application.ports import (
    CoarseStudyArticleScreenerPort,
    ScreeningCriteriaPlannerPort,
    SynthesisReadyStudyArticleScreenerPort,
    StudyArticleScreenerPort,
)
from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.common import WorkflowConstraints
from ebm_backend.online_pipeline.domain.meta_analysis import MetaAnalysisSynthesisPlan
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.screening import (
    ArticleSynthesisScreeningResult,
    ArticleScreeningResult,
    CoarseScreeningDecision,
    ScreeningCriteria,
    ScreeningCriterionJudgment,
    ScreeningCriterionJudgmentValue,
    ScreeningCriterionType,
    ScreeningDecision,
    ScreeningPolicy,
    ScreeningReportScope,
    SynthesisReadinessStatus,
    SynthesisTargetReadiness,
    StudyScreeningResult,
    screening_decision_from_article_result,
)


MAX_ARTICLES_PER_RUN = 500
RCT_INCLUSION_CRITERION = "The study uses randomized allocation to intervention groups."
PARALLEL_INDIVIDUAL_RCT_INCLUSION_CRITERION = (
    "The trial uses an individually randomized parallel-group design; "
    "cluster-randomized, crossover, cluster-crossover, and other non-parallel "
    "allocation designs are ineligible."
)
PRIMARY_REPORT_INCLUSION_CRITERION = (
    "The article is an original primary results report of the eligible trial, not a "
    "protocol, review, editorial, commentary, correction, or retraction notice."
)


@dataclass(frozen=True)
class RunStudyScreening:
    criteria_planner: ScreeningCriteriaPlannerPort
    article_screener: StudyArticleScreenerPort | None = None
    coarse_screener: CoarseStudyArticleScreenerPort | None = None
    synthesis_ready_screener: SynthesisReadyStudyArticleScreenerPort | None = None
    max_workers: int = 4

    def prepare_criteria(
        self,
        *,
        question_text: str,
        question_pico: QuestionPICO,
        constraints: WorkflowConstraints,
        policy: ScreeningPolicy | None = None,
    ) -> ScreeningCriteria:
        if not question_text.strip():
            raise ValueError("question_text is required")
        resolved_policy = policy or _policy_from_constraints(constraints)
        criteria = self.criteria_planner.run(
            question_text=question_text,
            question_pico=question_pico,
            constraints=constraints,
            policy=resolved_policy,
        )
        return _append_system_criteria(criteria=criteria, policy=resolved_policy)

    def execute(
        self,
        *,
        question_text: str,
        question_pico: QuestionPICO,
        constraints: WorkflowConstraints,
        articles: list[CleanedArticle],
        policy: ScreeningPolicy | None = None,
        criteria: ScreeningCriteria | None = None,
        synthesis_plan: MetaAnalysisSynthesisPlan | None = None,
    ) -> StudyScreeningResult:
        if not question_text.strip():
            raise ValueError("question_text is required")
        if self.max_workers <= 0:
            raise ValueError("max_workers must be positive")
        if len(articles) > MAX_ARTICLES_PER_RUN:
            raise ValueError(
                f"study_screening accepts at most {MAX_ARTICLES_PER_RUN} articles per run"
            )
        article_ids = [article.study_id for article in articles]
        if len(set(article_ids)) != len(article_ids):
            raise ValueError("study_screening articles must have unique study_id values")

        resolved_policy = policy or _policy_from_constraints(constraints)

        resolved_criteria = criteria or self.prepare_criteria(
            question_text=question_text,
            question_pico=question_pico,
            constraints=constraints,
            policy=resolved_policy,
        )
        staged = self.coarse_screener is not None or self.synthesis_ready_screener is not None
        if staged:
            if self.coarse_screener is None or self.synthesis_ready_screener is None:
                raise ValueError(
                    "staged screening requires both coarse and synthesis-ready screeners"
                )
            if synthesis_plan is None:
                raise ValueError("staged screening requires a frozen synthesis_plan")
            coarse, decisions, readiness = self._screen_articles_staged(
                criteria=resolved_criteria,
                synthesis_plan=synthesis_plan,
                articles=articles,
                policy=resolved_policy,
            )
        else:
            if self.article_screener is None:
                raise ValueError("study screening requires an article screener")
            decisions = self._screen_articles_single(
                criteria=resolved_criteria,
                articles=articles,
                policy=resolved_policy,
            )
            coarse = []
            readiness = {}
        included = [
            decision.study_id for decision in decisions if decision.decision == "include"
        ]
        excluded = [
            decision.study_id for decision in decisions if decision.decision == "exclude"
        ]
        unsupported = [
            decision.study_id
            for decision in decisions
            if decision.methodologically_eligible_unsupported_target_ids
            and not decision.meta_entry_target_ids
        ]
        meta_ready = [
            decision.study_id
            for decision in decisions
            if decision.decision == "include"
            and decision.meta_routing_status == "meta_ready"
        ]
        meta_investigation = [
            decision.study_id
            for decision in decisions
            if decision.decision == "include"
            and decision.meta_routing_status == "needs_meta_investigation"
        ]
        no_readable_table = [
            decision.study_id
            for decision in decisions
            if decision.decision == "include"
            and decision.meta_routing_status
            == "meta_unavailable_no_readable_table"
        ]
        return StudyScreeningResult(
            screening_criteria=resolved_criteria,
            decisions=decisions,
            included_studies=included,
            included_articles=included,
            excluded_articles=excluded,
            coarse_decisions=coarse,
            synthesis_readiness=readiness,
            methodologically_eligible_unsupported_studies=unsupported,
            meta_ready_studies=meta_ready,
            meta_investigation_studies=meta_investigation,
            meta_unavailable_no_readable_table_studies=no_readable_table,
        )

    def _screen_articles_single(
        self,
        *,
        criteria: ScreeningCriteria,
        articles: list[CleanedArticle],
        policy: ScreeningPolicy,
    ) -> list[ScreeningDecision]:
        if not articles:
            return []

        indexed_articles = list(enumerate(articles))
        workers = min(self.max_workers, len(indexed_articles))
        results: list[tuple[int, ScreeningDecision]] = []
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_index = {
                executor.submit(
                    self._screen_one_article,
                    criteria=criteria,
                    article=article,
                    policy=policy,
                ): index
                for index, article in indexed_articles
            }
            for future in as_completed(future_to_index):
                results.append((future_to_index[future], future.result()))
        results.sort(key=lambda item: item[0])
        return [decision for _, decision in results]

    def _screen_articles_staged(
        self,
        *,
        criteria: ScreeningCriteria,
        synthesis_plan: MetaAnalysisSynthesisPlan,
        articles: list[CleanedArticle],
        policy: ScreeningPolicy,
    ) -> tuple[
        list[CoarseScreeningDecision],
        list[ScreeningDecision],
        dict[str, list[SynthesisTargetReadiness]],
    ]:
        if not articles:
            return [], [], {}

        indexed_articles = list(enumerate(articles))
        coarse_by_index: dict[int, CoarseScreeningDecision] = {}
        deterministic_by_index: dict[int, ScreeningDecision] = {}
        coarse_candidates: list[tuple[int, CleanedArticle]] = []
        for index, article in indexed_articles:
            deterministic = _deterministic_judgments(article=article, policy=policy)
            deterministic_decision = screening_decision_from_article_result(
                study_id=article.study_id,
                result=ArticleScreeningResult(criterion_judgments=deterministic),
            )
            deterministic_by_index[index] = deterministic_decision
            if deterministic_decision.decision == "exclude":
                coarse_by_index[index] = CoarseScreeningDecision(
                    study_id=article.study_id,
                    decision="exclude",
                    reason=deterministic_decision.rationale,
                    source_spans=deterministic_decision.source_spans,
                )
            else:
                coarse_candidates.append((index, article))

        workers = min(self.max_workers, len(coarse_candidates)) or 1
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_index = {
                executor.submit(
                    self.coarse_screener.run,
                    criteria=criteria,
                    synthesis_plan=synthesis_plan,
                    article=article,
                ): index
                for index, article in coarse_candidates
            }
            for future in as_completed(future_to_index):
                coarse_by_index[future_to_index[future]] = future.result()

        final_candidates = [
            (index, article)
            for index, article in indexed_articles
            if coarse_by_index[index].decision == "advance"
        ]
        final_by_index: dict[int, ArticleSynthesisScreeningResult] = {}
        workers = min(self.max_workers, len(final_candidates)) or 1
        with ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_index = {
                executor.submit(
                    self.synthesis_ready_screener.run,
                    criteria=criteria,
                    synthesis_plan=synthesis_plan,
                    article=article,
                ): index
                for index, article in final_candidates
            }
            for future in as_completed(future_to_index):
                final_by_index[future_to_index[future]] = future.result()

        decisions: list[ScreeningDecision] = []
        readiness: dict[str, list[SynthesisTargetReadiness]] = {}
        for index, article in indexed_articles:
            coarse_decision = coarse_by_index[index]
            if coarse_decision.decision == "exclude":
                deterministic = deterministic_by_index[index]
                decisions.append(
                    deterministic
                    if deterministic.decision == "exclude"
                    else ScreeningDecision(
                        study_id=article.study_id,
                        decision="exclude",
                        rationale=coarse_decision.reason,
                        exclusion_reason=coarse_decision.reason,
                        source_spans=coarse_decision.source_spans,
                    )
                )
                readiness[article.study_id] = []
                continue

            final = final_by_index[index]
            combined = ArticleScreeningResult(
                criterion_judgments=[
                    *deterministic_by_index[index].criterion_judgments,
                    *final.article_screening.criterion_judgments,
                ],
                overall_note=final.overall_note or final.article_screening.overall_note,
            )
            base_decision = screening_decision_from_article_result(
                study_id=article.study_id,
                result=combined,
            )
            supported = [
                row.target_id
                for row in final.target_readiness
                if row.status == SynthesisReadinessStatus.CURRENT_META_SUPPORTED
            ]
            unsupported = [
                row.target_id
                for row in final.target_readiness
                if row.status
                == SynthesisReadinessStatus.METHODOLOGICALLY_ELIGIBLE_UNSUPPORTED
            ]
            investigation = [
                row.target_id
                for row in final.target_readiness
                if row.status == SynthesisReadinessStatus.NEEDS_META_INVESTIGATION
            ]
            target_spans = [
                span for row in final.target_readiness for span in row.source_spans
            ]
            readable_table = _has_readable_raw_table(article)
            if base_decision.decision != "include":
                routing_status = "not_review_eligible"
                unavailable_reason = None
            elif not readable_table:
                routing_status = "meta_unavailable_no_readable_table"
                unavailable_reason = (
                    "No non-empty canonical raw table XML is available. This "
                    "blocks the current table-local Meta extraction method but "
                    "does not change Review inclusion, Study PIO, or RoB routing."
                )
                supported = []
                investigation = []
            elif supported:
                routing_status = "meta_ready"
                unavailable_reason = None
            elif investigation:
                routing_status = "needs_meta_investigation"
                unavailable_reason = None
            elif unsupported:
                routing_status = "meta_runtime_unsupported"
                unavailable_reason = next(
                    (
                        row.reason
                        for row in final.target_readiness
                        if row.status
                        == SynthesisReadinessStatus.METHODOLOGICALLY_ELIGIBLE_UNSUPPORTED
                    ),
                    None,
                )
            else:
                routing_status = "no_matching_synthesis_target"
                unavailable_reason = None
            decisions.append(
                replace(
                    base_decision,
                    source_spans=[*base_decision.source_spans, *target_spans],
                    meta_entry_target_ids=supported,
                    meta_investigation_target_ids=investigation,
                    methodologically_eligible_unsupported_target_ids=unsupported,
                    evidence_char_count=final.evidence_char_count,
                    evidence_source_count=final.evidence_source_count,
                    meta_routing_status=routing_status,
                    meta_unavailable_reason=unavailable_reason,
                )
            )
            readiness[article.study_id] = final.target_readiness

        return (
            [coarse_by_index[index] for index, _ in indexed_articles],
            decisions,
            readiness,
        )

    def _screen_one_article(
        self,
        *,
        criteria: ScreeningCriteria,
        article: CleanedArticle,
        policy: ScreeningPolicy,
    ) -> ScreeningDecision:
        deterministic = _deterministic_judgments(article=article, policy=policy)
        deterministic_result = ArticleScreeningResult(
            criterion_judgments=deterministic,
        )
        deterministic_decision = screening_decision_from_article_result(
            study_id=article.study_id,
            result=deterministic_result,
        )
        if deterministic_decision.decision == "exclude":
            return deterministic_decision

        if self.article_screener is None:
            raise ValueError("study screening requires an article screener")
        llm_result = self.article_screener.run(criteria=criteria, article=article)
        result = ArticleScreeningResult(
            criterion_judgments=[*deterministic, *llm_result.criterion_judgments],
            overall_note=llm_result.overall_note,
        )
        return screening_decision_from_article_result(
            study_id=article.study_id,
            result=result,
        )


def _append_system_criteria(
    *,
    criteria: ScreeningCriteria,
    policy: ScreeningPolicy,
) -> ScreeningCriteria:
    inclusion = list(criteria.inclusion_criteria)
    if policy.rct_only and RCT_INCLUSION_CRITERION not in inclusion:
        inclusion.append(RCT_INCLUSION_CRITERION)
    if (
        policy.rct_only
        and policy.pairwise_parallel_individual_only
        and PARALLEL_INDIVIDUAL_RCT_INCLUSION_CRITERION not in inclusion
    ):
        inclusion.append(PARALLEL_INDIVIDUAL_RCT_INCLUSION_CRITERION)
    if (
        policy.report_scope == ScreeningReportScope.PRIMARY_RESULTS_REPORT
        and PRIMARY_REPORT_INCLUSION_CRITERION not in inclusion
    ):
        inclusion.append(PRIMARY_REPORT_INCLUSION_CRITERION)
    if not inclusion:
        raise ValueError("study_screening requires at least one inclusion criterion")
    return ScreeningCriteria(
        inclusion_criteria=inclusion,
        exclusion_criteria=list(criteria.exclusion_criteria),
        rationale=criteria.rationale,
    )


def _deterministic_judgments(
    *,
    article: CleanedArticle,
    policy: ScreeningPolicy,
) -> list[ScreeningCriterionJudgment]:
    judgments: list[ScreeningCriterionJudgment] = []
    year_start = policy.publication_year_start
    year_end = policy.publication_year_end
    if year_start is not None or year_end is not None:
        year = _publication_year(article.metadata.publication_year)
        within_range = (
            year is not None
            and (year_start is None or year >= year_start)
            and (year_end is None or year <= year_end)
        )
        bounds = f"{year_start or '-inf'}..{year_end or '+inf'}"
        judgments.append(
            ScreeningCriterionJudgment(
                criterion_id="metadata_publication_year",
                criterion_text=f"Publication year is within {bounds}.",
                criterion_type=ScreeningCriterionType.INCLUSION,
                judgment=(
                    ScreeningCriterionJudgmentValue.YES
                    if within_range
                    else ScreeningCriterionJudgmentValue.NO
                ),
                reason=(
                    f"Publication year {year} is within {bounds}."
                    if within_range
                    else f"Publication year is missing, invalid, or outside {bounds}."
                ),
                decision_source="deterministic",
            )
        )

    allowed_languages = {value.strip().casefold() for value in policy.allowed_languages if value.strip()}
    if allowed_languages:
        article_languages = {
            value.strip().casefold() for value in article.metadata.languages if value.strip()
        }
        language_allowed = bool(article_languages & allowed_languages)
        judgments.append(
            ScreeningCriterionJudgment(
                criterion_id="metadata_language",
                criterion_text="Article language is allowed by the screening policy.",
                criterion_type=ScreeningCriterionType.INCLUSION,
                judgment=(
                    ScreeningCriterionJudgmentValue.YES
                    if language_allowed
                    else ScreeningCriterionJudgmentValue.NO
                ),
                reason=(
                    f"Article languages {sorted(article_languages)} match the allowed set."
                    if language_allowed
                    else "Article language is missing or outside the allowed set."
                ),
                decision_source="deterministic",
            )
        )

    if policy.exclude_retracted and (
        article.metadata.is_retracted or article.metadata.is_retraction_notice
    ):
        judgments.append(
            ScreeningCriterionJudgment(
                criterion_id="metadata_retraction",
                criterion_text="The article is retracted or is a retraction notice.",
                criterion_type=ScreeningCriterionType.EXCLUSION,
                judgment=ScreeningCriterionJudgmentValue.YES,
                reason="PubMed metadata identifies a retracted article or retraction notice.",
                decision_source="deterministic",
            )
        )

    return judgments


def _has_readable_raw_table(article: CleanedArticle) -> bool:
    """Current Meta candidate discovery starts from one canonical raw table."""

    return any(str(table.raw_xml or "").strip() for table in article.tables)


def _publication_year(value: str | None) -> int | None:
    text = str(value or "").strip()
    if len(text) != 4 or not text.isdigit():
        return None
    return int(text)


def _policy_from_constraints(constraints: WorkflowConstraints) -> ScreeningPolicy:
    start = None
    end = None
    raw_range = str(constraints.publication_year_range or "").strip()
    if raw_range:
        parts = [part.strip() for part in raw_range.split("-", 1)]
        if len(parts) != 2 or not all(part.isdigit() for part in parts):
            raise ValueError("publication_year_range must use YYYY-YYYY format")
        start, end = (int(part) for part in parts)
    return ScreeningPolicy(
        rct_only=str(constraints.study_design or "").strip().upper() == "RCT",
        pairwise_parallel_individual_only=constraints.supports_pairwise_rct_only,
        publication_year_start=start,
        publication_year_end=end,
    )
