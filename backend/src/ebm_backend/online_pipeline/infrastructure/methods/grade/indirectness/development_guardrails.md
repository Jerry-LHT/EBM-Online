# Indirectness Method Development Guardrails

This method is intended to model real GRADE indirectness judgement, not recover
benchmark footnotes.

## Allowed development signals

- Official GRADE/Cochrane indirectness principles.
- Aggregate dev-set metrics and aggregate error distributions.
- Method debug summaries grouped by GRADE indirectness domain or signal type.
- Input-quality audits that use only the benchmark method input contract.

## Disallowed development signals

- Case-by-case tuning for a specific review, article, study, outcome row, or
  benchmark instance.
- Rules keyed to review IDs, study IDs, exact article names, or exact outcome
  labels observed in the benchmark.
- Using gold footnotes, SoF comments, source SoF row spans, alignment rationales,
  or test-set error examples to revise prompts or rules.
- Repeated test-set probing during prompt/rule iteration.

## Evaluation discipline

- Use `grade_v3_lite` smoke for interface checks.
- Use `grade_v3_lite` dev for iteration.
- Use `grade_v3_lite` test only for stage-gate evaluation after a dev iteration
  is frozen.
- If test performance is poor, return to aggregate diagnostics rather than
  single-case repair.

## LLM role

The LLM makes the final GRADE indirectness judgement from the allowed normalized
input. It must first produce structured intermediate evidence profiling and
domain directness ratings. Local code validates and normalizes the output but
does not add benchmark-specific downgrade rules or override the medical
judgement.
