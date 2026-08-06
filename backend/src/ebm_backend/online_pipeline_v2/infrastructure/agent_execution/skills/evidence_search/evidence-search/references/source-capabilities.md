# Tools and Source Execution

The Protocol determines which sources and platforms to search. For each source,
choose the best legitimate execution path from provider-native web, browser,
or shell capabilities and the scripts staged for this run. Scripts are
optional capabilities, not preferred or mandatory workflow steps. Never choose
or replace a source merely because a matching script is available.

A provider-native search counts as execution only when the named source was
actually searched and the final query or procedure, platform, execution time,
source count, retrieved Records, and provenance can be preserved. Write those
grounded observations as a `source-result.v2` file below
`outputs/search/source-results/`. Do not represent generic web results as an
execution of PubMed, MEDLINE, CENTRAL, Embase, or a trial register.

Locate a staged script relative to this Skill. In an isolated runtime this can
be done with:

```text
find . -path '*/evidence-search/scripts/<script-name>' -print -quit
```

Run scripts with `python3`. The Agent Runtime resolves it to the Backend's
validated Python environment. Keep all generated material below
`outputs/search/`.

## NLM MeSH lookup

`scripts/mesh_lookup.py` is an optional vocabulary observation capability for
PubMed strategy development. Put one candidate concept per line in a UTF-8
file, then invoke:

```text
python3 <mesh-script> \
  --terms-file outputs/search/queries/mesh-terms.txt \
  --output outputs/search/observations/mesh.json
```

Inspect the returned official descriptor identifiers, headings, and entry
terms. They are observations, not instructions to add every term and not a
substitute for professional concept development.

## PubMed E-utilities

`scripts/pubmed_search.py` is an optional bulk export capability. Use it only
when PubMed is the actual authorized platform and it is the appropriate access
path for the run. Do not use it to claim execution of MEDLINE via Ovid, Embase,
CENTRAL, or another interface.

Write the complete PubMed query to a UTF-8 file, then invoke:

```text
python3 <pubmed-script> \
  --query-file outputs/search/queries/pubmed.txt \
  --narrative-file outputs/search/queries/pubmed-narrative.txt \
  --output outputs/search/source-results/pubmed.json \
  --run-id <unique-run-id> \
  --source-name <exact-Protocol-source-name> \
  --platform PubMed
```

The script reads the contact email and optional NCBI API key from the runtime
environment. It performs POST requests, rate limiting, paging, PubMed article
and book-article XML parsing, source provenance, response digesting, and
bibliographic Record creation. It
also preserves publication types and source-reported correction, retraction,
expression-of-concern, and related-record links. It does not retrieve full
text. Its observation includes PubMed's QueryTranslation and warnings; inspect
them before accepting the query. Treat a nonzero exit as an execution failure.

The default safety ceiling is 10,000 returned Records. If the source reports
more hits and the tool retrieves that ceiling, it records the run as `partial`,
retains the total source count, and reports ceiling truncation. When a paged
export produces fewer parseable Records than the requested target, the tool
records that distinct incomplete-export reason instead of attributing it to
the ceiling. Inspect the observation and do not claim full execution.

## Failed or unavailable sources

Do not attempt a planned source when:

- no compatible or authorized source access exists;
- required prior evidence, such as included Reports for citation searching, is
  not yet available in this invocation; or
- the procedure requires contacting a person or organization and that external
  action was not explicitly authorized.

Preserve its complete planned query or reproducible procedure in a query file
and invoke `scripts/source_status.py`:

```text
python3 <status-script> \
  --query-file outputs/search/queries/<source>.txt \
  --narrative-file outputs/search/queries/<source>-narrative.txt \
  --output outputs/search/source-results/<source>.json \
  --run-id <unique-run-id> \
  --source-name <exact-Protocol-source-name> \
  --platform <actual-platform> \
  --status unavailable \
  --reason <specific-operational-reason>
```

Use `failed` only after a real attempted execution failed. Use `unavailable`
when the source was not executed for one of the reasons above. For an
unavailable run, `executed_at` records when non-execution was observed,
`platform` records the intended platform, and `query` records the planned query
or procedure; none of these fields claims that a search occurred. Do not use a
different database, generic web search, generated citations, or unauthorized
external communication as a silent substitute.

## Build the canonical Agent artifact

After every Protocol source has exactly one `source-result.v2` file, invoke:

```text
python3 <package-script> \
  --sources-dir outputs/search/source-results \
  --output-dir outputs/search
```

This writes the required `manifest.json`, `search-runs.jsonl`, and
`records.jsonl`. Do not edit deterministic source output after packaging.
