# GRADE Indirectness Method

This directory intentionally keeps one primary method:

```text
method_llm.py
```

## Flow

```text
normalized method input
  -> official PICO evidence package
  -> prompt template + official GRADE/Cochrane rubric
  -> LLM GRADE indirectness adjudicator
  -> schema normalization
  -> final judgement + debug
```

The LLM makes the GRADE indirectness judgement from the normalized evidence.
Local code does not override the medical judgement with rule-based critique; it
only packages allowed input, validates the output schema, normalizes labels, and
records debug fields.

The current prompt calibration follows the Cochrane/GRADE distinction between
minor applicability concerns and serious indirectness: a difference in PICO or
context is downgraded only when it is important enough to plausibly change the
anticipated effect for the synthesis target.

The prompt requires domain-by-domain assessment before the final judgement:

- population
- intervention
- comparator
- direct comparison
- outcome
- timepoint
- setting

It also requires two intermediate outputs before the final judgement:

- `evidence_profile`: summarizes what the already-pooled evidence body actually
  covers: population scope, intervention variants, comparator/current-practice
  context, outcome measurement, follow-up, setting/era context, and
  representativeness limits. This is not a second meta-analysis; it is an
  applicability profile used for GRADE indirectness.
- `directness_ratings`: answers the Cochrane-style question "is the evidence
  sufficiently direct for this synthesis target?" for each domain using
  `yes`, `probably_yes`, `probably_no`, `no`, or `unclear`.

Prompt resources live in `prompts/`:

- `system.txt`
- `user_template.txt`
- `output_schema.json`
- `batch_user_template.txt`
- `batch_output_schema.json`

`method_llm.py` supports both single-instance `run(...)` and batch
`run_batch_instances(...)`. Batch mode still judges each item independently; it
only reduces LLM round trips.

## Input Boundary

Allowed input:

- `review_scope_pico`: broad question/review PICO
- `synthesis_target_pico`: row-specific analysis/synthesis PICO
- `sof_display_context`: display and fallback context only
- `evidence_found`: study-level evidence and result rows
- included study IDs
- study characteristics
- study result rows for the current analysis

Forbidden input:

- SoF comments
- SoF footnotes
- source SoF row text/spans
- benchmark alignment rationales
- gold labels
- web search results from the source review/article

The LLM compares `synthesis_target_pico`, interpreted within
`review_scope_pico`, against `evidence_found`. It does not use SoF display
context as a judgement rationale.

## Web And RAG Policy

Web search is not part of this benchmark method. Dynamic RAG is not part of this
method. The GRADE/Cochrane indirectness rubric is included directly in the
prompt.

## Fallback

If no LLM config is available, the method returns `unclear` with a debug
`fallback_reason`. It does not silently use a deterministic downgrade heuristic.

## Development Discipline

See `development_guardrails.md`. Iterate from official guidance and aggregate
dev-set diagnostics only; do not tune to individual benchmark cases.
