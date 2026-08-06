# Task contract

## Purpose

Assess certainty for each selected body of evidence and build one or more
Summary of Findings tables for the main comparisons of an intervention review.
The unit of GRADE assessment is the outcome-specific body of evidence, not a
Study, Report, forest plot, or review as a whole.

## Decisions owned by this task

- Which Protocol-planned comparisons are main comparisons.
- Which important Protocol-planned outcomes appear in each table, up to seven.
- How synthesis estimates, Risk of Bias, directness, precision, consistency,
  and possible publication bias bear on certainty.
- Whether conditional upgrading domains apply.
- How supported relative and absolute effects are presented.
- Which current official method resolves a detail not specified by the
  Protocol, with an explicit supplemental-method record.

The selection basis for main comparisons and outcomes must be independent of
the observed direction, size, significance, or availability of results.

## Decisions owned upstream

Do not change eligibility, included Studies, extracted observations, Risk of
Bias judgements, synthesis membership, effect estimates, or analysis settings.
Flag conflicts or missing inputs with exact provenance.

The Protocol is the prospective plan and binds explicit choices. The package is
the authoritative record of what upstream tasks actually produced. Current
official methodology resolves applicable gaps. Record rather than conceal a
material deviation from the Protocol.

## Failure and uncertainty

An outcome with no evidence is a valid SoF row with zero Studies and null
certainty. Its `no_evidence` profile records the reason and provenance but no
GRADE domains or certainty fields. Evidence that exists but cannot support a
pooled or numerical estimate is not automatically no evidence; assess the
available body under the applicable method when possible and explain any
not-estimable effect or uncertain domain. Use blocked only when the verified
Protocol or semantic package cannot identify any main comparison and selected
outcome from which a valid table can be produced. A local unavailable,
unreported, unassessed, or not-estimable state is not task failure. A table in
which every selected outcome is `no_evidence` is a valid completed result when
the Protocol and package are verified and every outcome is accounted for.
