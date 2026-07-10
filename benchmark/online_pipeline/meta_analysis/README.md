# Meta Analysis Benchmark

本 benchmark 对齐 `docs/workflow_v3.md` 中的 Module 6：Meta Analysis。

当前不物化 package-level meta-analysis benchmark output，而是把 Module 6 拆成四个独立 subtask benchmark unit：

- `subtask2_study_results`：基于文章的 study-level result data extraction
- `subtask3_analysis_methods`：analysis method / model decision
- `subtask4_subgroup_analysis`：subgroup estimates 和 subgroup-difference tests
- `subtask5_overall_estimates`：overall pooled estimates

模块级 builder 仍从同一套冻结 raw/intermediate data 构建四个 subtasks，确保它们的 source material 一致。

## 1. 数据来源

v2 source 冻结在：

```text
benchmark/online_pipeline/raw_data/meta_analysis/
```

核心文件：

- `source/official_analysis_csv_snapshot/`：官方 Cochrane analysis CSV snapshot
- `intermediate/analysis_family_sources.jsonl`：每个 `review_id + Analysis group + Analysis number` 对应一个 source bundle
- `intermediate/analysis_settings.jsonl`：workflow-shaped analysis settings
- `intermediate/study_result_rows.jsonl`：官方 join 后的 study result rows
- `intermediate/analysis_methods.jsonl`：官方 method/model rows
- `intermediate/overall_estimates.jsonl`：官方 overall pooled estimates
- `intermediate/subgroup_results.jsonl`：官方 subgroup estimates 和 subgroup-difference tests

LLM setting cleaning 只负责结构化 comparison、outcome 和 timepoint。Gold numeric result data、method fields、overall estimates、subgroup estimates 和 subgroup-difference tests 都来自官方 CSV。

Study result rows 使用 canonical source-row assignment：如果同一条官方 `data-rows.csv` 记录带有 subgroup label，
并且 `Applicability=SUBGROUP_AND_OVERALL` 会同时归入 subgroup 和 overall，则 builder 优先保留 subgroup
assignment，不再额外生成重复的 overall study-result row。官方 overall pooled estimate 仍保留在 subtask5；
但 study-level row 不再同时作为 overall 和 subgroup 的输入。

Setting cleaning 使用 `comparison_v2` cache。Comparison cache identity 覆盖 LLM 实际看到的 comparison candidate 输入：
`candidate_id`、`review_id`、`analysis_group`、`analysis_number`、`analysis_name`、`analysis_group_name` 和 `explicit_labels`。
旧版 `comparison::...` cache 不再被 builder 接受。Meta Analysis 主构建默认只读取
`raw_data/meta_analysis/intermediate/setting_cleaned.jsonl`；GRADE/shared analysis-setting artifacts 只能显式传入，
不能作为 Meta 主构建的默认来源。

## 2. Dataset 结构

每个 subtask 拥有自己的 `datasets`、`evaluation` 和 `runs`：

```text
benchmark/online_pipeline/meta_analysis/subtask2_study_results/
  datasets/cochrane_meta_v2-key-filter/
  evaluation/runner.py
  runs/

benchmark/online_pipeline/meta_analysis/subtask3_analysis_methods/
  datasets/cochrane_meta_v2/
  evaluation/runner.py
  runs/

benchmark/online_pipeline/meta_analysis/subtask4_subgroup_analysis/
  datasets/cochrane_meta_v2/
  evaluation/runner.py
  runs/

benchmark/online_pipeline/meta_analysis/subtask5_overall_estimates/
  datasets/cochrane_meta_v2/
  evaluation/runner.py
  runs/
```

Subtask 2 带有自己的 article layer：

```text
subtask2_study_results/datasets/cochrane_meta_v2-key-filter/shared/article_index.jsonl
subtask2_study_results/datasets/cochrane_meta_v2-key-filter/shared/articles/*.json
```

当前不生成 module-level `meta_analysis/datasets/<dataset_name>/`。builder 只写入可运行的 subtask datasets，并返回 `dataset_dirs` 映射。

## 3. 子任务文档

每个 subtask 的数据契约、指标和运行示例由各自目录维护。

<table>
  <thead>
    <tr>
      <th>Subtask</th>
      <th>任务</th>
      <th>All</th>
      <th>Smoke</th>
      <th>Dev</th>
      <th>Test</th>
      <th>Gold 输出</th>
      <th>Schema</th>
      <th>文档</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>subtask2_study_results</code></td>
      <td>study-level result data extraction</td>
      <td>1041</td>
      <td>5</td>
      <td>451</td>
      <td>590</td>
      <td><code>study_result_rows</code></td>
      <td><a href="subtask2_study_results/datasets/cochrane_meta_v2-key-filter/schema.md">schema.md</a></td>
      <td><a href="subtask2_study_results/README.md">README.md</a></td>
    </tr>
    <tr>
      <td><code>subtask3_analysis_methods</code></td>
      <td>analysis method / model decision</td>
      <td>5308</td>
      <td>5</td>
      <td>2638</td>
      <td>2670</td>
      <td><code>analysis_methods</code></td>
      <td><a href="subtask3_analysis_methods/datasets/cochrane_meta_v2/schema.md">schema.md</a></td>
      <td><a href="subtask3_analysis_methods/README.md">README.md</a></td>
    </tr>
    <tr>
      <td><code>subtask4_subgroup_analysis</code></td>
      <td>subgroup estimates 和 subgroup-difference tests</td>
      <td>3447</td>
      <td>63</td>
      <td>1782</td>
      <td>1665</td>
      <td><code>subgroup_results</code></td>
      <td><a href="subtask4_subgroup_analysis/datasets/cochrane_meta_v2/schema.md">schema.md</a></td>
      <td><a href="subtask4_subgroup_analysis/README.md">README.md</a></td>
    </tr>
    <tr>
      <td><code>subtask5_overall_estimates</code></td>
      <td>overall pooled estimates</td>
      <td>751</td>
      <td>5</td>
      <td>364</td>
      <td>387</td>
      <td><code>overall_estimates</code></td>
      <td><a href="subtask5_overall_estimates/datasets/cochrane_meta_v2/schema.md">schema.md</a></td>
      <td><a href="subtask5_overall_estimates/README.md">README.md</a></td>
    </tr>
  </tbody>
</table>

`cochrane_meta_v2-key-filter` 复用同一版本构建逻辑；仅 Subtask 2 额外要求 gold key values
能在当前 article inputs 中直接出现。重建后 Subtask 2 key-filter 分布为 All 1041 / Smoke 5 /
Dev 451 / Test 590。

Subtask 2 当前提交和维护 `cochrane_meta_v2-key-filter`，以及其稳定的
`cochrane_meta_v2-key-filter-dev4` 和 `cochrane_meta_v2-key-filter-test78`
回归集。pairwise comparison/candidate-filter 变体仅用于本地定向审计，按需重建，
不作为当前提交的数据集。

## 4. 构建

```bash
PYTHONPATH=backend/src:. python benchmark/online_pipeline/meta_analysis/setting_cleaning/cleaner.py full \
  --workers 16 \
  --llm-config llm.local.json

PYTHONPATH=backend/src:. python benchmark/online_pipeline/meta_analysis/setting_cleaning/cleaner.py audit

PYTHONPATH=backend/src:. python benchmark/online_pipeline/benchmark.py build \
  --module meta_analysis \
  --source cochrane_meta_v2 \
  --dataset-name cochrane_meta_v2

PYTHONPATH=backend/src:. python benchmark/online_pipeline/benchmark.py build \
  --module meta_analysis \
  --source cochrane_meta_v2 \
  --dataset-name cochrane_meta_v2-key-filter
```

`cochrane_meta_v2` 是当前 Meta 上游 source 版本，要求 `setting_cleaned.jsonl`
通过 `setting_cleaning_v2` / `comparison_v2` / source hash 校验。Subtask 2 的默认开发数据集是
`cochrane_meta_v2-key-filter`；其旧 `cochrane_meta_v1` dataset 仅保留在本地 archive。

## 5. 评估

评估命令由各 subtask README 维护。结果写入各 subtask 的 `runs/` 目录。

## 6. 历史目录策略

旧版 root-level `datasets/`、`evaluation/` 和 `runs/` 目录已归档到：

```text
benchmark/online_pipeline/archive/20260617_subtask_domain_layout/meta_analysis/
```
