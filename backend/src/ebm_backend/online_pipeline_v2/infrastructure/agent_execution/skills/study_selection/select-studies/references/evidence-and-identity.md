# Evidence and Identity

## Record, Report, and Study

- A Record is one source's search result.
- A Report is an information-bearing account of a Study, including an article,
  abstract, registry entry, protocol, results page, or regulatory report.
- A Study is the review-local research unit described by one or more Reports.

Multiple Records may identify one Report. Multiple Reports may describe one
Study. Preserve both relationships with rationale and provenance.

Use registration and sponsor identifiers first when available. Also compare
authors, sites, recruitment dates, sample sizes, baseline characteristics,
interventions, doses, follow-up periods, and study design. Treat conflicting
details as evidence to investigate, not as automatic proof of different
Studies.

## Reading Report evidence

For each sought Report, record:

- the exact locator;
- a natural-language evidence format, such as abstract, HTML, XML, PDF,
  registry, or citation;
- whether evidence was accessed, plus the observation time;
- a concise evidence summary and short provenance excerpt.

These observations belong to the full-text assessment stage. Do not duplicate
the Search Record's title, abstract, citation, or metadata as Report evidence;
keep coarse-screen evidence in the Record decision provenance. A successful
observation means that the Agent read the actual available contents of the
Report. An unsuccessful observation records a real retrieval attempt.

`source_record_type: trial_registry_record` describes the Search source, not
the completeness of the persisted representation. A registry Search Record is
still a lead. Record `accessed: true` at Report assessment only after reading
the actual registry Report content needed for eligibility, and state the
modules or sections inspected. Do not promote a cropped `source_data` snapshot
to a complete registry Report.

The Search Record itself is not a failed retrieval attempt. Do not transform a
batch of abstract-only Records into unsuccessful Report observations unless
each Report was actually investigated. Use upstream locators and discovery
links before performing new discovery. Add a discovery link when investigation
identifies an additional Report or representation; an empty discovery
collection must not conceal skipped discovery.

Do not copy the full document into output artifacts. If one locator fails,
continue investigating when other credible legitimate paths remain. Describe
the observed access problem precisely; do not force it into a closed
vocabulary.

A Report found while following a citation, registry link, correction, protocol,
or companion publication may lack a Search Record. Preserve it with a Report
discovery link. Do not invent a Search Record.

Retraction statements, corrections, errata, and expressions of concern are
Report evidence. Preserve a relevant notice as its own linked Report or as a
Report evidence observation when the notice is part of the inspected Report.
Record what the notice actually says and judge its implications; do not turn
the publication-status label into an automatic eligibility decision.

If a Study is identifiable but eligibility information remains insufficient
after reasonable public checking, use `awaiting_classification`. If Study
identity itself remains unresolved, retain an identity conflict and do not
fabricate a Study.

Keep identity, access, and eligibility as separate judgements. A DOI, PMID,
registry-publication reference, or consistent Study facts can support a
Report-Study association even when the Report cannot be opened. Conversely,
opening a route does not prove Report identity or eligibility. Do not drop a
supported companion Report from an Included Study merely because its route
failed, and do not turn that local failure into an Awaiting classification
when the material eligibility criteria were resolved from other Reports.

Keep Report retrieval follow-up separate from supplementary Evidence Search.
Looking for another legitimate copy or companion Report for an already
identified Study is part of Report investigation. When that investigation
reaches an honest stopping judgement without sufficient evidence, preserve the
failed observations and follow-up actions and continue the review with the
Included Studies. Request supplementary Evidence Search only for a material
gap in systematic Study identification that requires new source Records or a
new Search Package.
