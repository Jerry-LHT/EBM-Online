# Meta Analysis Subtask 4: Subgroup Analysis

本 subtask 评估 subgroup estimates 和 subgroup-difference tests。评估单位是一个带有 subgroup gold 的 `AnalysisSetting`。

## 1. 任务边界

method 需要基于 `analysis_setting`、`study_result_rows` 和 `analysis_methods` 生成 subgroup-level pooled estimates，并在有条件时生成 subgroup difference test。

该 subtask 不抽取 study result rows，不重新选择 analysis method，也不负责 overall pooled estimate。

Backend production estimates 不含 analysis-level `candidate_id`。由于既有 benchmark gold 仍用该字段做 legacy
join，module-specific production adapter 会在 backend method 返回后从 benchmark instance 补入；该字段不是
backend runtime contract。

输入的 `study_result_rows` 使用 canonical source-row assignment：当官方同一条 study row 同时标记为 subgroup
和 overall 时，builder 保留 subgroup 版本，避免 subgroup analysis 与 overall instance 共享重复 row。

## 2. 当前数据分布

<table>
  <thead>
    <tr>
      <th>Dataset</th>
      <th>All</th>
      <th>Smoke</th>
      <th>Dev</th>
      <th>Test</th>
      <th>Schema</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>cochrane_meta_v2</code></td>
      <td>3447</td>
      <td>63</td>
      <td>1782</td>
      <td>1665</td>
      <td><a href="datasets/cochrane_meta_v2/schema.md">schema.md</a></td>
    </tr>
  </tbody>
</table>

## 3. 数据契约

<table>
  <thead>
    <tr>
      <th>Item</th>
      <th>Fields</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>输入</td>
      <td><code>analysis_setting</code>, <code>study_result_rows</code>, <code>analysis_methods</code>, <code>included_studies</code>, <code>source_context</code>, <code>source_refs</code></td>
    </tr>
    <tr>
      <td>Gold 输出</td>
      <td><code>subgroup_results.subgroup_estimates</code>, <code>subgroup_results.subgroup_difference_tests</code></td>
    </tr>
    <tr>
      <td>预测目标</td>
      <td>subgroup pooled estimates 以及 family-level subgroup difference tests。</td>
    </tr>
    <tr>
      <td>主要指标</td>
      <td><code>subtask4_subgroup_join_rate</code>, <code>subtask4_estimate_exact_or_close_rate</code></td>
    </tr>
  </tbody>
</table>

## 4. 运行

```bash
PYTHONPATH=backend/src python benchmark/online_pipeline/meta_analysis/subtask4_subgroup_analysis/evaluation/runner.py \
  --method method_test \
  --run-id smoke-subtask4
```

结果写入：

```text
benchmark/online_pipeline/meta_analysis/subtask4_subgroup_analysis/runs/<run_id>/
```
