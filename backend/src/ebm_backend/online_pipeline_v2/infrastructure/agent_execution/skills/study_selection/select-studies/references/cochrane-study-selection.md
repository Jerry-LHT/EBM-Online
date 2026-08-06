# Cochrane Study Selection

Before execution, consult the current directly applicable official or primary
methodology authority for Study Selection. For an intervention review this
normally includes the current Cochrane guidance on searching and selecting
studies; verify the current version and applicable section at runtime rather
than treating this reference as a frozen internal standard:

https://www.cochrane.org/authors/handbooks-and-manuals/handbook/current/chapter-04

Record the authority, version or publication date, locator, scope, and applied
principles in `methodology_authorities`. The authority governs the professional
method and evidence threshold. The supplied Protocol governs the review's
eligibility criteria and must not be silently rewritten.

Follow its boundary:

1. Merge source results and identify duplicate Records of the same Report.
2. Screen non-duplicate titles and abstracts over-inclusively: exclude only
   obviously irrelevant Records; advance plausible, unclear, or insufficiently
   described Records.
3. Retrieve and examine the full text of potentially eligible Reports when
   possible; use an adequate complete registry record where that is the
   relevant source.
4. Link multiple Reports of the same Study.
5. Determine eligibility from full-report evidence at Study level when
   possible. If eligibility information remains incomplete or unobtainable
   after appropriate investigation, record the Study as Awaiting
   classification rather than forcing inclusion or exclusion.
6. Record Included, Excluded, Awaiting classification, and Ongoing Studies,
   then proceed to data collection for the Included Studies. Awaiting and
   Ongoing Studies remain visible for follow-up and review updates.

MECIR C39 requires at least two independent people for final inclusion
decisions. One or more automated Agent runs are not people and do not satisfy
that requirement. Never claim otherwise.

MECIR C40 prohibits excluding an eligible Study merely because outcome data
are unavailable or unusable. Under this product contract, outcomes of interest
are not eligibility criteria, so do not exclude a Study because an outcome was
not reported, was unusable, or appears not to have been measured. MECIR C41
requires enough decision accounting for a flow diagram and excluded-studies
table. Initial obvious exclusions need Record-level audit, but must not be
turned into Excluded Studies. MECIR C42 requires multiple Reports of one Study
to be collated without discarding secondary Reports.

MECIR C48 requires relevant retraction statements and errata to be examined.
Before final eligibility classification, check relevant Reports for
retractions, corrections, errata, and expressions of concern, preserve the
evidence and provenance, and consider the implications for the Study. A notice
does not create a deterministic exclusion rule.

The two-stage boundary is explicit: title/abstract screening is a coarse,
Record-level relevance decision; full-report assessment is the fine,
Study-level eligibility decision. This Skill operationalizes that boundary
for an automated Agent, but does not claim to replace the human independent
reviewer requirement in MECIR C39.

For plausible Excluded Studies, record one explicit primary reason tied to the
Protocol. Keep that list focused; do not create Excluded Studies for every
obviously irrelevant Record.
