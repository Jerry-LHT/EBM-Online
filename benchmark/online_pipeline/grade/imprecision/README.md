# GRADE Domain: Imprecision

This domain evaluates whether an aligned Summary of Findings (SoF) evidence
body should be downgraded for imprecision. It uses the upstream effect estimate,
confidence interval, information-size evidence, and applicable clinical
threshold evidence; it does not recompute the meta-analysis estimate.

## Dataset

The maintained dataset is `datasets/grade_v4`.

Each instance represents one aligned SoF row. Predictions provide
`judgement.downgraded`, `judgement.severity`, `judgement.levels`, and
`judgement.level_evaluable`.

## Run

```bash
PYTHONPATH=backend/src:. python benchmark/online_pipeline/grade/imprecision/evaluation/runner.py \
  --dataset benchmark/online_pipeline/grade/imprecision/datasets/grade_v4/splits/smoke \
  --method method_llm_web \
  --run-id grade_v4_imprecision_smoke
```

Historical v3 datasets and experiments are local-only under `grade/archive/`.
