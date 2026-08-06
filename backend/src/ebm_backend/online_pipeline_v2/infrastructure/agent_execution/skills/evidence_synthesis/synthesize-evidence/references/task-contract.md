# Evidence Synthesis task contract

## Inputs

- `evidence-synthesis-protocol.v2` preserves all synthesis-relevant Protocol
  content, including planned questions, effect calculation, synthesis,
  heterogeneity, reporting-bias and Risk-of-Bias plans, and methodology basis.
  It is authoritative for approved choices and constraints. Interpret populated
  structured and narrative content together; do not infer the plan from observed
  effects.
- The referenced completed `study-data-collection-artifact.v3` resolves to one
  frozen unified document. Study identities, Report links, characteristics,
  source result observations, analysis representations, derivations, coverage,
  and unresolved issues remain distinct and visible. It is the only scientific
  source for synthesis data.
- The completed Risk-of-Bias artifact is projected without changing its
  assessment scope, applied standard, judgements, support, provenance, coverage
  rationale, or explicitly unassessed Results. Empty or unavailable local
  coverage is a limitation, not an incomplete Synthesis task.
- `work_id`, when supplied, is bound to the same review, Protocol, and exact
  upstream digests.

## Decisions

The Agent owns synthesis-question interpretation, evidence compatibility,
method selection within Protocol constraints, contribution decisions,
applicability of Risk of Bias, and the scientific interpretation of results.
When the Protocol leaves an execution detail open, consult current applicable
official or primary methodology and record the decision, authority, version,
inspected sections, and rationale. Report a material conflict rather than
silently rewriting the Protocol.

Deterministic code owns retrieval of staged artifacts, scalar and statistical
calculation, schema and relationship validation, provenance checks, digests,
persistence, and projections. Tool availability does not determine the
scientific method, and deterministic code does not silently repair Agent
reasoning or upstream evidence.

## Prohibited Sources And Actions

Web access is limited to current official or primary methodology. Do not use it
to discover scientific evidence, re-read
Studies,
Reports, new result data, retrieve a target review or completed synthesis,
consult benchmark Gold, or replace the frozen upstream set. Do not weight by
Risk of Bias, discard a reported form because the first
method cannot consume it, select a method from observed effects, or perform
unvalidated calculations in model reasoning.

## Output

The only authoritative professional output is
`outputs/synthesis/document.json`, conforming to
`evidence-synthesis-document.v3.schema.json`. It contains:

- the immutable upstream binding;
- consulted authorities and recorded method decisions;
- one typed, source-linked Analysis per planned synthesis question;
- compatibility, Study contributions, Risk-of-Bias references, disposition,
  calculation traces, limitations, and issues.

Each representation must identify its Study, source Result, outcome/timepoint
context, and semantic values. Bind every direct value to the upstream
`representation_id` and `source_value_id`; bind calculated values to a
deterministic trace and named output. Do not encode scientific provenance as a
JSON path. Numeric claims still require matching upstream values or valid
deterministic calculator inputs and outputs.

For `meta-compute`, map each tool input through a trace
`representation_projection` containing `representation_id`, the semantic
`value_name`, and the calculator's declared `input_path`. Calculator input and
output paths belong only to that deterministic tool contract; they are not
Report or scientific-evidence provenance.

The finalizer also writes these deterministic audit/exchange projections:

- `<review_id>-data-rows.csv`
- `<review_id>-subgroup-estimates.csv`
- `<review_id>-overall-estimates-and-settings.csv`

The CSVs do not define or limit the adaptive professional document. Do not
create Backend Markdown or a second scientific report.
