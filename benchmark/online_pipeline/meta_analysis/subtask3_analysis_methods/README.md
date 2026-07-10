# Meta Analysis Subtask 3: Analysis Methods

本 subtask 评估 analysis method / model decision。评估单位是一个 `AnalysisSetting`。

## 1. 任务边界

method 需要为当前 setting 选择 effect measure、analysis model、statistical method、CI level，以及是否启用 overall estimates、subgroup estimates 和 subgroup difference tests。

该 subtask 不抽取 study result rows，也不计算 pooled estimates。

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
      <td>5308</td>
      <td>5</td>
      <td>2638</td>
      <td>2670</td>
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
      <td><code>analysis_setting</code>, <code>included_studies</code>, <code>source_context</code>, <code>source_refs</code></td>
    </tr>
    <tr>
      <td>Gold 输出</td>
      <td><code>analysis_methods</code></td>
    </tr>
    <tr>
      <td>预测目标</td>
      <td>当前 setting 的 method record，包括 effect measure、analysis model、statistical method、CI level 和 analysis flags。</td>
    </tr>
    <tr>
      <td>主要指标</td>
      <td><code>subtask3_method_exact_rate</code> 和 method-field exact rates</td>
    </tr>
  </tbody>
</table>

## 4. 运行

```bash
PYTHONPATH=backend/src python benchmark/online_pipeline/meta_analysis/subtask3_analysis_methods/evaluation/runner.py \
  --method method_test \
  --run-id smoke-subtask3
```

结果写入：

```text
benchmark/online_pipeline/meta_analysis/subtask3_analysis_methods/runs/<run_id>/
```
