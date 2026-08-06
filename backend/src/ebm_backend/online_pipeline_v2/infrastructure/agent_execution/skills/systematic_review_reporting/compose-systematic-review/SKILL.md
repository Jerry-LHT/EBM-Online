---
name: compose-systematic-review
description: Compose a complete scientific systematic-review draft from a verified Protocol and immutable upstream Search, Selection, Study Data, Risk of Bias, Synthesis, and certainty evidence. Use for the final professional reporting stage of an evidence review or an explicit empty review.
---

# Compose Systematic Review

Compose the final scientific Review from the evidence actually supplied. Keep
the scientific evidence set closed. Use current official or primary reporting
and interpretation methodology only to resolve how to report that evidence.

Read [the task contract](references/task-contract.md) before working. Read
[the artifact contract](references/artifact-contract.md) before producing the
response. When `find-and-read-methodology` is supplied, use it to inspect the
current execution-bearing reporting and interpretation guidance needed here.

## Evidence boundary

Read `inputs/task.json`, then
`inputs/artifacts/systematic-review-evidence-package/review-context/reporting-index.json`.
Use its reading roles and display candidates to open the complete semantic
sources needed for the Review. Do not read every raw Search Record or screening
row by default. Open raw audit collections only to resolve a reporting question
that the compact index and semantic downstream documents cannot answer. Treat:

- the Protocol as the prospective scientific plan;
- upstream artifacts as the authoritative record of what was actually done
  and found;
- current reporting authority as guidance for complete, accurate expression.

Do not search for Studies, Reports, external reviews, contextual scientific
literature, a target review, Gold, or completed-review answers. Do not redo or
alter search, eligibility, data collection, Risk of Bias, synthesis, or GRADE.
Use Web and network access only for official or primary methodology.

## Workflow

1. Verify the review path. Read the Protocol, reporting index, artifact index,
   and the complete semantic sources needed for the actual Review. For an
   evidence review these normally include Study Data, Risk of Bias, Synthesis,
   evidence profiles, and Summary of Findings. Use the index summaries for
   Search and Selection unless a specific raw fact is needed. Preserve the
   Protocol and upstream methodology-basis states; do not relabel an inherited
   `llm_fallback` as verified.
2. Inspect the current directly applicable reporting and interpretation
   authority. For each method decision, record `verified` only when the
   execution-bearing source was actually read. If legitimate access fails,
   `llm_fallback` may use existing methodology knowledge only when the model
   identifier and limitation are explicit; do not invent a URL, version,
   section, or authority. `unresolved` cannot support a completed draft. Do
   not copy a branded template or fixed wording. Keep every inherited or new
   fallback visible as a methodology-sufficiency limitation in the draft.
3. Plan the Review's narrative and evidence displays before drafting. Select
   context-appropriate display candidates for the main comparison and important
   outcomes. Bind every display to its declared source file and object
   identities. Use tables where an image adds no information. Do not request an
   empty plot, imply pooling when none occurred, or convert a no-evidence outcome
   into a visual effect estimate. Ensure the Included Study presentation makes
   Methods and the actual Study population, intervention, comparator, outcomes,
   and time points visible; do not reduce Characteristics to design and sample
   size alone.
4. Compose Background and Objectives from supplied evidence only. Reconcile
   planned and conducted methods. Report actual methods in the past
   tense and disclose material deviations or methods that could not be used.
   Never rewrite the Protocol or upstream artifacts.
5. Compose Results from the frozen evidence. Preserve unsuccessful sources,
   awaiting or ongoing Studies, unavailable or unreported data, unassessed
   Risk of Bias, no-pooling, not-estimable effects, and no-evidence outcomes.
   Do not confuse absence of evidence with evidence of no effect.
   Present, when applicable, the Study-selection flow, Included Study
   characteristics, Risk of Bias, individual Study results, synthesis results,
   and Summary of Findings. Prefer the main SoF before Background and place the
   other central displays with Results; appendices may hold supporting detail.
   Relate Risk of Bias visually to the applicable Study and assessed result, but
   do not turn a result-level RoB 2 or ROBINS-I judgement into a whole-Study
   attribute.
6. Compose Discussion around the main findings, applicability, completeness,
   certainty, review-process limitations, and implications for research. If
   the package contains no contextual comparison evidence, state that
   agreement with external studies or reviews was not assessed.
7. Compose Conclusions that reflect effect magnitude, uncertainty, benefits
   and harms without making a healthcare recommendation that requires values,
   resources, feasibility, or other evidence not supplied.
8. Compose References from supplied evidence. Group Study-linked Reports by
   Included, Excluded, Awaiting Classification, and Ongoing status when those
   groups exist; keep methodological references distinct. Then compose the Abstract and
   plain-language summary last. Make their outcomes,
   numerical claims, uncertainty, and overall message consistent with the
   Results, Discussion, Conclusions, and Summary of Findings.
9. Cross-check every outcome, count, effect, interval, certainty judgement, and
   conclusion across narrative, Summary of Findings, and selected displays.
   Check that every required section is present exactly once and every important
   planned outcome is represented, including outcomes with no data. A source
   locator is useful when available but is not required for a valid statement.
10. Validate the complete response against
    `references/systematic-review-agent-output.v3.schema.json`.

For an empty review, report the completed Search and Selection process and the
absence of Included Studies. A selection-flow display remains legitimate. Do
not invent downstream Study Data, Risk of Bias, Synthesis, GRADE, effect, or
certainty results.

## Completion

Return `completed` when the professional reporting process is finished and all
required sections honestly reflect the supplied evidence. Local evidence
limitations do not change a completed task to partial or blocked.

Return `partial` only when required reporting work remains unfinished or the
run was interrupted. Return `blocked` only when the verified input cannot
establish the review question or Selection outcome needed to form any valid
scientific Review. Partial and blocked responses carry no final artifact.

The completed product is a scientific draft, not publication, editorial
approval, registration, human independent review, or a healthcare
recommendation. Do not add authorship, funding, declarations, acknowledgements,
registration, editorial, or AI-disclosure content that was not supplied.
