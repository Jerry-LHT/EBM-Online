# Document Contract

The authoritative Agent artifact is
`study-data-collection-document.v3`. Read the checked Schema at
`references/study-data-collection-document.v3.schema.json` before authoring it.

The fixed shell makes the extraction auditable; the evidence content remains
adaptive:

- `characteristics` contains stable Methods, Population, funding, conflicts,
  and notes fields plus `additional_characteristics` for Protocol- or
  design-specific items;
- shared `arms` and `outcomes` describe the Study once;
- `source_observations` preserve result data as reported;
- `calculations` preserve reproducible transformations;
- `results` keep an Agent-authored collection assessment, source-observation
  links, and zero or more analysis representations;
- `report_coverage`, conflicts, issues, and completion expose gaps honestly.

`report_coverage` records investigation state, not evidence adequacy. Use
`not_started` only when no investigation was performed. Use `unavailable` only
after real attempts failed to find or access usable content, and explain which
ending occurred. Use `inspected` when content was actually read and preserve
its precise `content_scope`; partial or registry access must not be presented
as a complete journal Report. Use `unreported` when an inspected source does
not contain the needed item. Field-level `unreported` and `unavailable` remain
separate from Report access state.

For every requested item, preserve these as two independent observations:

1. **Report access**: the representation actually read and its scope. This is
   recorded in `report_coverage` and may be an abstract, registry record,
   partial Report, complete Report, or an unsuccessful access attempt.
2. **Content reporting**: whether that read representation contains the
   requested characteristic or result. If it does, preserve the reported
   text, category, or number. If it was read and does not contain the item,
   use `unreported`. If the representation needed to answer the item could
   not be obtained, use `unavailable` and retain the access limitation.

Do not infer content reporting from a citation, an outcome title, a source
label, or a planned Protocol outcome. Do not require content to be numeric or
immediately usable by a particular analysis projection; source-faithful
qualitative and categorical findings are valid collected content.

Use one shared arm identity and one shared outcome identity per Study. A Result
target must reference an `outcome_id`. Keep study-wide, arm-level, and
result-specific sample sizes distinct.

Treat source reporting and analysis representation as separate axes. Write a
clear, evidence-specific `collection_assessment.status`, `rationale`, source
Reports, and limitations in professional language; do not choose a status or
reason from an engineering vocabulary. A reported qualitative result,
insufficient numeric reporting, conflicting or unavailable evidence, and a
form outside the current RevMan profile may all have an empty
`analysis_representations` collection without failing extraction.

Use stable semantic identities, not JSON paths, for scientific provenance.
Every numeric value in a RevMan representation is an object containing a
globally unique `value_id`, its `value`, and exactly one `origin`. An observed
origin names an `observation_id`; a calculated origin names a `calculation_id`
and `output_name`. RevMan rows name `arm_id`; Backend resolves the reported arm
label and target outcome only when producing the exchange projection. Never
copy a display label into an identity field.

For a decimal reported by the source, use `kind: decimal` and preserve its
lexical value as a string, such as `0.10`. Use `integer` only for exact integral
source values. Do not round a source value or replace a missing value with zero.

The runtime supplies the structured artifact contract and collects the declared
document. Use an available validation or calculation capability when it helps,
then inspect the document before returning its control status. Backend
revalidates the frozen document and may derive deterministic projections; such
projections contain no additional scientific content or professional decision.
