# Output Contract

For a non-blocked task, create the structured artifact members declared by the
runtime for this task. The names and transport paths are an interface contract,
not a prescribed professional workflow:

```text
outputs/selection/manifest.json
outputs/selection/record-screening.jsonl
outputs/selection/reports.jsonl
outputs/selection/report-discoveries.jsonl
outputs/selection/record-report-links.jsonl
outputs/selection/report-evidence.jsonl
outputs/selection/studies.jsonl
outputs/selection/study-report-links.jsonl
outputs/selection/study-decisions.jsonl
outputs/selection/conflicts.jsonl
```

Represent empty collections explicitly when the declared artifact shape
requires them. You may use the supplied packaging or validation capability, or
another equivalent method, as long as the collected artifact is structurally
valid and semantically unchanged.

The script validates JSON syntax, rejects full-text fields, writes canonical
JSONL, and computes counts and digests. It does not make professional
decisions. It validates structure against
`references/selection-collections.v2.schema.json`, the checked snapshot of the
Backend Pydantic contract. Treat that Schema as authoritative for field names
and types.

Return only the supplied final JSON Schema:

- `status`: `completed`, `partial`, or `blocked`;
- `data.artifact_schema_version`: `agent-selection-output.v3`;
- `data.execution_summary`: concise execution account;
- `data.methodology_authorities`: every current official or primary authority
  consulted for the Study Selection workflow, each with its title,
  version/publication date, locator, scope, and the principles applied;
- `data.methodology_basis_status`: `verified` when the authority was read, or
  `llm_fallback` when a coherent selection used model methodology knowledge
  after an access failure;
- `data.fallback_model` and `data.fallback_note`: required for
  `llm_fallback`, and the authority list may be empty in that state;
- `data.search_continuation`: whether the review may proceed or whether a
  material systematic Study-identification gap requires supplementary Evidence
  Search, with rationale, evidence gaps, suggested actions, and candidate
  leads;
- `issues`: specific warnings and errors.

Use `data: null` only for `blocked`. Do not inline collections in the final
answer. Every source Record has exactly one screening decision. Duplicate
Records point to a non-duplicate canonical Record and are not screened again. Every
Report has a Record link or discovery link and at least one access observation.
Every Study has exactly one primary Report and one Study-level decision.

Task status records completion of the required professional work, not the
availability of every Report. Return `completed` after all required Selection
activities reach an honest conclusion, including when Reports remain
inaccessible and Studies remain Awaiting classification. Return `partial` only
when required activities remain undone. Warnings, inaccessible Reports,
Awaiting or Ongoing Studies, and investigated conflicts do not mechanically
determine task status.

Use `search_continuation: continue_search` only when systematic Study
identification requires a new Search Package. Seeking another copy of a known
Report is Report investigation; when reasonable legitimate investigation ends
without sufficient evidence, record the access failure and Study follow-up and
use `proceed` unless a separate identification gap exists.

Follow the professional workflow by linking Reports that describe the same
Study. If Report-Study identity remains unresolved, preserve the Report and
record the uncertainty honestly. Do not invent a Study, association, or
conflict merely to satisfy a file shape.

Keep evidence summaries and provenance focused on the information needed to
support and audit the decision. Preserve enough directly reported evidence to
represent the source faithfully; do not copy an entire Report into the
artifact.

## Collection rows

Every row includes non-empty provenance:

```json
[{"source_id":"...","source_type":"...","locator":null,"excerpt":null}]
```

Use these exact fields. Fields marked optional may be omitted or set to null
where stated.

- `record-screening`: required `record_id`, `screening_label`,
  `advances_to_report_assessment`, `provenance`; optional
  `reason`, `duplicate_of_record_id`, `protocol_criteria`.
- `reports`: required `report_id`, `title`, `report_type`, `provenance`;
  optional `citation`, `external_identifiers`, `locators`.
- `report-discoveries`: required `report_id`, `source_id`, `source_type`,
  `rationale`, `provenance`.
- `record-report-links`: required `record_id`, `report_id`, `rationale`,
  `provenance`.
- `report-evidence`: required `observation_id`, `report_id`,
  `locator`, `evidence_format`, `accessed`, `observed_at`, `summary`,
  `provenance`. It records full-text-stage Report retrieval and assessment,
  not title/abstract/citation evidence already present in a Search Record.
- `studies`: required `study_id`, `display_name`, `provenance`.
- `study-report-links`: required `study_id`, `report_id`, `is_primary`,
  `rationale`, `provenance`.
- `study-decisions`: required `study_id`, `classification`,
  `provenance`; optional `reason`, `primary_exclusion_criterion`,
  `follow_up_actions`.
- `conflicts`: required `conflict_id`, `kind`, `target_ids`, `resolved`,
  `description`, `provenance`; optional `resolution`.

## Conditional rules

- For a duplicate Record, set `duplicate_of_record_id` and set progression to
  null. For every non-duplicate Record, omit the duplicate pointer and set
  progression to true or false.
- A Record-level `reason` is optional. Initial title/abstract exclusions need
  accounting and a broad label, not an invented per-Record explanation.
- An excluded Study requires one natural-language
  `primary_exclusion_criterion`. A reason is optional and must not merely
  repeat that criterion.
- An included Study does not require a reason.
- An awaiting-classification or ongoing Study requires a concise reason that
  states the missing eligibility information or evidence of ongoing status.
- Exactly one Study-Report link per Study has `is_primary: true`; explain that
  primary choice in its rationale.
- A resolved conflict requires a resolution. An unresolved conflict omits it.
- Set Report evidence `accessed` to true only when the actual available
  full-text contents of that Report were read. A landing page, citation,
  Search Record, bibliographic-database abstract of a journal article, snippet,
  or failed request is not successful full-text Report access. If the Report
  is itself a conference abstract or another abstract-only publication,
  reading that complete publication is access to that Report, but its limited
  information may still require Awaiting classification. Record a failed
  retrieval attempt with `accessed: false`; its summary must describe the
  observed route failure and the honest stopping basis. The fact that the
  Search Record contains only an abstract is not such an attempt.
  A registry Search Record is also not such an attempt: `source_data` is a
  source snapshot, and `accessed: true` with `complete_registry_record` is
  allowed only after the registry content and the relevant modules were
  actually inspected during Report assessment.

Process descriptions are open professional language. Use any accurate wording,
including `screened`; do not invent or infer a closed vocabulary. Do not add
boilerplate solely to fill optional narrative fields. Only final Study
`classification` is standardized as `included`, `excluded`,
`awaiting_classification`, or `ongoing`.
