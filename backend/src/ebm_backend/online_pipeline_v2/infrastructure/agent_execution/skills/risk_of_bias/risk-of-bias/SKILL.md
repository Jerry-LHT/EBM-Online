---
name: risk-of-bias
description: Assess Protocol-relevant Risk of Bias coverage for Included Studies from a complete Protocol, verified Selection Package, and completed Study Data Collection artifact. Use when one automated Agent must retrieve and apply the Protocol-selected official method, read Study Reports, preserve standard-native assessment structure, and return auditable assessed or explicitly unassessed coverage.
---

# Risk Of Bias

Complete one automated Risk of Bias task. Follow the Protocol and retrieve the
current directly applicable official or primary authority needed to interpret
and apply its planned method. Keep professional target selection, evidence
reading, method interpretation, and judgements in the Agent.

When `find-and-read-reports` is supplied as a companion Skill, use it for
lawful Report discovery and actual reading. It does not choose targets or make
Risk-of-Bias judgements.
When `find-and-read-methodology` is supplied, use it to inspect the complete
execution-bearing method, instrument, conditional paths, algorithms, and
update information needed by this assessment. Keep target selection and all
Risk-of-Bias responses and judgements in this Skill.

Read before working:

- [professional workflow and authority](references/standard-and-reading.md)
- [authoritative document contract](references/output-contract.md)
- [quality, completion, and recovery](references/quality-and-recovery.md)

## Workflow

1. Validate the complete Protocol, immutable `selection-package.v4`, completed
   `study-data-collection-artifact.v3`, and supplied binding. The binding
   separately identifies the complete Protocol digest and the digest of the
   Study Data Collection Protocol projection; Backend has already verified
   that projection lineage. Do not treat those distinct representations as if
   their digests should be equal. Treat Selection's Included Studies and
   Study–Report links as upstream decisions; do not repeat eligibility or
   silently change Study identity.
2. Read the Protocol's Risk of Bias plan and relevant outcome, analysis, and
   data-collection context. Treat a named method, version, and variant as
   binding. Retrieve and inspect the exact official or primary authority needed
   to execute it. Record the authority, version/date, applicability decisions,
   and material conflict without rewriting the Protocol. If the method source
   is inaccessible after reasonable lawful attempts, use `llm_fallback` with
   model and limitation metadata; do not fail a coherent assessment because
   no authority was retrieved.
3. Resolve only choices left open by the Protocol using the consulted authority
   and the actual Study design, intervention assignment, outcome/result, effect
   of interest, and analysis. Do not rely on model memory and do not silently
   substitute another method.
4. Inspect the Study Data Collection document and select Protocol-relevant RoB
   targets. Bind every target to one or more real `study_result_ids`; record the
   outcome, measurement, time point, comparison, effect of interest, analysis,
   provenance, and selection rationale. When an Included Study has no
   method-applicable Result, do not invent a target or Result id. Account for
   that Study explicitly in `coverage.unassessed_results`, using a null
   `study_result_id` and explaining why no assessment applies. Explain other
   relevant Results not selected there as well.
5. Work through Studies and targets in whatever internal order is useful within
   this single Agent execution. Use the companion Skill to find and actually
   read linked or newly discovered Reports, protocols, registries, supplements,
   appendices, corrections, and companion publications. Start from persisted
   upstream Report locators and discovery links rather than repeating resolved
   discovery. Supplement them only when the Risk-of-Bias evidence need remains
   unmet. Record only scientific evidence actually inspected, its read scope,
   limitations, and provenance. Do not treat an upstream abstract-only or
   access-failure observation as current-task reading.
6. Apply the retrieved method in its native structure. Preserve required
   preliminary sections, assessment items, domains, signalling questions,
   response options, algorithms or proposed judgements, permitted overrides,
   judgement levels, direction of bias, and overall rule when applicable. The
   open schema carries those structures; it does not define them.
7. Base every response and judgement on the inspected evidence and authority.
   Do not infer favourable conduct from silence. When information is absent,
   apply the method's own no-information or uncertainty handling and state the
   limitation. A valid uncertainty judgement is still a completed assessment.
8. Review all Study×Target assessments for identifier integrity, internal
   consistency, protocol coverage, and faithful use of the applied method.
   Return only the structured task output required by the supplied schema.

Do not use Benchmark data, Gold, a target systematic review, completed-review
answers, pooled results, runtime diagnostics, or model memory as Study evidence.
Do not contact authors, authenticate, bypass access controls, or return full
text or downloaded documents.

Always leave `human_independent_review_satisfied` to deterministic Backend
provenance. One Agent execution does not satisfy independent human review.

Use `completed` when every Included Study is accounted for and every applicable
selected target has a valid assessment, including method-supported uncertainty
caused by unreported or unavailable information. A completed document may have
zero targets only when no applicable Result exists and explicit unassessed
coverage explains that professional disposition.
Use `partial` only when a material part of the planned target coverage or method
could not be completed but a valid bound document with inspectable work remains.
Use `blocked` only when no valid bound document can be produced, such as an
unusable upstream identity or an irreconcilable Protocol-method conflict
affecting the whole task.
