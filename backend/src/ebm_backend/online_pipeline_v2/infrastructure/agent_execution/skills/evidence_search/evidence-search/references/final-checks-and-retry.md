# Final Checks and Retry

Before returning:

- cover every Protocol source exactly once and preserve its exact name;
- develop and preserve the actual final strategy for every attempted
  execution, using any supplied Protocol strategy only as an optional baseline;
- ensure each strategy and execution path matches its actual source and
  platform, regardless of which scripts are available;
- preserve Protocol restrictions without adding unjustified restrictions;
- distinguish executed, partial, failed, and unavailable sources;
- ensure unavailable sources contain their planned query or procedure and a
  specific access, prerequisite-evidence, or authorization reason;
- inspect every tool exit and its structured observation;
- explain material strategy development observations and the professional
  stopping judgement in every Search Run narrative;
- ensure each Search Run's retrieved count equals its linked Records and every
  incomplete run has a specific status reason;
- ensure each Record links to a known Search Run and has provenance;
- run the package tool and inspect its manifest, counts, and digests;
- avoid screening, deduplication, Report, Study, and eligibility content;
- surface mapping, terminology, authorization, truncation, and execution
  uncertainty in `issues`.

Judge task status from completion of the required work, not by aggregating
Search Run labels. Use `completed` after every required source or follow-up
procedure was executed or reached an honest stopping judgement and the package
and professional checks were completed. Preserve `partial`, `failed`, and
`unavailable` Search Runs and surface their coverage implications in `issues`.
Use task `partial` only when required work remains unfinished.

For an initial search, use `blocked` when no source produced a usable Search
Run or packaging failed. For a supplementary search, an honestly completed
round with no new usable run is still `completed` when its failed or
unavailable observations can be merged with the valid parent Search Package.
Do not claim that this resolves the recorded evidence gap.

The current task has no in-workspace resume contract. A retry is a new task
execution and Search Package. Never claim that a run resumed or overwrite a
successful source observation with generated content.
