# Artifact contract

The checked
`references/systematic-review-agent-output.v3.schema.json` is the authoritative
wire contract. Do not invent another output shape or scientific sidecar file.

The response contains `status`, `artifact`, `issues`, `blocker`, and `warnings`.
A completed response carries `systematic-review-draft.v3`; partial and blocked
responses carry no artifact. Only blocked carries a blocker.

The draft has `document_maturity = scientific_draft`, the evidence or empty
review path, a title, every required section exactly once, reporting method
decisions, and structured issues. Each section has narrative content, optional
subsections, optional upstream artifact identities, and optional provenance.
Locators and source paths are not required fields for completion.

The draft's `displays` are an adaptive presentation plan, not a fixed template.
Each display records a unique id, kind, title, placement, a declared source
file, optional source object identities, and optional caption/rationale. The
renderer formats those unchanged source values; the display plan must not
contain copied scientific cells or model-calculated effects.

Every reporting method decision records `basis_status`. `verified` requires an
actually inspected authority. `llm_fallback` carries no claimed authority and
requires `fallback_model` plus `fallback_note`. `unresolved` cannot appear in a
completed draft. These states concern methodology only and never authorize
remembered or invented scientific evidence.

Use only artifact identities listed in
`review-context/artifact-index.json`. Do not copy the complete upstream
structured results into the draft: cite and explain them. Backend persists the
unchanged evidence files in the Review Data package and checks identities,
digests, schema shape, section completeness, and package integrity. Backend
does not judge prose quality, infer task status from local evidence states, or
repair Agent content.
