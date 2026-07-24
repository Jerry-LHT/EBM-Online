"""API dependency construction."""

from __future__ import annotations

from ebm_backend.online_pipeline.application.use_cases.get_workflow_run import (
    GetWorkflowRun,
)
from ebm_backend.online_pipeline.application.use_cases.run_article_qualification import (
    RunArticleQualification,
)
from ebm_backend.online_pipeline.application.use_cases.run_grade import RunGrade
from ebm_backend.online_pipeline.application.use_cases.run_meta_analysis import RunMetaAnalysis
from ebm_backend.online_pipeline.application.use_cases.run_online_ebm_workflow import (
    RunOnlineEBMWorkflow,
)
from ebm_backend.online_pipeline.application.use_cases.run_q2pico import RunQ2PICO
from ebm_backend.online_pipeline.application.use_cases.run_risk_of_bias import RunRiskOfBias
from ebm_backend.online_pipeline.application.use_cases.run_search_retrieval import (
    RunSearchRetrieval,
)
from ebm_backend.online_pipeline.application.use_cases.run_study_pio import RunStudyPIO
from ebm_backend.online_pipeline.application.use_cases.run_study_screening import (
    RunStudyScreening,
)
from ebm_backend.online_pipeline.domain.screening import ScreeningEvidenceScope
from ebm_backend.online_pipeline.infrastructure.llm import load_llm_config
from ebm_backend.online_pipeline.infrastructure.methods.q2pico.factory import (
    build_production_q2pico,
)
from ebm_backend.online_pipeline.infrastructure.methods.article_qualification.factory import (
    build_production_article_qualifier,
)
from ebm_backend.online_pipeline.infrastructure.methods.grade.factory import (
    build_production_grade_imprecision_assessor,
    build_production_grade_inconsistency_assessor,
    build_production_grade_indirectness_assessor,
    build_production_grade_risk_of_bias_assessor,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.factory import (
    build_production_analysis_methods_selector,
    build_production_overall_estimates_calculator,
    build_production_study_evidence_agent,
    build_production_subgroup_analyzer,
    build_production_synthesis_planner,
)
from ebm_backend.online_pipeline.infrastructure.methods.meta_analysis.errors import (
    MetaAnalysisConfigurationError,
)
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.factory import (
    build_production_risk_of_bias,
)
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_onestep_llm.cache import (
    FileRoBDomainJudgementCache,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.factory import (
    build_search_retrieval_sources,
)
from ebm_backend.online_pipeline.infrastructure.methods.search_retrieval.pubmed_pmc.cache import (
    PubMedPmcFileCache,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_screening.factory import (
    build_production_staged_study_screening,
    build_production_study_screening,
)
from ebm_backend.online_pipeline.infrastructure.methods.study_pio.factory import (
    build_production_study_pio,
)
from ebm_backend.online_pipeline.infrastructure.persistence import (
    FileWorkflowRunStore,
    get_runtime_root,
)


def get_q2pico_use_case_for_api() -> RunQ2PICO:
    return RunQ2PICO(q2pico=build_production_q2pico())


def get_search_retrieval_use_case_for_api(
    *,
    source_names: list[str],
) -> RunSearchRetrieval:
    return RunSearchRetrieval(
        retrieval_sources=build_search_retrieval_sources(
            source_names=source_names,
            cache=PubMedPmcFileCache(get_runtime_root() / "cache"),
        ),
    )


def get_study_screening_use_case_for_api(
    *,
    evidence_scope: ScreeningEvidenceScope = ScreeningEvidenceScope.FULL_TEXT,
) -> RunStudyScreening:
    method_pair = build_production_study_screening(evidence_scope=evidence_scope)
    return RunStudyScreening(
        criteria_planner=method_pair.criteria_planner,
        article_screener=method_pair.article_screener,
    )


def get_study_pio_use_case_for_api() -> RunStudyPIO:
    return RunStudyPIO(
        study_pio_extractor=build_production_study_pio()
    )


def get_risk_of_bias_use_case_for_api() -> RunRiskOfBias:
    return RunRiskOfBias(
        risk_of_bias_assessor=build_production_risk_of_bias(
            domain_cache=FileRoBDomainJudgementCache(
                get_runtime_root() / "cache" / "rob1_article_level_v1"
            )
        )
    )


def get_meta_analysis_use_case_for_api(*, llm_config=None) -> RunMetaAnalysis:
    # Freeze one provider configuration snapshot for the whole workflow run.
    # Editing llm.local.json affects the next use-case construction, never a
    # later Meta stage in the same run.
    try:
        llm_config = llm_config or load_llm_config()
    except (FileNotFoundError, OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
        raise MetaAnalysisConfigurationError(stage="composition") from exc
    return RunMetaAnalysis(
        synthesis_planner=build_production_synthesis_planner(config=llm_config),
        study_evidence_agent=build_production_study_evidence_agent(config=llm_config),
        analysis_methods_selector=build_production_analysis_methods_selector(),
        subgroup_analyzer=build_production_subgroup_analyzer(),
        overall_estimates_calculator=build_production_overall_estimates_calculator(),
    )


def get_grade_use_case_for_api() -> RunGrade:
    return RunGrade(
        risk_of_bias_assessor=build_production_grade_risk_of_bias_assessor(),
        inconsistency_assessor=build_production_grade_inconsistency_assessor(),
        indirectness_assessor=build_production_grade_indirectness_assessor(),
        imprecision_assessor=build_production_grade_imprecision_assessor(),
    )


def get_online_workflow_use_case_for_api(
    *,
    source_names: list[str],
    evidence_scope: ScreeningEvidenceScope = ScreeningEvidenceScope.FULL_TEXT,
) -> RunOnlineEBMWorkflow:
    try:
        llm_config = load_llm_config()
    except (FileNotFoundError, OSError, KeyError, TypeError, ValueError, RuntimeError) as exc:
        raise MetaAnalysisConfigurationError(stage="composition") from exc
    screening_methods = build_production_staged_study_screening(config=llm_config)
    return RunOnlineEBMWorkflow(
        q2pico=get_q2pico_use_case_for_api(),
        search_retrieval=get_search_retrieval_use_case_for_api(
            source_names=source_names
        ),
        article_qualification=RunArticleQualification(
            qualifier=build_production_article_qualifier(
                config=llm_config,
                cache_root=(
                    get_runtime_root()
                    / "cache"
                    / "article_qualification_content_v1"
                ),
                debug_root=(
                    get_runtime_root()
                    / "debug"
                    / "article_qualification_content_v1"
                ),
            )
        ),
        study_screening=RunStudyScreening(
            criteria_planner=screening_methods.criteria_planner,
            coarse_screener=screening_methods.coarse_screener,
            synthesis_ready_screener=screening_methods.synthesis_ready_screener,
        ),
        study_pio=get_study_pio_use_case_for_api(),
        risk_of_bias=get_risk_of_bias_use_case_for_api(),
        meta_analysis=get_meta_analysis_use_case_for_api(llm_config=llm_config),
        grade=get_grade_use_case_for_api(),
        run_store=FileWorkflowRunStore(get_runtime_root() / "workflow_runs"),
    )


def get_workflow_run_use_case_for_api() -> GetWorkflowRun:
    return GetWorkflowRun(
        run_store=FileWorkflowRunStore(get_runtime_root() / "workflow_runs")
    )
