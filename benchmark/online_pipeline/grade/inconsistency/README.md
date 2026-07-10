# GRADE Domain: Inconsistency

This domain evaluates whether an aligned Summary of Findings (SoF) evidence
body should be downgraded for important inconsistency between studies. The
method uses workflow-aligned heterogeneity, study-result, subgroup, and study
characteristic evidence; it does not read gold labels, SoF footnotes, or review
conclusions.

## Dataset

The maintained dataset is `datasets/grade_v4`.

Each instance represents one aligned SoF row. Predictions provide
`judgement.downgraded`, `judgement.severity`, `judgement.levels`, and
`judgement.level_evaluable`.

## Run

```bash
PYTHONPATH=backend/src:. python benchmark/online_pipeline/grade/inconsistency/evaluation/runner.py \
  --dataset benchmark/online_pipeline/grade/inconsistency/datasets/grade_v4/splits/smoke \
  --method method_test \
  --run-id grade_v4_inconsistency_smoke
```

Historical v3 datasets and experiments are local-only under `grade/archive/`.
