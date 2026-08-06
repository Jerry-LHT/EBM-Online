# Discovery And Reading Examples

## Boundary

This Skill follows up Reports already known or suspected by a parent task. It
does not replace Protocol-planned Evidence Search or rewrite a verified Search
Package.

Persisted upstream Report locators, discovery links, identifiers, source types,
and access observations are the starting routing map for later tasks. Reuse
that map instead of repeating identity discovery, while keeping registry routes
and Report routes distinct. Re-read the actual Report content needed by the
active parent task; an upstream observation is provenance and routing evidence,
not a claim that the current task inspected the same material or that a
registry record supplied a full Report.

## Think in identities, not URLs

Use the evidence available in the case to distinguish:

- another version or location of the same Report;
- a companion Report from the same Study;
- a correction, retraction, expression of concern, protocol, supplement, or
  registry record related to the Report or Study;
- a different Report or Study with similar wording.

Do not force a match when the evidence conflicts or remains ambiguous.

## Adapt to the case

Examples:

- A DOI or publisher locator fails with 401/403/429, a CAPTCHA, a challenge
  page, a login or purchase page, or HTML pretending to be a PDF: classify the
  current route as failed, do not loop on it, and use the identity packet to
  choose another lawful public location or representation.
- A publisher landing page is inaccessible but a separately linked PDF, HTML,
  XML/JATS, repository copy, or author copy is public: inspect that candidate
  and verify that it is the same Report before using it.
- A public author page or scholarly upload is readable but its copyright status
  is unclear: it may support evidence when identity and read scope are verified;
  record the rights uncertainty and do not redistribute or save the full text.
- A DOI fails: search the exact title, authors, PMID or registry identifier,
  and citation links for another lawful public location.
- A journal article is inaccessible: look for an accepted manuscript,
  repository copy, supplement, protocol, registry results, correction, or
  companion Report when it could answer the parent's evidence need.
- A metadata index reports closed access or no public copy: treat that as an
  observation about the index, then use identity and citation evidence to
  decide which other independent discovery paths are credible.
- A PDF is poorly extracted: inspect its rendered pages, tables, figures, or
  another available representation.
- Two sources appear related: compare identifiers and Study facts before
  deciding whether they are versions, companion Reports, or different Studies.
- A URL returns HTTP success or a PDF-looking link: verify the bytes or rendered
  content and inspect enough title, authors, body sections, methods/results,
  tables, figures, or references to justify the stated evidence format.

These examples are neither a checklist nor a required order. Select other
legitimate paths when they fit the evidence better.

## Decide when to stop

Judge retrieval sufficiency against the parent task's evidence need, not
against whether one preferred article URL opened. Continue when another
credible lawful version, location, or related Report could materially answer
that need. Stop when useful evidence is adequate or the remaining credible
paths are unlikely to change the task. When stopping with a gap, state the
missing evidence and summarize the materially different leads explored without
turning the artifact into a search diary.

Do not call a Report unavailable merely because the starting Record contains
only an abstract. An unavailable conclusion follows actual case-adapted
investigation. If workload, runtime, or tool interruption prevents that
investigation, return unfinished work to the parent rather than manufacturing
identical access-failure observations for the uninvestigated remainder.

Distinguish two unavailable endings. `not_found` means no verified usable
representation was located after the recorded investigation; preserve the
search or discovery route that supports that conclusion. `unreachable` means
a candidate representation was located and identity-checked, but lawful access
or reading failed; preserve that locator and the observed failure. Both map to
the parent's `unavailable` coverage state, with their difference retained in
the attempts and reason. Neither applies when investigation never started.

## Characterize what was read

Use precise descriptions such as complete article, complete conference
abstract, Methods and participant flow, Table 2 with footnotes, or specified
registry modules. A metadata service can reveal a location but cannot prove
the content was accessible or read. Expose uncertainty caused by partial
previews, challenge/login pages, poor rendering, OCR, copyright status, or
conflicting versions. Do not turn these examples into a fixed source list,
fallback order, or request-count rule; choose paths according to the evidence
need and the identity packet.
