from __future__ import annotations

from dataclasses import dataclass, field

from ebm_backend.online_pipeline.application.use_cases.run_study_screening import (
    RunStudyScreening,
)
from ebm_backend.online_pipeline.domain.article import (
    ArticleMetadata,
    ArticleSection,
    ArticleTable,
    ArticleXmlContent,
    CleanedArticle,
)
from ebm_backend.online_pipeline.domain.common import DataType, WorkflowConstraints
from ebm_backend.online_pipeline.domain.meta_analysis import (
    AnalysisComparison,
    AnalysisOutcome,
    AnalysisSubgroup,
    AnalysisTimepoint,
    MetaAnalysisSynthesisPlan,
    SynthesisTarget,
)
from ebm_backend.online_pipeline.domain.question import QuestionPICO
from ebm_backend.online_pipeline.domain.screening import (
    ArticleScreeningResult,
    ArticleSynthesisScreeningResult,
    CoarseScreeningDecision,
    ScreeningCriteria,
    ScreeningCriterionJudgment,
    ScreeningCriterionJudgmentValue,
    ScreeningCriterionType,
    SynthesisReadinessStatus,
    SynthesisTargetReadiness,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.staged_synthesis_screening_llm.evidence import (
    build_coarse_evidence,
    build_final_evidence,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.staged_synthesis_screening_llm.method import (
    CoarseSynthesisStudyArticleScreener,
    SynthesisReadyStudyArticleScreener,
)


@dataclass(frozen=True)
class _CriteriaPlanner:
    def run(self, **kwargs) -> ScreeningCriteria:
        return ScreeningCriteria(
            inclusion_criteria=["Adults with knee osteoarthritis"],
            exclusion_criteria=["Protocol-only report"],
        )


@dataclass
class _CoarseScreener:
    calls: list[str] = field(default_factory=list)

    def run(self, *, article, **kwargs) -> CoarseScreeningDecision:
        self.calls.append(article.study_id)
        return CoarseScreeningDecision(
            study_id=article.study_id,
            decision="exclude" if article.study_id == "coarse-exclude" else "advance",
            reason="Explicit mismatch" if article.study_id == "coarse-exclude" else "Advance",
        )


@dataclass
class _FinalScreener:
    calls: list[str] = field(default_factory=list)

    def run(self, *, criteria, synthesis_plan, article, **kwargs):
        self.calls.append(article.study_id)
        judgments = [
            ScreeningCriterionJudgment(
                criterion_id=f"inc_{index}",
                criterion_text=text,
                criterion_type=ScreeningCriterionType.INCLUSION,
                judgment=ScreeningCriterionJudgmentValue.YES,
                reason="Established by full text.",
            )
            for index, text in enumerate(criteria.inclusion_criteria, start=1)
        ]
        judgments.extend(
            ScreeningCriterionJudgment(
                criterion_id=f"exc_{index}",
                criterion_text=text,
                criterion_type=ScreeningCriterionType.EXCLUSION,
                judgment=ScreeningCriterionJudgmentValue.NO,
                reason="Not present.",
            )
            for index, text in enumerate(criteria.exclusion_criteria, start=1)
        )
        status = (
            SynthesisReadinessStatus.METHODOLOGICALLY_ELIGIBLE_UNSUPPORTED
            if article.study_id == "adjusted-only"
            else SynthesisReadinessStatus.CURRENT_META_SUPPORTED
        )
        return ArticleSynthesisScreeningResult(
            article_screening=ArticleScreeningResult(criterion_judgments=judgments),
            target_readiness=[
                SynthesisTargetReadiness(
                    target_id=synthesis_plan.targets[0].target_id,
                    status=status,
                    reason="Adjusted contrast only" if status.value.endswith("unsupported") else "Arm-level data",
                )
            ],
        )


def _plan() -> MetaAnalysisSynthesisPlan:
    return MetaAnalysisSynthesisPlan(
        plan_id="plan-1",
        review_id="review-1",
        version="1",
        status="frozen",
        plan_hash="hash-1",
        targets=[
            SynthesisTarget(
                target_id="target-1",
                setting_family_id="family-1",
                population_scope="adults with knee osteoarthritis",
                comparison=AnalysisComparison(
                    experimental="exercise",
                    comparator="usual care",
                ),
                outcome=AnalysisOutcome(label="pain", measure="pain scale"),
                timepoint=AnalysisTimepoint(label="12 weeks"),
                subgroup=AnalysisSubgroup(),
                data_type=DataType.CONTINUOUS,
            )
        ],
    )


def _article(study_id: str) -> CleanedArticle:
    return CleanedArticle(
        study_id=study_id,
        metadata=ArticleMetadata(title=study_id),
        xml_content=ArticleXmlContent(),
        tables=[
            ArticleTable(
                table_id="results",
                caption="Results",
                raw_xml="<table><tr><td>result</td></tr></table>",
            )
        ],
    )


def test_staged_screening_preserves_runtime_unsupported_eligibility() -> None:
    coarse = _CoarseScreener()
    final = _FinalScreener()
    use_case = RunStudyScreening(
        criteria_planner=_CriteriaPlanner(),
        coarse_screener=coarse,
        synthesis_ready_screener=final,
        max_workers=3,
    )

    result = use_case.execute(
        question_text="Does exercise reduce knee pain?",
        question_pico=QuestionPICO(P=["adults"], I=["exercise"], C=["usual care"], O=["pain"]),
        constraints=WorkflowConstraints(),
        articles=[
            _article("supported"),
            _article("adjusted-only"),
            _article("coarse-exclude"),
        ],
        synthesis_plan=_plan(),
    )

    assert result.included_studies == ["supported", "adjusted-only"]
    assert [row.study_id for row in result.decisions] == [
        "supported",
        "adjusted-only",
        "coarse-exclude",
    ]
    adjusted = result.decisions[1]
    assert adjusted.decision == "include"
    assert adjusted.methodologically_eligible_unsupported_target_ids == ["target-1"]
    assert result.methodologically_eligible_unsupported_studies == ["adjusted-only"]
    assert result.meta_ready_studies == ["supported"]
    assert set(final.calls) == {"supported", "adjusted-only"}
    assert "coarse-exclude" not in final.calls


def test_no_readable_table_blocks_only_meta_routing() -> None:
    article = CleanedArticle(
        study_id="no-table",
        metadata=ArticleMetadata(title="Eligible RCT"),
        xml_content=ArticleXmlContent(
            sections=[
                ArticleSection(
                    section_id="results",
                    title="Results",
                    text="Results reported.",
                )
            ]
        ),
    )
    result = RunStudyScreening(
        criteria_planner=_CriteriaPlanner(),
        coarse_screener=_CoarseScreener(),
        synthesis_ready_screener=_FinalScreener(),
    ).execute(
        question_text="Does exercise reduce knee pain?",
        question_pico=QuestionPICO(P=["adults"], I=["exercise"], C=["usual care"], O=["pain"]),
        constraints=WorkflowConstraints(),
        articles=[article],
        synthesis_plan=_plan(),
    )

    assert result.included_studies == ["no-table"]
    assert result.meta_ready_studies == []
    assert result.meta_unavailable_no_readable_table_studies == ["no-table"]
    assert result.decisions[0].meta_routing_status == "meta_unavailable_no_readable_table"


def test_staged_screening_requires_a_frozen_plan() -> None:
    use_case = RunStudyScreening(
        criteria_planner=_CriteriaPlanner(),
        coarse_screener=_CoarseScreener(),
        synthesis_ready_screener=_FinalScreener(),
    )

    try:
        use_case.execute(
            question_text="Question",
            question_pico=QuestionPICO(P=["adults"]),
            constraints=WorkflowConstraints(),
            articles=[_article("study-1")],
        )
    except ValueError as exc:
        assert "frozen synthesis_plan" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_evidence_navigation_handles_empty_headings_and_captionless_tables() -> None:
    article = CleanedArticle(
        study_id="study-1",
        metadata=ArticleMetadata(title="Randomized exercise trial"),
        xml_content=ArticleXmlContent(
            sections=[
                ArticleSection(
                    section_id="s1",
                    title="",
                    text="Adults with knee osteoarthritis were randomized to exercise or usual care.",
                ),
                ArticleSection(
                    section_id="s2",
                    title="R",
                    text="Pain scores at 12 weeks were reported for both groups.",
                ),
            ]
        ),
        tables=[
            ArticleTable(
                table_id="t1",
                caption="",
                raw_xml="<table-wrap><tr><td>Pain mean SD N at 12 weeks</td></tr></table-wrap>",
            )
        ],
    )
    criteria = ScreeningCriteria(inclusion_criteria=["Randomized adults"])
    plan = _plan()

    coarse = build_coarse_evidence(
        article=article,
        criteria=criteria,
        synthesis_plan=plan,
        max_chars=2_000,
    )
    final = build_final_evidence(
        article=article,
        criteria=criteria,
        synthesis_plan=plan,
        max_chars=4_000,
    )

    assert coarse.char_count <= 2_000
    assert all(block.kind != "raw_table_xml" for block in coarse.blocks)
    assert any(block.label == "untitled section" for block in coarse.blocks)
    assert final.char_count <= 4_000
    assert any(block.kind == "raw_table_xml" for block in final.blocks)
    assert any(block.label == "caption unavailable" for block in final.blocks)


def test_llm_adapters_map_quotes_to_sources_and_target_keys_to_frozen_ids() -> None:
    article = CleanedArticle(
        study_id="study-1",
        metadata=ArticleMetadata(title="Randomized exercise trial"),
        xml_content=ArticleXmlContent(
            sections=[
                ArticleSection(
                    section_id="results",
                    title="Results",
                    text="Adults were randomized. Pain results were available at 12 weeks.",
                )
            ]
        ),
        tables=[
            ArticleTable(
                table_id="pain",
                caption="Pain",
                raw_xml="<table><td>exercise mean 2 SD 1 N 20; usual care mean 4 SD 1 N 20</td></table>",
            )
        ],
    )
    criteria = ScreeningCriteria(
        inclusion_criteria=["Randomized adults"],
        exclusion_criteria=["Protocol-only report"],
    )

    def caller(**kwargs):
        assert kwargs["config"]["sdk_max_retries"] == 0
        assert kwargs["config"]["json_marker_retry_enabled"] is False
        return {
            "criterion_judgments": {
                "inc_1": {
                    "judgment": "yes",
                    "reason": "Randomized adults.",
                    "evidence_spans": ["Adults were randomized."],
                },
                "exc_1": {
                    "judgment": "no",
                    "reason": "Primary results are reported.",
                    "evidence_spans": ["Pain results were available at 12 weeks."],
                },
            },
            "target_readiness": {
                "target_1": {
                    "status": "current_meta_supported",
                    "reason": "Both arms report mean, SD, and N.",
                    "data_representation": "continuous_arm_level",
                    "experimental_arm": "exercise",
                    "control_arm": "usual care",
                    "evidence_spans": [
                        "exercise mean 2 SD 1 N 20; usual care mean 4 SD 1 N 20"
                    ],
                }
            },
            "overall_note": "Eligible and ready.",
        }

    result = SynthesisReadyStudyArticleScreener(
        config={"api_mode": "responses"},
        llm_caller=caller,
    ).run(criteria=criteria, synthesis_plan=_plan(), article=article)

    assert result.target_readiness[0].target_id == "target-1"
    assert result.target_readiness[0].source_spans[0].source_id.startswith("table:pain")
    assert result.article_screening.criterion_judgments[0].source_spans[0].source_id.startswith(
        "section:results"
    )
    assert result.evidence_char_count > 0


def test_coarse_llm_stage_uses_exactly_one_method_retry() -> None:
    attempts = []

    def caller(**kwargs):
        attempts.append(kwargs)
        if len(attempts) == 1:
            raise RuntimeError("temporary provider failure")
        return {
            "decision": "advance",
            "reason": "No decisive mismatch.",
            "evidence_spans": [],
        }

    result = CoarseSynthesisStudyArticleScreener(
        config={"api_mode": "responses"},
        llm_caller=caller,
    ).run(
        criteria=ScreeningCriteria(inclusion_criteria=["Randomized adults"]),
        synthesis_plan=_plan(),
        article=_article("study-1"),
    )

    assert result.decision == "advance"
    assert len(attempts) == 2
    assert all(call["config"]["sdk_max_retries"] == 0 for call in attempts)
