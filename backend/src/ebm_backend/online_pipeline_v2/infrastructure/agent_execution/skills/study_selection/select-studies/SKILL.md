---
name: select-studies
description: Perform Cochrane-aligned Study Selection from an approved Protocol and verified Evidence Search Package. Use when Codex or Claude must deduplicate source Records, screen titles and abstracts, independently discover and inspect potentially relevant Reports through legitimate evidence, collate multiple Reports into Studies, classify Studies, and create auditable structured selection artifacts.
---

# Select Studies

Read the task input, including the typed Study Selection Protocol view, the
verified Search Package under
`inputs/artifacts/search-package/`, and every linked reference before acting:

- [Cochrane workflow](references/cochrane-study-selection.md)
- [Evidence and identity](references/evidence-and-identity.md)
- [Output contract](references/output-contract.md)
- [Review modes and recovery](references/review-modes-and-recovery.md)

When `find-and-read-reports` is supplied as a companion Skill, use it for
Report discovery and reading and keep eligibility decisions in this Skill.
When `find-and-read-methodology` is supplied, use it to inspect
execution-bearing selection authority and keep screening, Study collation,
and eligibility decisions in this Skill.

## Authority and decision hierarchy

Before screening, identify and inspect the current directly applicable
official or primary methodology authority for Study Selection. Record the
authority, version or publication date, locator, scope, and principles applied
in `methodology_authorities`. The authority defines how the professional
workflow is performed and what evidence is sufficient; it does not replace or
rewrite the Protocol. If the authority cannot be read after reasonable lawful
attempts, complete the selection with `methodology_basis_status` set to
`llm_fallback`, record the model and limitation, and leave the authority list
empty. An access limitation is not a Selection failure.

The Protocol is authoritative for this review's eligibility criteria. Apply
its study-design, population, intervention, comparator, setting, language,
publication-status, and time restrictions exactly as supplied. Do not invent
new criteria from outcomes, search results, downstream analysis needs, or
remembered reviews.

At coarse Record screening, exclude only an obviously irrelevant Record.
Advance a Record when it is plausible, unclear, or missing enough information
to decide a material Protocol criterion. A lack of proof in a title, abstract,
or registry title is uncertainty, not evidence of ineligibility. Make final
inclusion or exclusion decisions only at Study level after sufficient Report
evidence has been inspected.

## Complete the task

1. Read the task input and complete the professional Selection work in the
   supplied task scope.
   Treat every Search Run status as an immutable upstream observation, not as
   the completion status of Selection. A `partial`, `failed`, or `unavailable`
   source does not authorize stopping after Record screening or leaving the
   supplied Records unprocessed.
2. Merge the source results conceptually and identify duplicate Records of the
   same Report. Preserve every Record and keep uncertain matches separate.
3. Examine non-duplicate titles and abstracts over-inclusively. Advance
   plausible and unclear Reports; remove only obviously irrelevant Records.
   Do not turn a coarse-screen exclusion into an Excluded Study.
4. Use the companion Skill to discover and examine each potentially relevant
   Report. Treat the Search Package as the immutable starting record of what
   Evidence Search found, not as a closed evidence collection. Build an
   explicit worklist from every non-duplicate Record advanced from coarse
   screening and close every item by actual Report reading or an honest
   stopping judgement. A bibliographic abstract is a lead, not evidence that
   full Report investigation was attempted. A registry Search Record and its
   `source_data` are likewise a source snapshot, not proof that a complete
   registry Report was read. Do not bulk-mark the
   uninvestigated remainder as not retrieved. Persist each identity-checked
   locator and actual access observation in `report-evidence`, including failed
   routes and the real read scope, so later tasks can reuse the route without
   treating it as proof of broader reading.
5. Link multiple Reports of the same Study without discarding secondary
   Reports. Use identifiers and study characteristics, not title similarity
   alone. Preserve the discovery chain for Reports found during checking.
   Resolve Report identity and Study association independently of access:
   inaccessible, abstract-only, and secondary Reports may still be linked when
   identifiers and Study facts support the association. Follow explicit
   registry-publication references, PMIDs, DOIs, registration identifiers,
   and related-record metadata even when the referenced Report later proves
   inaccessible. Never require a successful full-text route before creating a
   supported Study-Report link.
   When Report-Study identity cannot be determined, record that uncertainty
   explicitly rather than inventing an association.
6. Check relevant Reports for retraction statements, corrections, errata, and
   expressions of concern before making a final eligibility decision. Preserve
   a notice as a linked Report or Report evidence observation with its locator,
   content summary, and provenance. Judge its implications professionally; do
   not infer an eligibility decision from a notice label alone.
7. Apply every material Protocol eligibility criterion to the Study using all
   available full-text Reports. Classify the Study as `included`, `excluded`,
   `awaiting_classification`, or `ongoing`.
   Report access is evidence availability, not an eligibility criterion.
   Never infer inclusion from a successful request or exclusion from a failed
   request. A related inaccessible Report also does not make an otherwise
   sufficiently assessed Study Awaiting classification; use Awaiting only when
   missing evidence prevents a material eligibility decision.
8. Keep insufficient or unobtainable eligibility information explicit. Use
   `awaiting_classification` rather than forcing a decision; use `ongoing`
   when adequate evidence establishes that status. Lack of usable results is
   never itself an exclusion. Once reasonable Report investigation is
   complete, unavailable evidence is a Study state and access observation,
   not unfinished task execution.
9. Record identity uncertainty as a conflict rather than fabricating a Study.
10. Complete the professional review below and produce the structured artifact
    declared by the runtime. Use any supplied validation or packaging
    capability when useful; it is an artifact aid, not a professional decision
    procedure.

Choose an efficient execution method for the size and shape of the work.
Batching, scripts, structured parsing, identifier matching, keyword-assisted
triage, and incremental workspace files may organize and support the work
within this single Agent execution. They do not need to imitate manual
keystrokes or produce one model interaction per Record. Apply the Protocol and
the same professional quality gates across the complete worklist.

Mechanical observations may contribute evidence but are not sufficient by
themselves for a broader claim. For example, keywords alone do not establish
eligibility or Study identity, and HTTP status, response length, content type,
or a generic HTML marker alone does not establish that task-relevant Report
content was read. The Agent may use any of these signals in its method, but
must ground final identity, association, eligibility, read-scope, and stopping
judgements in the evidence represented by the artifact.

Set `search_continuation` to `continue_search` only when systematic Study
identification remains materially incomplete and a supplementary Evidence
Search must create a new Search Package. Explain the identification gap and
provide concrete `candidate_leads` when available. Do not use supplementary
Evidence Search merely to seek another copy of an already identified Report.
Do not request supplementary Search merely to restate or retry an inherited
failed, partial, or unavailable Search Run when no new legitimate execution
path or Study-identification lead exists. First complete Selection for the
entire current immutable Search Package. A concrete follow-up that becomes
executable during Selection, such as citation searching from an inspected
Report, may support `continue_search` after that current-package work is
complete.
After reasonable legitimate Report investigation ends without sufficient
access, retain the Study as `awaiting_classification`, record its follow-up,
and set `search_continuation` to `proceed` unless a separate Study-identification
gap exists. Selection does not create a second Search Package itself.

## Review before finalizing

- Account for every source Record and every potentially relevant Report.
- Confirm that upstream source limitations did not cause current-package work
  to stop after deduplication or title-and-abstract screening.
- Confirm that every Report sought in the full-text stage has either actually
  been read or has an honest retrieval-failure observation describing a real
  attempt and why further credible lawful paths were unlikely to resolve the
  eligibility need.
- Keep title, abstract, and citation evidence used for coarse screening in the
  Record decision provenance. Do not present it as full-text Report access.
- Base every Included or Excluded decision on sufficient actually read Report
  evidence for all material eligibility criteria. Preserve unresolved cases
  as Awaiting classification.
- Confirm that no Search Record snapshot was relabelled as a complete registry
  Report without actually reading the registry content and naming the modules
  inspected.
- Confirm that route success or failure did not determine eligibility or
  prevent a supported Report-Study association.
- Confirm that relevant retraction statements, corrections, errata, and
  expressions of concern were checked and their implications considered.
- Confirm that Reports describing the same Study are linked and that any
  unresolved Report-Study identity is represented honestly.
- Check that Record-Report-Study links, primary and secondary Reports,
  classifications, conflicts, and flow counts tell one consistent story.

Follow the collection rows and conditional rules in the output contract
exactly. Do not fabricate a narrative reason when the contract makes it
optional; do provide the specific explanation when a conditional rule
requires it.

## Protect evidence integrity

Treat the Study Selection Protocol view as authoritative for the review
question, objectives, eligibility criteria, and any non-empty setting,
language, publication-status, or time restrictions. An empty restriction
collection means that no restriction of that kind applies. Outcomes of
interest are not Study Selection eligibility criteria in this contract.
Do not infer an outcome-based eligibility rule from the review question,
objectives, Reports, or downstream analysis needs.
Do not use benchmark data, Gold, a target review, or a completed review's
included/excluded list as an answer source.
Do not exclude an eligible Study because an outcome was unreported, unusable,
not extractable, apparently unmeasured, or unavailable for synthesis.
Do not contact investigators or send external messages. Record missing
information and suggested follow-up instead.

Return `completed` when every required Selection activity was performed:
account for the source Records; investigate each potentially relevant Report
until it was read or an honest stopping judgement was reached; and preserve
every supported Study decision, awaiting state, ongoing state, or investigated
identity uncertainty. A paywall, 403 response, unavailable Report, warning,
`awaiting_classification` Study, or unresolved evidence state does not by
itself make the task `partial`.

Return `partial` only when required professional work remains undone, such as
unprocessed Records, Report investigation that was not performed, or a tool or
runtime failure that prevented the required investigation from reaching an
honest stopping judgement. Return `blocked` with `data: null` when no valid
selection artifact can be produced. Never infer task status mechanically from
the number of inaccessible Reports, Awaiting Studies, warnings, or conflicts.
