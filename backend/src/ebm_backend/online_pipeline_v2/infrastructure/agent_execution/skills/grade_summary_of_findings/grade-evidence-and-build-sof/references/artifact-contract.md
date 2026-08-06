# Artifact contract

The staged `references/grade-agent-output.v4.schema.json` is the checked
authoritative schema for field names,
nullability, enums, and object shape. Do not create a second JSON contract.

The response has `status`, `artifact`, `issues`, `blocker`, and `warnings`.
`completed` carries a complete artifact draft. `blocked` carries no artifact
and names the blocker.

The `grade-sof-draft.v4` draft records method decisions, one evidence profile
per selected comparison-outcome-timeframe body, and one to seven rows per
Summary of Findings table. Every profile occurs in exactly one row.

A `graded` profile records the Synthesis Analysis ids defining the body,
starting certainty, all five downgrade domains, the three conditional upgrade
domains, explanations, and issues. It does not write final certainty; Backend
derives it from the recorded levels.

A `no_evidence` profile records only its evidence-body id, status, explanation,
provenance, and issues. It has no Analysis ids, initial or final certainty,
domains, or upgrades. Its SoF row has zero Studies, no participant count, and
no relative or absolute effect. Do not use `not_serious` domain records as
placeholders for `not assessed`.

Each absolute-effect scenario identifies the comparator effect, intervention
effect, absolute difference, and baseline-risk basis. An effect is estimated,
not estimable, or not reported. An estimated effect without a confidence
interval states why the interval is unavailable. When values were derived with
the supported calculator, record its inputs; omit that record for an upstream-
reported value or unsupported derivation.

Use structured issues for evidence limitations and uncertainty. Backend checks
shape, referenced Synthesis Analysis identities, count types, calculation
arithmetic, integrity, and stable GRADE invariants. It does not infer an SoF
subgroup count from an Analysis-level total, rewrite the artifact, or judge the
professional reasoning. A missing optional projection,
source path, Report, result, or RoB assessment is not a structural failure.
