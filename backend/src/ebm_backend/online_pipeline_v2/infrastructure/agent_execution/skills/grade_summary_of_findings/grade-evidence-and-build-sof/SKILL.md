---
name: grade-evidence-and-build-sof
description: Assess certainty of evidence and produce Cochrane intervention-review Summary of Findings artifacts from complete Protocol context and an immutable GRADE Evidence Package. Use when performing the backend GRADE with Summary of Findings professional task.
---

# Grade Evidence and Build SoF

Work as the review's GRADE expert. Apply the Protocol and the evidence actually
present in the staged package. Use current official methodology to resolve
details that the Protocol leaves open. Do not reconstruct or search for a
completed review answer.

When `find-and-read-methodology` is supplied as a companion Skill, use it to
inspect the execution-bearing certainty and presentation authority needed by
this task. Keep evidence-body selection, GRADE judgements, and Summary of
Findings construction in this Skill.

## Inputs and evidence boundary

Read `inputs/task.json` first. Then inspect every declared file under
`inputs/artifacts/grade-evidence-package/`. Read the complete `search.json`,
`selection.json`, `risk-of-bias.json`, and `synthesis.json` evidence before
grading. The optional CSVs are deterministic projections only; their absence
does not imply missing evidence, and they never replace the semantic Synthesis
document, including no-pooling, other synthesis, no-evidence, and issues.

Use scientific evidence only from:

- the complete model-visible Protocol context;
- the immutable package files and their provenance;
- results returned by declared deterministic scripts.

You may use Web search and network access only to consult current, directly
applicable official or primary methodology. Prefer the governing Cochrane,
GRADE Working Group, and named risk-of-bias tool sources. Do not use Web access
to find Studies, Reports, extracted results, a target review, Gold, an existing
Summary of Findings table, or completed-review answers. Do not redo search,
selection, data extraction, Risk of Bias, or synthesis.

Read [references/task-contract.md](references/task-contract.md) before working.
Read [references/artifact-contract.md](references/artifact-contract.md) before
writing outputs.

## Professional workflow

1. Read the Protocol as one prospective methodological plan: its PICO,
   eligibility, outcome definitions and timeframes, risk-of-bias method,
   effect measures, synthesis rules, reporting-bias plan, and SoF/GRADE plan.
   Explicit Protocol choices bind the task.
2. Select the main comparison or comparisons and no more than seven important
   outcomes per table. Follow the Protocol; never select because results look
   favourable or statistically significant. Record the Protocol or current
   official basis for the selection.
3. Define one evidence body for each selected
   comparison-outcome-timeframe combination. Use a `graded` profile when an
   evidence body exists, including a single-Study or non-pooled body, and link
   it to the Synthesis Analysis or Analyses it uses. Use a `no_evidence`
   profile only when no eligible evidence contributes to the selected outcome.
   Do not put certainty, downgrade domains, upgrade domains, or an Analysis
   reference in a `no_evidence` profile.
4. Interpret upstream Risk of Bias using its actual tool, version, target,
   assessment level, effect of interest, and judgement semantics. Never
   relabel Study-level RoB as result-level or assume RoB 2 when another
   standard was used.
5. For each gradeable body, apply the current official GRADE approach that is
   compatible with the Protocol and upstream evidence. Record the starting
   certainty and assess risk of bias, inconsistency, indirectness, imprecision,
   and publication bias independently and transparently.
   For imprecision, state the decision threshold or other patient-important
   basis used; do not reduce the judgement to statistical significance.
6. Consider upgrading only in an officially applicable pathway. Do not
   mechanically offset a downgrade with an upgrade or upgrade evidence already
   starting at high certainty.
7. Treat unavailable information as uncertainty, not automatically as
   `not_serious`. Preserve conflicts and missing evidence as explicit issues.
   Do not encode `not assessed` as a `not_serious` domain judgement. Evidence
   that exists but has no pooled or estimable effect is not automatically
   `no_evidence`; assess the available body when the applicable method permits.
8. Present supported SoF elements: population and setting, comparison, outcome
   and timeframe, comparator baseline effect and its source, intervention
   effect, absolute difference, relative effect where appropriate, confidence
   intervals, Study and participant counts, certainty, and explanations. Use
   explicit not-estimable or not-reported states.
9. Preserve unsupported result forms instead of forcing a binary or continuous
   conversion. Use `sof_effects.py` for a supported derived absolute effect and
   record its calculation inputs in that absolute-effect scenario. A reported
   upstream absolute effect or an unsupported derivation does not require a
   calculation record.
10. Record a method decision when the Protocol is supplemented or deviated
    from. Cite the current official source and explain why the decision was
    necessary. Do not silently change the review question, eligibility,
    upstream results, or synthesis.
11. Explain every certainty judgement and important presentation caveat with
    package provenance.
12. Reconcile the complete structured response against
    `references/grade-agent-output.v4.schema.json` before claiming completion. Backend derives
    final certainty and checks artifact relationships after the response; do
    not duplicate those operations.

The supported scope is direct evidence for Cochrane intervention reviews,
including randomized and non-randomized evidence that the typed package can
express. Do not improvise specialized network-meta-analysis or
diagnostic-test-accuracy GRADE methods; preserve the evidence and return an
explicit unsupported-method issue when those methods are required.

## Completion

Return one JSON object that conforms exactly to
`references/grade-agent-output.v4.schema.json`. The `artifact` member contains method
decisions, evidence profiles, and SoF table drafts. It does not contain
`final_certainty` or row `certainty`; Backend derives those fields from the
recorded level changes. Do not write scientific sidecar files.

Return `completed` only when every selected SoF outcome is accounted for and
the complete draft passes your self-check. Return `blocked` with an explicit
blocker only when the verified Protocol or semantic evidence package cannot
support identification of any main comparison and selected outcome for a
valid SoF. Keep scientific uncertainty
inside profiles, rows, and structured issues; do not confuse it with execution
failure. Missing or unavailable evidence is an honest professional result and
is not, by itself, blocked execution. Missing Reports, unreported results,
unassessed Risk of Bias, no pooling, and empty optional projections remain
local evidence limitations and do not change a completed task to blocked.
This also applies when every selected outcome is honestly represented as
`no_evidence`: a verified Protocol and package can support a completed SoF
artifact without contributing Studies.
