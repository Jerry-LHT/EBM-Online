"""Risk-of-bias method using calibrated per-domain extraction slots."""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ebm_backend.online_pipeline.domain.article import CleanedArticle
from ebm_backend.online_pipeline.domain.risk_of_bias import ROB1_DOMAINS, RiskOfBiasAssessment, RoB1DomainJudgement
from ebm_backend.online_pipeline.infrastructure.llm import LLMConfig, call_llm_json, load_llm_config
from ebm_backend.online_pipeline.infrastructure.methods.risk_of_bias.method_onestep_llm.method import _article_evidence


@dataclass(frozen=True)
class DomainSpec:
    slot_id: str
    domain_label: str
    criteria: str


DOMAIN_LABELS = {
    "random_sequence_generation": "Random sequence generation (selection bias)",
    "allocation_concealment": "Allocation concealment (selection bias)",
    "blinding_participants_personnel": "Blinding of participants and personnel (performance bias)",
    "blinding_outcome_assessment": "Blinding of outcome assessment (detection bias)",
    "incomplete_outcome_data": "Incomplete outcome data (attrition bias)",
    "selective_reporting": "Selective reporting (reporting bias)",
    "other_bias": "Other bias",
}


_RANDOM_SEQUENCE_CRITERIA = """\
Evaluate whether the study used a truly random allocation sequence.

Be reasonably PERMISSIVE for Low risk: if the paper describes randomization
with sufficient detail to suggest a proper random method was used, Low risk
is appropriate even without exhaustive methodological detail.

Low risk - any one of these supports Low:
- Explicit random method: random number table, computer random number generator,
  coin toss, shuffled cards/envelopes, dice, drawing lots, minimization
- "Randomized" or "randomly allocated" plus context clues that suggest proper
  randomization, e.g. "computer-generated", "random number generator",
  "permuted blocks", "stratified randomization", "central randomization",
  "pharmacy randomization", or similar phrases indicating a systematic random
  process
- Random permuted blocks with the random generation method described
- Description of randomization procedure that clearly indicates random
  allocation, e.g. "participants were randomly assigned using a computerized
  system"

High risk - requires clear evidence of non-random or predictable allocation:
- Explicitly non-random rules: birth date parity, admission date or day of week,
  hospital record number, alternation, clinician judgement, patient preference,
  test results, intervention availability
- Paper explicitly states a non-random method was used

Unclear risk - reserve for genuinely ambiguous cases:
- Only states "randomized" or "randomly allocated" with no additional context
  and no mention of computer, blocks, stratification, central allocation, etc.
- Insufficient information to judge and no context clues

Important: "randomized" alone with no context -> Unclear. But "randomized" plus
context clues (computer-generated, blocks, stratification, central allocation)
-> Low risk.

Common mistakes to avoid:
- "Computer-generated randomization" -> Low risk, not Unclear
- "Block randomization" or "stratified randomization" -> Low risk; these imply
  proper random sequence
- "Randomization was performed by statistician" -> Low risk; this suggests a
  proper method
"""


_ALLOCATION_CONCEALMENT_CRITERIA = """\
Evaluate whether the person enrolling participants could foresee the upcoming
group assignment before each participant was enrolled.

Critical distinction: this domain is not about how the random sequence was
generated. "Computer-generated randomization" or "random number generator"
describes sequence generation. Allocation concealment is about whether the
recruiter could peek at or predict the next assignment.

Default is Unclear. Only upgrade to Low if there is explicit description of a
concealment mechanism that prevents foreknowledge.

Low risk requires explicit mention of one of these mechanisms:
- Central allocation such as telephone, web-based, or pharmacy-controlled
  randomization
- Sequentially numbered, opaque, sealed envelopes (SNOSE); all three features
  are required
- Sequentially numbered identical drug containers
- Other mechanism that clearly prevents the recruiter from knowing the next
  assignment

High risk:
- Open random allocation schedule visible to recruiters
- Envelopes without all of: sequential numbering, opacity, and sealing
- Alternation or rotation
- Allocation by birth date, admission date, hospital record number
- Any procedure where the recruiter could foresee the assignment

Unclear risk, the default:
- Paper describes randomization method but says nothing about how assignments
  were concealed from recruiters
- Mentions "envelopes" without specifying opaque, sealed, and sequentially
  numbered
- No information about concealment at all
- Cluster trial where it is unclear whether participants were recruited before
  or after cluster randomization

Common mistakes to avoid:
- "Computer-generated randomization" describes sequence generation, not
  concealment -> Unclear
- "Randomization was performed by [person]" describes who did it, not whether
  it was concealed -> Unclear
- "Block randomization" describes sequence structure, not concealment ->
  Unclear
"""


_BLINDING_PARTICIPANTS_CRITERIA = """\
Evaluate whether participants and personnel delivering the intervention knew
the group assignment, and whether knowing could plausibly affect the outcomes.

This domain is judged across all study outcomes overall. Give the single
judgement that best represents the dominant risk for this study.

Low risk:
- Participants and key personnel were successfully blinded and blinding was
  unlikely to be broken
- Or not blinded / blinding incomplete but outcomes are unlikely to be
  influenced by knowledge of allocation, e.g. all-cause mortality

High risk:
- Not blinded or blinding incomplete and outcomes could be influenced
- Blinding attempted but likely broken and outcomes could be affected

Unclear risk:
- Does not specify who was blinded
- Only says "double blind" without specifying participants/personnel
- Insufficient information
"""


_BLINDING_OUTCOME_CRITERIA = """\
Evaluate whether the outcome assessor was blinded to allocation, and whether
the outcome measurement could be influenced by lack of blinding.

First identify who assessed the outcomes in this study: patient self-report,
clinician judgement, independent assessor, blinded coder, lab/imaging system,
or chart abstractor.

Important: the key question is whether knowledge of allocation could bias the
measurement of the outcome. Consider the nature of the outcome:
- Objective outcomes (lab values, mortality, imaging) are hard to bias even
  when unblinded
- Subjective outcomes (pain, quality of life, satisfaction, clinician scales)
  are easily biased

Worst-outcome rule: RoB is judged at the level of the most vulnerable outcome,
not averaged across the outcome set. If the study reports a mix of objective
and subjective/patient-reported outcomes, and the subjective outcomes are
unblinded or the patient is unblinded and is the assessor, the overall
judgement is High risk even if the objective outcomes alone would be Low.

Examples that are High risk:
- Study reports both mortality and a self-report quality-of-life questionnaire,
  and participants are not blinded
- Outcome assessors are not blinded and any clinician-rated scale, symptom
  score, or patient-reported measure is among the outcomes
- Patient self-report outcomes when participants are not blinded

Low risk:
- Outcome assessor explicitly blinded and blinding unlikely to be broken
- Or assessor unblinded but all outcomes are objective and measurement cannot
  be influenced. This requires that there are no subjective outcomes in the mix.

High risk - any of:
- Assessor unblinded or likely unblinded and at least one outcome is subjective
  or judgement-dependent
- Patient self-report outcomes and participants are not blinded
- Mix of objective and subjective outcomes with no blinding of assessor for
  the subjective ones

Unclear risk:
- Does not state whether outcome assessors were blinded and outcomes are
  entirely objective so blinding may not matter
- Only says "double blind" without clarifying whether this includes outcome
  assessment, and outcome types cannot be inferred
- No information about outcome assessment blinding and outcome types unclear

Common mistakes to avoid:
- Do not average across outcome types. One unblinded subjective outcome makes
  the whole domain High risk.
- Patient self-report outcomes: the patient is the assessor. If participants
  are not blinded and outcomes are self-reported -> High risk.
- "Objective" does not mean "unbiasable". Blood pressure measured by an
  unblinded clinician who decides when to stop measuring may be biased.
- Lab values measured by automated analyzer are Low risk for that outcome only;
  if other subjective outcomes exist, judge the domain on the subjective ones.
"""


_INCOMPLETE_OUTCOME_CRITERIA = """\
Evaluate whether attrition, withdrawals, exclusions or missing data could bias
the result for the outcomes of interest.

To judge this domain you need actual reported numbers about post-randomization
attrition on the analysed outcome: per-arm randomized versus analysed, reasons
for loss, and time horizon. When those numbers are not in the paper, you almost
certainly should judge Unclear, not High.

Step 1 - identify what counts as attrition for this judgement.
- Only post-randomization loss on the analysed outcome counts. Exclude:
  * Losses before randomization or before the intervention started
  * Participants in a study sub-design that was never intended to contribute
    to the outcome
  * "Anticipated" or "planned for" attrition stated only in the protocol or
    sample-size justification
- Use the analysed outcome denominator at the analysed time point, not some
  other intermediate questionnaire return rate.

Step 2 - judge using these guidelines.

Low risk:
- Essentially complete follow-up on the outcome, loss <= about 10%, with no
  meaningful arm imbalance
- Loss <= about 20%, balanced across arms within about 5 percentage points,
  and reasons not outcome-related
- Appropriate missing-data handling and attrition is moderate
- ITT analysis combined with low or balanced attrition
- Pre-randomization losses only and post-randomization data are intact

High risk requires the paper to report numbers that establish bias:
- Reported total loss >= about 30% on the analysed outcome and no convincing
  missing-data analysis showing robustness
- Reported differential loss >= about 10 percentage points between arms
- Reported loss > about 20% and differential >= about 5 percentage points
- Attrition imbalance with reasons plausibly related to the outcome
- Exclusions for lack of efficacy or adverse events imbalanced across arms
- Per-protocol / as-treated analysis materially deviating from random
  assignment with substantial crossover or post-hoc exclusion
- Inappropriate simple imputation, e.g. unjustified LOCF, when outcome
  trajectories likely differ across arms

Unclear risk:
- No CONSORT flow diagram and no per-arm analysed numbers in text or tables
- Only "ITT" is stated, with no numbers and no flow
- Attrition is mentioned but reasons, per-arm split, or size cannot be inferred
- The article's flow figure is referenced but not in the supplied text and no
  equivalent numbers appear in the article

Important calibration notes:
- Missing CONSORT / per-arm numbers / reasons -> Unclear, not High.
- Loss to follow-up before randomization or before the intervention is not
  attrition for this domain.
- A protocol expectation such as "33% loss expected" without observed data is
  not enough to judge High.
- A drop in questionnaire response on a secondary measure does not flip the
  primary outcome to High if the primary outcome denominator is intact.
- Reassurance such as "completers did not differ from non-completers" does not
  downgrade High when raw numbers cross High thresholds. If raw numbers are not
  reported, that reassurance also does not let you assert High.
"""


_SELECTIVE_REPORTING_CRITERIA = """\
Evaluate whether the article suggests selective outcome reporting relative to
a protocol, registration, methods section, or clearly stated planned outcomes.

This domain is not about missing attrition data or poor outcome measurement.
It is about whether expected outcomes are missing, incompletely reported, or
changed in a way that could bias the result.

Low risk:
- Trial registration or protocol is cited and the prespecified primary and
  secondary outcomes appear reported
- The methods list outcomes and the results report those outcomes with usable
  data
- The article explicitly explains a protocol deviation and the deviation is
  unlikely to suppress unfavorable results
- No evidence of missing or selectively reported outcomes after comparing
  methods and results

High risk requires positive evidence:
- A prespecified primary outcome is not reported, incompletely reported, or
  reported only in a non-usable way
- Outcomes in the methods, protocol, or trial registration are absent from the
  results without a convincing reason
- Outcome definitions, time points, or analyses appear changed in a way that
  favors significant results
- Only selected subscales, time points, or favorable outcomes are reported

Unclear risk:
- No protocol or registration is available and the methods/results comparison
  is insufficient
- Outcomes are mentioned vaguely and it is not possible to tell whether all
  planned outcomes were reported
- The article gives too little information to assess selective reporting
"""


_OTHER_BIAS_CRITERIA = """\
Evaluate whether there are other important sources of bias not covered by the
preceding RoB1 domains.

Focus on design, conduct, analysis, and reporting problems that could
materially bias the study. Do not mark High risk for ordinary limitations,
small sample size alone, or missing information alone.

Low risk:
- Baseline characteristics are broadly balanced or any imbalances are minor
- Funding, conflicts of interest, and deviations do not suggest a material bias
- No major design-specific concern is evident from the supplied article
- Pilot or feasibility status alone is not a high risk if the study appears
  otherwise fairly conducted

High risk requires positive evidence:
- Major baseline imbalance likely to affect outcomes
- Early stopping, contamination, co-intervention, non-adherence, or protocol
  deviation likely to bias effects
- Important unit-of-analysis problems, inappropriate clustering, or analysis
  choices likely to bias estimates
- Fraud, extreme conflict of interest with design/control of analysis, or other
  explicit concern raised by the article

Unclear risk:
- The article provides too little information about possible other sources of
  bias
- Baseline balance, funding, or protocol deviations are not reported clearly
  enough to judge
- There is a possible concern but insufficient evidence that it materially
  biases results
"""


SPECS: list[DomainSpec] = [
    DomainSpec("random_sequence_generation", DOMAIN_LABELS["random_sequence_generation"], _RANDOM_SEQUENCE_CRITERIA),
    DomainSpec("allocation_concealment", DOMAIN_LABELS["allocation_concealment"], _ALLOCATION_CONCEALMENT_CRITERIA),
    DomainSpec(
        "blinding_participants_personnel",
        DOMAIN_LABELS["blinding_participants_personnel"],
        _BLINDING_PARTICIPANTS_CRITERIA,
    ),
    DomainSpec(
        "blinding_outcome_assessment",
        DOMAIN_LABELS["blinding_outcome_assessment"],
        _BLINDING_OUTCOME_CRITERIA,
    ),
    DomainSpec("incomplete_outcome_data", DOMAIN_LABELS["incomplete_outcome_data"], _INCOMPLETE_OUTCOME_CRITERIA),
    DomainSpec("selective_reporting", DOMAIN_LABELS["selective_reporting"], _SELECTIVE_REPORTING_CRITERIA),
    DomainSpec("other_bias", DOMAIN_LABELS["other_bias"], _OTHER_BIAS_CRITERIA),
]
SPECS_BY_ID = {spec.slot_id: spec for spec in SPECS}
LLM_DOMAINS = [domain_id for domain_id in ROB1_DOMAINS if domain_id in SPECS_BY_ID]


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
            raise RuntimeError("Missing LLM config for risk_of_bias.method_calibrated_slots")

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
                    notes="Seven-domain calibrated slot method using article-only evidence.",
                )
            )
        return results

    def _run_domains(self, *, config: LLMConfig, evidence: str) -> list[RoB1DomainJudgement]:
        if self.workers > 1:
            with ThreadPoolExecutor(max_workers=min(self.workers, len(LLM_DOMAINS))) as executor:
                return list(
                    executor.map(
                        lambda domain_id: _run_llm_domain(config=config, spec=SPECS_BY_ID[domain_id], evidence=evidence),
                        LLM_DOMAINS,
                    )
                )
        return [_run_llm_domain(config=config, spec=SPECS_BY_ID[domain_id], evidence=evidence) for domain_id in LLM_DOMAINS]


def build_method() -> Method:
    return Method()


def _run_llm_domain(*, config: LLMConfig, spec: DomainSpec, evidence: str) -> RoB1DomainJudgement:
    system_prompt = build_system_prompt(spec)
    user_prompt = f"{evidence}\n\nAssess {spec.domain_label}. Output JSON only."
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            parsed = call_llm_json(config=config, system=system_prompt, prompt=user_prompt)
            return RoB1DomainJudgement(
                domain=spec.slot_id,
                judgement=_normalize_judgement(parsed.get("judgement")),
                rationale=str(parsed.get("support_text") or parsed.get("rationale") or ""),
            )
        except (json.JSONDecodeError, ValueError) as exc:
            last_error = exc
            if attempt == 0:
                user_prompt = (
                    f"{evidence}\n\nAssess {spec.domain_label} again. "
                    "Your previous response could not be parsed. Return exactly one strict JSON object "
                    'with double-quoted keys and string values for "domain", "judgement", "support_text", and "source".'
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
        domain=spec.slot_id,
        judgement="unclear_risk",
        rationale=f"LLM call failed or returned invalid JSON for {spec.domain_label}: {last_error}",
    )


def build_system_prompt(spec: DomainSpec) -> str:
    return f"""You are a systematic-review risk-of-bias assessor following Cochrane Handbook Chapter 8.

You are assessing ONE domain only:
Domain: {spec.domain_label}

{spec.criteria}

META-PRINCIPLE: High risk requires positive evidence, not absence of evidence.

To call a domain High risk, you must point to something the article says or
shows that constitutes a flaw. Missing information by itself is not evidence
of High risk; it is evidence of Unclear risk. Concretely:

  Random sequence generation (selection bias)
    High requires: the paper describes a non-random or predictable rule
    (birth date parity, admission date / day of week, hospital record number,
    alternation, clinician judgement, patient preference, test results,
    intervention availability). Silence about the method => Unclear, not High.

  Allocation concealment (selection bias)
    High requires: the paper describes a procedure where the recruiter could
    foresee the upcoming assignment (open random list visible to recruiters,
    envelopes that are not sequentially numbered + opaque + sealed,
    alternation, allocation by birth date / admission date / record number).
    Silence about concealment => Unclear, not High.

  Blinding of participants and personnel (performance bias)
    High requires: paper says blinding was absent or incomplete and the outcome
    can plausibly be influenced by knowledge of allocation (subjective outcomes
    such as pain, quality of life, symptom scales, self-report). Silence about
    blinding and silence about outcome subjectivity => Unclear. Objective
    outcomes such as all-cause mortality from records or automated lab assays
    without blinding can still be Low.

  Blinding of outcome assessment (detection bias)
    High requires: paper indicates the assessor was unblinded, or the patient
    is unblinded and is the assessor for self-report measures, and at least one
    outcome is subjective / judgement-dependent. Silence about assessor
    blinding => Unclear, not High. Apply the worst-outcome rule: one unblinded
    subjective outcome makes the domain High even if objective outcomes are
    also reported.

  Incomplete outcome data (attrition bias)
    High requires that the paper reports numbers establishing the bias: e.g.
    observed loss >= about 30% on the analysed outcome, observed differential
    loss >= about 10 percentage points, dropout reasons clearly tied to the
    intervention, or PP/as-treated analyses materially deviating from random
    assignment. If CONSORT flow / per-arm analysed numbers / reasons are
    missing and cannot be inferred from the article, this is Unclear, not High.

  Selective reporting (reporting bias)
    High requires direct comparison of pre-specified outcomes (protocol,
    registry, or Methods) against what is actually reported, with concrete
    discrepancies. Without that comparison, treat as Unclear.

GLOBAL JUDGEMENT GUIDANCE:

1. Use the domain-specific criteria above as your primary guide. Different
   domains have different evidence thresholds.

2. Unclear risk is the appropriate judgement when the paper does not say enough
   to confirm Low or High.

3. Use only what the paper explicitly states or what can be reasonably read
   from the reported methods. Do not invent details. Do not infer High risk
   from missing detail.

4. The support_text quote should directly bear on this domain. If you cannot
   find a direct quote, write "Summary: ..." and explain what you concluded
   from the available evidence, including absence of evidence.

Use only the supplied article sections and tables. Do not use benchmark gold labels.

Output a single JSON object with exactly these fields:
{{
  "domain": "{spec.domain_label}",
  "judgement": "Low risk | High risk | Unclear risk",
  "support_text": "Quote: ... Comment: ... OR Summary: ... Comment: ...",
  "source": "source_full_text | source_review_characteristics | source_protocol | source_registry | author_correspondence"
}}

Rules:
- judgement must be exactly one of: Low risk, High risk, Unclear risk
- support_text must include both the evidence, or note its absence, and the reasoning
- Output JSON only, no text outside the JSON object"""


def _normalize_judgement(value: Any) -> str:
    text = str(value or "").lower().strip()
    if "low" in text:
        return "low_risk"
    if "high" in text:
        return "high_risk"
    return "unclear_risk"
