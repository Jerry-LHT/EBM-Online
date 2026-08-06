# Review Modes and Recovery

Study Selection performs one complete `single_agent` run. There is no
multi-Agent comparison or reconciler in this task contract.

Keep three states separate: task completion, Report/Study evidence state, and
the review's need for supplementary Evidence Search.

Complete Selection against the entire supplied immutable Search Package even
when one or more upstream Search Runs are partial, failed, or unavailable.
Those source observations describe search coverage; they do not make Records
that were returned unprocessable and do not excuse stopping after coarse
screening.

An inaccessible Report does not automatically make the task partial:

- use `awaiting_classification` when the Study is identified, reasonable
  public checking is complete, and eligibility evidence remains unavailable;
- retain an unresolved conflict when reasonable investigation cannot establish
  Report or Study identity;
- return `completed` when the required investigation and artifact work were
  performed, including these honest evidence limitations;
- return `partial` only when unfinished work or a tool/runtime failure prevented
  required checking from reaching an honest stopping judgement.

Use `search_continuation: proceed` when Selection can hand its Included Studies
to data collection, even if Awaiting or Ongoing Studies remain. Use
`continue_search` only for a material systematic Study-identification gap that
requires a supplementary Search Package and has a new legitimate execution
path or concrete lead. Do not use it merely to restate an inherited incomplete
source run, retry a source with no changed access path, or route ordinary
access failure for a known Report back to Evidence Search. Finish the current
Package before requesting any supplementary round.

Retries start again from the immutable Search Package and create a new
Selection Package. Never overwrite or silently extend a prior package. This
version has no automatic resume or investigator-contact mechanism.
