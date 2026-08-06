# Output Contract

For a non-blocked task, create exactly these canonical artifacts:

```text
outputs/search/manifest.json
outputs/search/search-runs.jsonl
outputs/search/records.jsonl
```

`manifest.json` must use `agent-search-output.v1`. Always create it through
`scripts/package_search.py`; do not synthesize its digests or counts.
`references/source-result.v2.schema.json` is the checked snapshot of the
Backend Pydantic contract used by that command. Treat its field names and
types as authoritative; do not guess a nearby shape.

Return only the object required by the supplied JSON Schema:

- `status`: `completed`, `partial`, or `blocked`;
- `data.artifact_schema_version`: `agent-search-output.v1`;
- `data.execution_summary`: concise account of sources executed and limited;
- `issues`: specific professional or operational warnings and errors.

Use `data: null` only for `blocked`. A blocked task need not create canonical
artifacts. Do not inline Search Runs or Records in the final answer; the
runtime collects the declared files before cleaning the workspace.

Task status and Search Run status are separate axes. A `completed` task may
contain warning issues and `partial`, `failed`, or `unavailable` Search Runs
when the Agent completed the required source accounting, stopping judgements,
quality review, and packaging. Those limitations remain visible and must not
be rewritten as successful source execution.

Every Search Run preserves the exact Protocol source name. A succeeded,
partial, or failed run preserves the actual platform and complete final query
or procedure attempted, execution time, status, source count, retrieved count,
search-development narrative, optional status reason, and provenance.
An unavailable run preserves the intended platform, planned query or
procedure, time the non-execution was recorded, zero source and retrieved
counts, a specific reason, and a narrative explaining the handling; it does
not claim execution. Every Record preserves the source record identifier, an
open `source_record_type`, available bibliographic fields, external
identifiers, publication types, source-reported related records or notices,
locators, Search Run link, provenance, and source-native structured fields in
`source_data`. Preserve an `abstract` only when the source explicitly supplies
a bibliographic abstract. Do not generate one. Registry summaries and
descriptions belong in `source_data`, not `abstract`. `retrieved_count` must
equal the Records linked to that Search Run.
Preserve these source observations without deciding whether a Report or Study
is eligible.

A packaged Record is a source-returned search snapshot and lead. It is not
proof that a Report was opened, that a registry entry was read as a complete
Report, or that every source section was returned. Do not describe
`source_data` as complete registry content merely because the source record
type is `trial_registry_record`. Preserve source-returned registry modules,
including posted-results modules when the executed interface returned them;
do not silently crop returned modules and then claim complete content. When an
execution or export representation is intentionally limited, describe that
scope in the Search Run narrative. Report access and task-specific reading are
owned by downstream professional tasks.

Do not return Reports, Studies, duplicate groups, screening decisions,
eligibility decisions, or completed-review facts.
