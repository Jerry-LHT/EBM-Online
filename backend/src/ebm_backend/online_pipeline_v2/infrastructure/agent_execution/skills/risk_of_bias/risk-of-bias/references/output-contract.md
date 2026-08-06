# Output Contract

Return a JSON object with exactly `status`, `data`, `issues`, and
`execution_summary`.

For `completed` or `partial`, `data` is the authoritative
`risk-of-bias-document.v4` defined by
`references/risk-of-bias-document.v4.schema.json`. Do not invent a second
shape. It contains:

- `binding`: echo the supplied immutable identifiers and digests exactly. Its
  `complete_protocol_digest` identifies the complete Protocol, while
  `study_data_protocol_projection_digest` identifies the narrower Protocol
  projection embedded in Study Data Collection; they are deliberately
  different representations and are not expected to be equal;
- `method_uses`: one record for every applied method/version/variant, including
  the Protocol-planned value, official sources, applicability, open decisions,
  and any material Protocol conflict;
- `targets`: explicit Study×Result targets linked to non-empty
  `study_result_ids`, with complete analytical context and provenance; leave
  this collection empty rather than inventing a target when no applicable
  Result exists;
- `evidence_observations`: concise scientific observations from sources that
  were actually inspected, including read scope and limitations;
- `assessments`: exactly one per target, preserving the method's native
  pre-assessment sections, items, domains, signalling responses, proposed and
  final judgements, overrides, direction, and overall structure as applicable;
- `coverage`: all assessed target ids plus every Included Study or
  Protocol-relevant Result not assessed and the professional rationale. Use a
  null `study_result_id` when the Study has no applicable Result.

The open identifiers and strings adapt to the retrieved method. They are not
permission to omit method-required content or to rename official concepts.
Fields that do not apply remain empty or `null` as allowed by the schema; do
not fabricate placeholders.

Every evidence-bearing item requires provenance. Keep observations concise and
refer to locators instead of embedding source documents. Do not emit keys named
`full_text`, `fulltext`, `raw_full_text`, `document_content`,
`downloaded_document`, or equivalent nested content. Do not include Benchmark
identifiers, Gold data, target-review answers, pooled results, or
completed-review conclusions.

For `blocked`, set `data` to `null` and include at least one error issue. Do not
return a malformed document as a diagnostic. Runtime route/access diagnostics
belong to the Debug Bundle; include an issue only when the underlying evidence
gap materially affects professional coverage or validity.
