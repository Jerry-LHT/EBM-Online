---
name: collect-study-data
description: Collect auditable Study Characteristics, protocol-relevant Outcomes, and Study Results from Reports already linked to Included Studies by Study Selection. Use for the complete Study Data Collection task when one Agent must follow the Protocol, inspect current official methodology, read linked Reports, preserve source-form data, reconcile multiple Reports, and create analysis-ready representations without reassessing eligibility or inventing Report–Study links.
---

# Collect Study Data

Complete one automated Study Data Collection task. Follow the Protocol and the
current directly applicable official or primary methodology; do not substitute
a remembered standard. Use `find-and-read-reports` for lawful discovery and
actual reading of Reports already linked by Selection. Use
`find-and-read-methodology` to inspect execution-bearing collection and
calculation authority while keeping extraction and transformation decisions in
this Skill.

Read before working:

- [professional workflow](references/professional-workflow.md)
- [evidence and task boundary](references/evidence-boundary.md)
- [document contract](references/document-contract.md)
- [calculation and quality](references/calculation-and-quality.md)

## Workflow

1. Validate the Protocol, immutable `selection-package.v4`, and binding.
   Treat Selection's Included Studies and Study–Report links as
   authoritative input; do not repeat screening or association decisions.
2. Inspect the Protocol's collection and analysis plans. Retrieve and inspect
   current directly applicable official or primary methodology needed to
   execute them. Record authority, version/date, scope, applied decisions, and
   any material conflict without rewriting the Protocol. If the authority is
   inaccessible after reasonable lawful attempts, use an explicit
   `llm_fallback` basis with model and limitation metadata; do not fail the
   collection because the authority list is empty.
3. Work Study by Study. Classify each linked source before extraction: a
   registry record, abstract, landing page, complete Report, protocol,
   supplement, or other source has a different evidence scope. Read every
   linked source deeply enough for the current data need, including relevant
   text, tables, figures, supplements, corrections, and posted registry
   results. Reuse persisted Report locators, discovery links, and access
   observations as a routing cache, but do not treat them as proof that the
   needed evidence was read. If a registry record or other source does not
   contain the Protocol-required Characteristics or Results, use the companion Skill to
   investigate credible lawful Reports or related sources before concluding
   that a field is unavailable. Do not repeat identity decisions already owned
   by Selection. Choose legitimate sites, representations,
   tools, order, and stopping judgement autonomously.
   For each material Protocol data need, first reuse an adequate known route;
   then seek a more informative representation when the cached route contains
   only metadata, an abstract, a registry record without the needed result, or
   partial content. Do not search again when an already verified accessible
   route answers the need.
   Treat Selection evidence as a routing and identity handoff, not as proof
   that Study Data Collection read the same content. In particular, do not
   inherit `complete registry record` from a Search Record type, Selection
   summary, or cached label. Re-open or otherwise inspect the representation
   needed for this task and record its actual modules and scope.
4. During the same evidence review, collect Study Characteristics and Results
   as distinct data categories. Establish one shared set of Study arms and
   outcomes. Preserve the source's wording, values, units, locations,
   reporting precision, missingness, and uncertainty before transformation.
   Keep two judgements separate for every data need: (a) the Report access
   scope, meaning what representation was actually read (abstract, registry,
   partial or complete Report), and (b) the content reporting state, meaning
   whether that read representation contains the requested item. A Report can
   be inspected while a particular item is not reported; an item cannot be
   called unreported when the representation that could answer it was never
   read. Record qualitative, categorical, and numeric content alike. Do not
   treat an outcome being listed or planned as evidence that its result was
   reported.
5. Collate multiple linked Reports at Study level. Preserve discrepancies and
   revisions; do not silently select, merge, split, or overwrite evidence.
6. Map Results to Protocol-relevant outcomes, comparisons, populations,
   analysis populations, time points, and units of analysis. Keep a Study
   sample size, arm enrollment, result-specific denominator, events,
   withdrawals, and analysed sample distinct.
7. Decide professionally whether a reported value needs transformation and
   what formula is applicable. Use `scripts/data_calculator.py` for every
   authoritative numeric transformation. Bind every calculator input to an
   observation or earlier calculation and retain the complete trace.
8. Create a RevMan representation when the reported or reproducibly derived
   data fit the supplied profile. Otherwise keep the source observations,
   record the professional collection assessment and limitations, and leave
   `analysis_representations` empty. Lack of a projection is not lack of
   extraction.
9. Compare projected magnitudes, directions, denominators, and qualitative
   findings with the Reports. Resolve correctable transcription errors in the
   document and preserve genuine uncertainty or conflict. Before concluding
   that a complete Report contains only qualitative or insufficient numeric
   Results, inspect the relevant Results body, tables, figures, footnotes, and
   supplements. If those parts were not actually read, record the narrower
   read scope instead of claiming a complete Report.
10. Produce the structured Study Data document declared by the runtime and
    inspect it before returning the control result. Use supplied calculation or
    validation capabilities when they help; they support the professional work
    and do not replace it. The control result must truthfully match the
    document and the work actually completed.

Choose an efficient method for the complete Study worklist. Batching, scripts,
structured extraction, shared transformations, and incremental workspace files
may support the Agent's collection work; the Skill does not require one model
interaction per Study or Result. A common transformation is valid when each
input supports it.

Do not generate one templated `unreported` Result per Protocol outcome merely
because no numeric extraction was supplied upstream. Each `unreported` or
`unavailable` conclusion must be grounded in the recorded investigation and
read scope for the material source need. If the run did not investigate that
need, keep the work `not_started` and return `partial`; do not manufacture
completion through repeated rows.

Do not use benchmark data, Gold, a target systematic review, completed-review
answers, pooled results, or model memory as Study evidence. Do not contact
authors, authenticate, bypass access controls, or persist full text.

Always set `human_independent_extraction_satisfied` to `false`. One automated
Agent does not satisfy Cochrane's requirement for independent human outcome
data extraction.

Use `completed` when every Included Study has an inspectable Characteristics
and Results state, and each material evidence gap has received a
case-adapted source investigation. This means the professional investigation
is finished, not that every requested item was found or can be converted to a
preferred analysis form. A complete registry record is not a
complete journal Report, and a registry-only Study cannot be described as
full-text reviewed. Missing, unavailable, unreported, conflicting,
qualitative, and currently unprojectable data remain valid collected states,
not crashes, once the Agent has reached an honest stopping judgement. An
abstract-only upstream observation is not proof that current Report
investigation was attempted. Work the Included Study set in the supplied task
scope. If required work is left undone or execution is interrupted, report
`partial` rather than claiming completion. Use `blocked` only when an invalid
upstream identity or contract makes a valid document impossible.

Apply Report coverage states consistently. `not_started` means required
investigation was not performed and makes the task `partial`. `unavailable`
requires actual attempts and an honest stopping judgement, whether no usable
representation was found or known routes were unreachable. `inspected` means
content was read at the stated scope; abstract, partial Report, complete
Report, and complete registry record are not interchangeable. `unreported`
means the relevant source was read but did not contain the requested item.
Local `unavailable`, partial access, and `unreported` states do not prevent a
completed task after the full worklist was investigated.
