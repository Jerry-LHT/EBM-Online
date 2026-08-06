from __future__ import annotations

import pytest

from ebm_backend.online_pipeline_v2.domain.common import Provenance
from ebm_backend.online_pipeline_v2.domain.protocol import (
    AnalysisPlan,
    BackgroundSection,
    CertaintyPlan,
    DataCollectionPlan,
    EffectMeasurePlan,
    EligibilityCriteria,
    EligibilitySection,
    MethodologyProfile,
    MethodologyReference,
    OutcomeMeasure,
    OutcomePlan,
    OutcomeRole,
    PICO,
    ProtocolDraft,
    ProtocolDocument,
    ProtocolDocumentSection,
    ProtocolMethods,
    ProtocolReviewType,
    ProtocolSemanticSection,
    RiskOfBiasPlan,
    SearchPlan,
    SearchSource,
    SearchSourceStrategy,
    SearchSourceType,
    StudySelectionPlan,
    SynthesisPICO,
    SynthesisPlan,
)
from ebm_backend.online_pipeline_v2.domain.selection import (
    StudySelectionProtocol,
    study_selection_protocol_from_draft,
)
from ebm_backend.online_pipeline_v2.domain.study_characteristics import (
    CharacteristicsMethodSectionName,
    StudyCharacteristicsMethodSection,
    StudyCharacteristicsProtocolContext,
)
from ebm_backend.online_pipeline_v2.domain.study_data import (
    StudyResultsProtocol,
    study_results_protocol_from_draft,
)
from ebm_backend.online_pipeline_v2.domain.synthesis import (
    EvidenceSynthesisProtocol,
    evidence_synthesis_protocol_from_draft,
)


@pytest.fixture
def source() -> Provenance:
    return Provenance(
        source_id="source-1",
        source_type="user_input",
        locator="question",
    )


@pytest.fixture
def protocol() -> ProtocolDraft:
    pico = PICO(
        population=("adults",),
        intervention=("intervention",),
        comparator=("usual care",),
        outcomes=("mortality",),
    )
    eligibility_section = EligibilitySection(
        description="Eligible studies",
        inclusion_criteria=("Meets the specified criterion",),
    )
    return ProtocolDraft(
        schema_version="protocol-artifact.v2",
        version="protocol-1",
        title="Intervention for adults",
        background=BackgroundSection(
            condition_or_problem="The condition affects adults.",
            intervention="The intervention is under review.",
            how_intervention_might_work="It may improve the condition.",
            rationale="The evidence requires synthesis.",
        ),
        review_question="Does the intervention reduce mortality?",
        review_pico=pico,
        objectives=("Assess the effects of the intervention.",),
        methods=ProtocolMethods(
            eligibility=EligibilityCriteria(
                types_of_studies=eligibility_section,
                types_of_participants=eligibility_section,
                types_of_interventions=eligibility_section,
                comparators=eligibility_section,
            ),
            outcomes=OutcomePlan(
                (
                    OutcomeMeasure(
                        name="mortality",
                        definition="Death from any cause",
                        measurement="Number of deaths",
                        time_points=("12 months",),
                        role=OutcomeRole.PRIMARY,
                    ),
                )
            ),
            search=SearchPlan(
                structured_sources=(
                    SearchSource(
                        source_name="MEDLINE",
                        source_type=SearchSourceType.DATABASE,
                        platform="Ovid",
                        date_coverage="inception to search date",
                    ),
                    SearchSource(
                        source_name="ClinicalTrials.gov",
                        source_type=SearchSourceType.TRIAL_REGISTRY,
                        platform="ClinicalTrials.gov",
                        date_coverage="inception to search date",
                    ),
                ),
                strategies=(
                    SearchSourceStrategy(
                        source_name="MEDLINE",
                        strategy=(
                            "1 intervention.ti,ab.\n"
                            "2 randomized controlled trial.pt."
                        ),
                    ),
                ),
            ),
            selection=StudySelectionPlan(
                title_abstract_screening="Screen all retrieved records.",
                full_report_assessment="Assess potentially eligible reports.",
                reviewer_process="Two reviewers work independently.",
                disagreement_resolution="Resolve by discussion or a third reviewer.",
            ),
            data_collection=DataCollectionPlan(
                extraction_process="Two reviewers extract data independently.",
                data_items=("study methods", "participants", "results"),
                study_report_linkage="Link all reports from the same study.",
                missing_information="Contact investigators when needed.",
            ),
            risk_of_bias=RiskOfBiasPlan(
                reviewer_process="Two reviewers assess each RoB 1 domain.",
                disagreement_resolution="Resolve by consensus.",
                use_in_synthesis="Consider judgements in interpretation.",
                tool="cochrane_rob_1",
            ),
            analysis=AnalysisPlan(
                effect_measures=(
                    EffectMeasurePlan(
                        result_type="dichotomous",
                        effect_measure="risk ratio",
                    ),
                ),
                unit_of_analysis="Use the randomized participant.",
                missing_data="Seek and report missing data.",
                heterogeneity="Assess clinical and statistical heterogeneity.",
                reporting_bias="Assess reporting bias when evidence permits.",
            ),
            synthesis=SynthesisPlan(
                comparisons=(
                    SynthesisPICO(
                        population=("adults",),
                        intervention=("intervention",),
                        comparator=("usual care",),
                        outcomes=("mortality",),
                        time_frames=("12 months",),
                        study_designs=("randomized controlled trial",),
                        grouping_rules=("Combine clinically comparable studies",),
                    ),
                ),
                quantitative_synthesis_criteria="Pool clinically comparable results.",
                meta_analysis_methods="Use an appropriate meta-analysis model.",
                non_meta_synthesis="Use structured synthesis without meta-analysis.",
                subgroup_analyses=("Baseline severity",),
                sensitivity_analyses=("Exclude high risk of bias studies",),
            ),
            certainty=CertaintyPlan(
                outcomes=("mortality",),
                summary_of_findings_plan="Prepare a Summary of Findings table.",
                approach="GRADE",
            ),
        ),
        methodology_profile=MethodologyProfile(
            decisions=(),
            authorities=(
                MethodologyReference(
                    standard="cochrane_handbook",
                    title=(
                        "Cochrane Handbook for Systematic Reviews of Interventions"
                    ),
                    version_or_revision="Version 6.5 (2024)",
                    sections=("Chapters 2-14",),
                    url=(
                        "https://www.cochrane.org/authors/"
                        "handbooks-and-manuals/handbook/current"
                    ),
                    accessed_on="2026-07-25",
                ),
                MethodologyReference(
                    standard="mecir",
                    title=(
                        "Methodological Expectations of Cochrane "
                        "Intervention Reviews"
                    ),
                    version_or_revision="Current online revision",
                    sections=("C1-C23",),
                    url=(
                        "https://www.cochrane.org/authors/handbooks-and-manuals/"
                        "mecir-manual/standards-conduct-new-cochrane-intervention-"
                        "reviews-c1-c75/developing-protocol-review-c1-c23"
                    ),
                    accessed_on="2026-07-25",
                ),
                MethodologyReference(
                    standard="revman_protocol_template",
                    title="RevMan Protocol project template",
                    version_or_revision="Current online revision",
                    sections=("Protocol project template",),
                    url=(
                        "https://documentation.cochrane.org/revman-kb/"
                        "protocol-project-template-281608353.html"
                    ),
                    accessed_on="2026-07-25",
                ),
                MethodologyReference(
                    standard="cochrane_rob_1",
                    title="Cochrane Risk of Bias 1 tool",
                    version_or_revision="Original 2011 version",
                    sections=("Risk of bias domains",),
                    url=(
                        "https://www.cochrane.org/authors/handbooks-and-manuals/"
                        "handbook/previous-versions"
                    ),
                    accessed_on="2026-07-25",
                ),
            ),
        ),
        document=ProtocolDocument(
            template_id="q2protocol.test.v2",
            version_or_revision="1",
            review_type=ProtocolReviewType.INTERVENTION,
            language="English",
            tense="prospective",
            sections=tuple(
                ProtocolDocumentSection(
                    section_id=semantic.value,
                    title=title,
                    semantic_section=semantic,
                    order=order,
                    required=True,
                    content=None,
                )
                for order, (semantic, title) in enumerate(
                    (
                        (ProtocolSemanticSection.TITLE, "Title"),
                        (ProtocolSemanticSection.BACKGROUND, "Background"),
                        (
                            ProtocolSemanticSection.REVIEW_QUESTION,
                            "Review question",
                        ),
                        (ProtocolSemanticSection.REVIEW_PICO, "Review PICO"),
                        (ProtocolSemanticSection.OBJECTIVES, "Objectives"),
                        (ProtocolSemanticSection.METHODS, "Methods"),
                        (
                            ProtocolSemanticSection.METHODOLOGY,
                            "Methodology basis",
                        ),
                    )
                )
            ),
        ),
    )


@pytest.fixture
def selection_protocol(protocol: ProtocolDraft) -> StudySelectionProtocol:
    return study_selection_protocol_from_draft(protocol)


@pytest.fixture
def results_protocol(protocol: ProtocolDraft) -> StudyResultsProtocol:
    return study_results_protocol_from_draft(protocol)


@pytest.fixture
def synthesis_protocol(protocol: ProtocolDraft) -> EvidenceSynthesisProtocol:
    return evidence_synthesis_protocol_from_draft(protocol)


@pytest.fixture
def characteristics_protocol_context(
    protocol: ProtocolDraft,
    source: Provenance,
) -> StudyCharacteristicsProtocolContext:
    sections = (
        (
            CharacteristicsMethodSectionName.STUDY_DESIGNS,
            "Types of studies",
            "Include randomized controlled trials.",
        ),
        (
            CharacteristicsMethodSectionName.PARTICIPANTS,
            "Types of participants",
            "Include adults with the condition.",
        ),
        (
            CharacteristicsMethodSectionName.INTERVENTIONS,
            "Types of interventions",
            "Compare the intervention with usual care.",
        ),
        (
            CharacteristicsMethodSectionName.PRIMARY_OUTCOMES,
            "Primary outcomes",
            "Mortality at 12 months.",
        ),
        (
            CharacteristicsMethodSectionName.DATA_COLLECTION,
            "Data extraction and management",
            "Extract Study methods, participants, interventions, and outcomes.",
        ),
    )
    return StudyCharacteristicsProtocolContext(
        protocol_version=protocol.version,
        review_question=protocol.review_question,
        review_pico=protocol.review_pico,
        method_sections=tuple(
            StudyCharacteristicsMethodSection(name, heading, text)
            for name, heading, text in sections
        ),
        provenance=(source,),
    )
