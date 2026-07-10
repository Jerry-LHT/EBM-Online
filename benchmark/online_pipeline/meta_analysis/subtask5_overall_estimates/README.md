# Meta Analysis Subtask 5: Overall Estimates

本 subtask 评估 overall pooled estimates。评估单位是一个需要 overall estimate 的 `AnalysisSetting`。

## 1. 任务边界

method 需要基于 `analysis_setting`、`study_result_rows` 和 `analysis_methods` 计算 overall pooled estimate、置信区间、heterogeneity 和 effect test。

该 subtask 不抽取 study result rows，不重新选择 analysis method，也不生成 subgroup estimates。

官方 overall pooled estimate 仍作为 gold 保留；但 `study_result_rows` 使用 canonical source-row assignment。
如果一条官方 study row 同时属于 subgroup 和 overall，builder 会优先归到 subgroup，不在 overall instance
里重复提供该 row。

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
      <td>751</td>
      <td>5</td>
      <td>364</td>
      <td>387</td>
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
      <td><code>overall_estimates</code></td>
    </tr>
    <tr>
      <td>预测目标</td>
      <td>overall pooled estimates，包括 effect value、CI、heterogeneity、effect test 和 estimation status。</td>
    </tr>
    <tr>
      <td>主要指标</td>
      <td>overall estimate exact / close numeric rates</td>
    </tr>
  </tbody>
</table>

## 4. 运行

```bash
PYTHONPATH=backend/src python benchmark/online_pipeline/meta_analysis/subtask5_overall_estimates/evaluation/runner.py \
  --method method_test \
  --run-id smoke-subtask5
```

结果写入：

```text
benchmark/online_pipeline/meta_analysis/subtask5_overall_estimates/runs/<run_id>/
```
