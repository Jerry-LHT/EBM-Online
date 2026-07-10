# Meta-analysis Subtask 2: Study Result Extraction

This benchmark converts a dataset instance into the backend workflow contract,
calls the Subtask 2 method, and evaluates `StudyResultRow.result_items[]`.
Backend runtime code does not depend on benchmark datasets or evaluation code.

## Current Method

The single public method is:

```text
method_source_local_candidate_extraction
```

Its implementation is under:

```text
backend/src/ebm_backend/online_pipeline/infrastructure/methods/meta_analysis/
  subtask2_study_results/source_local_candidate_extraction/
```

Historical methods and experiments are local-only under `archive/`. They are
not runtime dependencies and are excluded from version control.

## Contract

The benchmark supplies the backend method with:

- the review analysis setting;
- one study/article extraction task;
- optional non-numeric extraction hints;
- linked article text and raw table XML.

The method returns `StudyResultRow[]`. Each row contains one `result_items[]`
list. A result item preserves an article-local candidate setting and contains
all currently supported numeric fields in `result_data`. A broad review setting
may legitimately produce multiple `possible` result items.

The method must not read benchmark gold, benchmark row indexes, or evaluation
artifacts.

## Datasets

Primary development dataset:

```text
datasets/cochrane_meta_v2-key-filter
```

Committed regression subsets:

- `datasets/cochrane_meta_v2-key-filter-dev4/splits/dev4`: four representative
  prompt and pipeline regression cases.
- `datasets/cochrane_meta_v2-key-filter-test78/splits/test78`: 78 audited,
  article-supported evaluation instances containing 83 gold study rows.

The test78 directory includes its curated source-support audit and audit-clean
manifest; historical predictions used during review remain in local archive.

Both subsets use a relative `shared` link to the primary key-filter dataset, so
they remain portable across repository checkouts.

Temporary subsets, run outputs, prompts, traces, and rerun artifacts belong in
this module's ignored `archive/` directory.

## Running

Run the fast regression split:

```bash
PYTHONPATH=backend/src:. python benchmark/online_pipeline/meta_analysis/subtask2_study_results/evaluation/runner.py \
  --dataset benchmark/online_pipeline/meta_analysis/subtask2_study_results/datasets/cochrane_meta_v2-key-filter-dev4/splits/dev4 \
  --method method_source_local_candidate_extraction \
  --run-id source_local_dev4 \
  --hint-policy full
```

Run the audited test split with timeout/resume orchestration:

```bash
PYTHONPATH=backend/src:. python benchmark/online_pipeline/meta_analysis/subtask2_study_results/evaluation/run_instances_with_timeout.py \
  --dataset benchmark/online_pipeline/meta_analysis/subtask2_study_results/datasets/cochrane_meta_v2-key-filter-test78/splits/test78 \
  --method method_source_local_candidate_extraction \
  --run-id source_local_test78 \
  --timeout-seconds 1800 \
  --workers 2 \
  --hint-policy full \
  --progress \
  --resume
```

## Primary Metrics

The primary metrics evaluate one predicted result item at a time. They never
combine fields from different candidates:

- `candidate_item_complete_recall`: proportion of gold items for which one
  predicted item contains every required numeric field.
- `candidate_item_any_value_recall`: proportion of gold items for which one
  predicted item matches at least one required numeric field.
- `candidate_item_field_coverage`: mean fraction of required fields matched by
  the single best predicted item for each gold item.

Per-field, denominator-only, value-only, candidate-count, status, and audit
subset metrics are diagnostics. In particular, legacy per-field recall may
aggregate observations across candidates and must not be reported as item-level
completion.

## Maintained Utilities

- `datasets/builders/build_supported_test_subset.py`
- `datasets/builders/build_audited_test_subset.py`
- `evaluation/metrics.py`
- `evaluation/runner.py`
- `evaluation/run_instances_with_timeout.py`
