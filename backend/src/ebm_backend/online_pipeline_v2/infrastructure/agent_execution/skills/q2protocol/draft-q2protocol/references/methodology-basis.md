# Methodology Authority And Constraints

## Profile Identity

The output profile remains `cochrane_intervention_v1`; this fixes the Protocol
artifact structure, not every methodological choice.

Read the optional `standards` object in task input:

- If it is null, act as the methodology expert and select standards appropriate
  to the question, eligible study designs, planned analyses, and current
  official guidance.
- If a field is null or a list is empty, select that unconstrained part.
- If `risk_of_bias_tool` or `certainty_approach` is supplied, use that exact
  value.
- Retrieve and inspect every supplied `methodology_standards` entry and include
  it in `methodology_profile.authorities`; do not silently replace its
  identity, title, version, sections, or URL.
- Apply every `additional_requirements` item unless it conflicts with the fixed
  output schema or makes a scientifically usable Protocol impossible. Report
  such a conflict as an issue.

The caller's Protocol document version and methodology versions are separate
concepts. Evaluation identifiers and exchange schemas have no methodological
authority inside this Skill.

## Unconstrained Selection

Find the current, directly applicable official or primary authority for every
material unconstrained methodology choice. Record only authorities actually
inspected and decisions actually made. If an authority is inaccessible after
reasonable attempts, use model methodology knowledge only as an explicitly
marked `llm_fallback`, with the provider/model and limitation recorded; never
invent a citation. A tool or framework must fit the
eligible study designs, assessment level, intended analysis, and review type;
do not select one merely because it is common or remembered.

Set `methodology_profile.basis_status` to `verified` when the recorded
authorities were inspected, or `llm_fallback` when the model supplied a
provisional method after access failure. In the latter case populate
`fallback_model` and `fallback_note`; leave `authorities` empty unless a real
source was read.

Do not infer that historical completed-review practice is the right standard
for a new Protocol. Prefer current official guidance unless the caller
explicitly constrains a historical version.

## Citation Rules

For each methodology reference return:

- a stable, descriptive standard identifier;
- the official title;
- a non-empty version, year, or revision qualifier;
- the chapters, standards, or tool sections actually used;
- an HTTPS official URL;
- the UTC calendar date on which the source was accessed.

Do not invent a semantic version for a continuously updated page. Use an
official last-updated date when present; otherwise say `Current online revision
accessed YYYY-MM-DD`.

If an official page has moved, follow official redirects and cite the final
official URL. If live guidance conflicts with a caller constraint, retain the
constraint and report the conflict rather than silently changing methods. A
coherent Protocol based on an explicitly recorded LLM fallback may be
`completed` with a warning. An unresolved method choice is `partial` only when
it prevents an executable Protocol; an authority access gap or explicitly
recorded provisional choice alone is not `partial`.

Do not bundle or reproduce full official guidance in the output.

For each material choice, add one `methodology_profile.decisions` record with
its origin and rationale. When the basis is `verified`,
`authority_standards` must identify authorities actually recorded in the
profile. When the basis is `llm_fallback`, keep the applicable supplied or
selected standard identifiers in `authority_standards` without fabricating
authority records; the fallback metadata establishes that those sources were
not verified in this run. Record a material conflict or interpretation gap in
`methodology_profile.unresolved_questions`; return `partial` only when it
leaves the Protocol non-executable. Never rewrite a supplied constraint to
match live guidance.
