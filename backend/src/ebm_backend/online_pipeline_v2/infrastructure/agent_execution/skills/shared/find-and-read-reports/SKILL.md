---
name: find-and-read-reports
description: Locate, identify, and inspect lawful public research Reports and related material for Study Selection, Study Characteristics, Study Results, or Risk of Bias. Use as a companion to the active professional task when supplied citations, identifiers, abstracts, files, or locators do not by themselves provide the Report evidence that task needs.
---

# Find And Read Reports

Obtain the best available primary Report evidence needed by the active
professional task. Find and read evidence; leave eligibility, extraction,
reconciliation, calculation, and Risk-of-Bias judgements to the parent Skill.
Success means actually reading content sufficient for the parent's evidence
need, not downloading a PDF or opening any preferred file format.

Use [the examples and evidence distinctions](references/discovery-and-reading.md)
when identity, access, or evidence form is unclear.

## Work autonomously

1. Determine what Report evidence the parent task needs and why. Inspect the
   parent task's persisted upstream Reports, identifiers, locators, discovery
   links, and access observations before searching again. These are a routing
   cache: reuse a previously verified route when it can answer the current
   need, but re-evaluate its current accessibility and evidentiary scope. Do
   not rediscover a Report merely because a different parent task is now
   reading it. Supplied Records, citations, identifiers, files, and locators
   are leads, not a closed evidence collection.
2. Choose any lawful native search, browsing, PDF, file, image, or document
   reading method suited to the case. No source list, site order, identifier
   sequence, request count, or tool route is prescribed.
3. Confirm identity before attributing content. Build an identity packet from
   the available title, authors, journal, year, pages, DOI, PMID, registry ID,
   and Study facts. Use it to distinguish the same Report in another location
   or representation, a companion Report, and a different Study. Preserve
   uncertainty instead of forcing a match.
4. Treat an access response as a property of the current route. A 401/403/429,
   CAPTCHA, Cloudflare or JavaScript challenge, login or purchase page, and
   HTML returned where a PDF was expected are route failures. Do not repeatedly
   retry that route without new evidence. Choose a materially different lawful
   public location or another representation of the Report when it could
   resolve the parent's evidence need. Ordinary public redirects may be
   followed; authentication and access-control bypasses may not. Do not solve,
   evade, or bypass proof-of-work or challenge mechanisms.
5. Search beyond a failed or incomplete locator while a credible lawful path
   could materially resolve the evidence need. For example, if a DOI fails,
   search the identity packet for a public copy, alternate PDF/HTML/XML
   representation, repository or author copy, or relevant companion Report;
   do not merely retry the DOI. Treat metadata claims such as closed access or
   no open-access location as observations about that service, not proof that
   no lawful public copy exists.
6. Validate a candidate before calling it usable evidence. Match its identity
   to the Report and inspect the content itself. HTTP success, a PDF link,
   `application/pdf`, a landing page, a preview, a search snippet, or a
   metadata location does not prove that the complete article was accessible
   or read. HTML, XML/JATS, rendered or scanned pages, tables, figures,
   supplements, registry results, and verified repository or author copies can
   all be usable when they answer the evidence need. When extraction is poor,
   inspect rendered pages, tables, figures, or another representation.
   Describe the actual sections, tables, figures, supplements, registry fields,
   or notices inspected.
   Automation may batch discovery, fetch, parse, and inspect representations.
   Status code, response size, content type, and generic HTML markers are
   useful route observations, but none alone proves reading. The parent task's
   broader claim must be grounded in the actual task-relevant content made
   available for inspection.
7. Before concluding that material evidence is unavailable, reconsider the
   Report identity and search expression, other versions or lawful locations,
   and related materials that could answer the parent task's actual question.
   Explore independent credible leads suited to the case; do not stop merely
   because the supplied locator, publisher page, or one metadata index failed.
8. Check applicable corrections, errata, retractions, expressions of concern,
   and publication or registry updates. Give the evidence to the parent task;
   a notice label is not itself a professional decision.

Work to closure for every Report the parent has advanced for investigation.
For each such Report, either read evidence sufficient for the current need or
reach and record an honest stopping judgement after case-adapted lawful
investigation. Never bulk-convert bibliographic abstracts or unresolved
locators into retrieval failures without actually investigating them. If the
run cannot investigate all advanced Reports, tell the parent that required
work remains unfinished; do not describe that remainder as unavailable.

## Distinguish evidence forms

A citation, database abstract, landing page, or search snippet is not the
full journal article. A complete abstract-only publication is a Report in its
own right, although it may be insufficient. A complete registry record may
answer some questions without becoming the article's full text. A registry
identifier and a publication identifier must remain separately attributable:
do not let a cached registry route stand in for a missing Report route.
Describe the sections, tables, figures, supplements, or registry fields
actually read.

A Search Package's registry `source_data` is a source-returned snapshot, not a
cached claim that the complete registry Report was read. Call a registry
representation complete only after its currently available task-relevant
modules were actually inspected; distinguish protocol/identification modules
from posted-results modules and state which were present. Do not infer
completeness from the Record type or from a Search narrative.

## Hand off honestly

Stop when the parent task has adequate evidence or when case-adapted
exploration of the remaining credible lawful leads is unlikely to resolve the
material gap. An unavailable conclusion must distinguish a failed route, a
partial or abstract-only result, and failure to find a complete public copy;
identify the unresolved evidence need and the materially different leads
explored. It must not rest only on an aggregator's access label or a single
failed route. Use only the parent task's existing artifact to report identity,
locator, read scope, observation or failure, uncertainty, copyright or
licensing uncertainty, and provenance. Do not create a separate access log,
save full text as an output, or conceal incomplete, conflicting, inaccessible,
or unreadable evidence.

Use the parent artifact's existing fields consistently:

- `not_started` means the required Report investigation was not performed. It
  has no access attempts and is unfinished work, not evidence unavailability.
- `unavailable` means real case-adapted investigation reached a stopping
  judgement without accessing usable Report content. Attempts distinguish a
  Report or representation that was not found from a known route that was
  unreachable because of access, network, format, or rendering failure.
- `inspected` means some Report content was actually read. State its real
  scope, such as abstract, partial Report, complete Report, complete registry
  record, table, supplement, or correction. Partial access does not become a
  complete-Report claim.
- `unreported` means sufficiently relevant content was read but the source did
  not report the needed item. It is a data observation, not an access failure.

An interrupted run, exhausted runtime, or unprocessed remainder stays
`not_started`; never relabel it `unavailable`. A complete registry record and
a journal Report remain distinct evidence sources even when both describe the
same Study.

Choose any efficient batch or scripted method for identifiers, locators,
discovery, retrieval, parsing, inspection, and worklist accounting. The Skill
does not prescribe manual processing or one operation per Report. The Agent
remains responsible for checking that any resulting identity, read-scope,
evidence-sufficiency, or unavailability claim is supported by the actual
evidence and routes represented in the parent artifact. A common transformation
is valid when its inputs support the same conclusion; an uninspected remainder
cannot inherit that conclusion merely because it was in the batch.

Use only lawful public resources and caller-supplied lawful files. A public
author copy may be usable when its identity and read scope are verified, but
record uncertainty about copyright or redistribution rights and do not copy
the full text into the task artifact. Do not authenticate, evade access
controls, contact investigators, or use a target systematic review, benchmark
Gold, completed-review answer, or model recollection as Report evidence.

Use the parent task's already persisted discovery and evidence collections for
handoff. A discovery record explains how an additional Report or lawful
representation was found; an evidence observation explains what this task
actually accessed or the real route failure it observed. Those stable
identifiers, locators, source types, and route observations are the reusable
cache across tasks. Do not create a new shared cache or a separate content
cache, copy full text between tasks, or claim that an upstream reading scope
satisfies a different downstream evidence need without checking it.
