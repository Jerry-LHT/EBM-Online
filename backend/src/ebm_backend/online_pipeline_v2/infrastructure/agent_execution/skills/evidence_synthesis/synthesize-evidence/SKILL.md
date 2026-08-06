---
name: synthesize-evidence
description: Synthesize intervention-review evidence from a frozen Protocol, unified Study Data Collection, and Risk-of-Bias artifact. Use for Protocol-planned meta-analysis, other explicit synthesis methods, justified no-pooling, and no-evidence conclusions while consulting current official or primary methodology.
---

# Synthesize Evidence

Complete one professional Evidence Synthesis from the frozen upstream evidence
set. Follow the Protocol, inspect and apply current directly applicable
methodology, make professional compatibility and method decisions, and delegate
all arithmetic and statistical computation to deterministic tools.

Read before working:

- [task contract](references/task-contract.md)
- [calculation capabilities and method decisions](references/methods.md)
- [document, quality gates, and recovery](references/ledger-and-recovery.md)

Use the supplied `find-and-read-methodology` companion Skill to locate, verify,
and actually read execution-bearing official or primary guidance. Record the
authority, version or currency information, inspected sections, applicability,
and resulting decisions in `review_process`. The Protocol remains authoritative:
do not silently replace it when guidance differs, and surface a material
conflict or uncertainty.

The Protocol, Study Data Collection document, and Risk-of-Bias artifact are the
closed scientific evidence set. Web and network access may be used only for
current official or primary methodology. Do not retrieve Reports, new study data, target reviews, completed
syntheses, benchmark Gold, or remembered answers.

## Workflow

1. Inspect the complete Protocol, unified Study Data Collection document,
   Risk-of-Bias evidence, immutable binding, and any checkpoint. Interpret
   structured, narrative, and mixed Protocol content together; no individual
   field is an execution gate.
2. Establish every Protocol-planned synthesis question. Use explicit Synthesis
   PICOs when available and interpret the complete Protocol when they are not.
   Record any execution detail resolved from current methodology. Label an
   evidence-driven departure from the prospective plan as post hoc and explain
   it; never choose a method for a preferred effect.
3. Inspect Study characteristics before results. Map the actual participants,
   interventions, comparators, designs, settings, and follow-up to each planned
   question, then inspect the associated reported results and their analysis
   representations. Preserve source observations and stable Study, Result,
   outcome, timepoint, and representation identities. An exact upstream field
   path is optional audit detail: use it when available, but do not invent one
   or let an unavailable path prevent an otherwise honest synthesis. Do not
   force every result into one data type.
4. Judge clinical, methodological, and statistical compatibility. Record all
   included and excluded Study contributions with reasons. Handle clusters,
   cross-over designs, multiple arms, repeated time points, missing data, units,
   and dependencies according to the Protocol and consulted authority without
   double-counting participants.
5. Use Risk of Bias at its actual assessment scope for interpretation,
   Protocol-specified restrictions, subgroup or sensitivity analysis, and
   limitations. Never alter statistical weights because of a judgement.
   The upstream Risk-of-Bias task is completed before Synthesis starts. Preserve
   its local empty or unassessed coverage as evidence limitations; those local
   states do not become an incomplete Synthesis task.
6. Select the Protocol-consistent method. For every numerical transform,
   arithmetic operation, effect calculation, variance, weight, interval, test,
   or meta-analysis, use the declared deterministic calculation capability.
   Preserve its input, output, engine identity, digests, and semantic
   projection trace unchanged. Exact source paths are optional; numeric values
   still require valid deterministic calculator inputs and outputs.
7. Account for every planned question as meta-analysis, a named other synthesis
   method, justified no-pooling, or no evidence. For non-meta-analysis methods,
   record the method, result, contributions, rationale, and limitations. Do not
   vote count by statistical significance or use an unspecified label such as
   "narrative synthesis".
8. Review heterogeneity, planned subgroup and sensitivity analyses, reporting
   biases, robustness, and limitations where applicable. Validate and finalize
   the authoritative document and its deterministic CSV projections, then
   return only the compact control object.

## Failure Semantics

Retry correctable calculator input errors after inspecting the structured
diagnostic. An unavailable optional capability does not invalidate a legitimate
non-statistical disposition. If the Protocol requires an unsupported numerical
method and no approved deterministic capability can perform it, retain
inspectable work as `incomplete`; never substitute model-generated arithmetic.

Mark `completed` when every identifiable planned question has an inspectable
disposition, including valid no-pooling or no-evidence results. Use `incomplete`
when a concrete safe next action remains. Use `blocked` only when invalid or
contradictory task inputs prevent an honest result. Keep document status equal
to control status.
