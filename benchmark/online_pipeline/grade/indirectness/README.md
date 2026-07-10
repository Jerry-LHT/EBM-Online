# GRADE Domain: Indirectness

This domain evaluates whether the evidence body contributing to an aligned
Summary of Findings (SoF) row should be downgraded for indirectness. The method
compares the review scope, synthesis target, and included evidence without
using SoF footnotes, alignment rationale, or gold labels.

## Dataset

The maintained dataset is `datasets/grade_v4`.

Each instance represents one aligned SoF row. Predictions provide
`judgement.downgraded`, `judgement.severity`, `judgement.levels`, and
`judgement.level_evaluable`.

## Run

```bash
PYTHONPATH=backend/src:. python benchmark/online_pipeline/grade/indirectness/evaluation/runner.py \
  --dataset benchmark/online_pipeline/grade/indirectness/datasets/grade_v4/splits/smoke \
  --method method_llm \
  --run-id grade_v4_indirectness_smoke
```

Historical v3 datasets and experiments are local-only under `grade/archive/`.
