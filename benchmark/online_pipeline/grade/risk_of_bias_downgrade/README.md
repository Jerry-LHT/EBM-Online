# GRADE Domain: Risk-of-Bias Downgrade

本 domain 评估 GRADE 四域中的偏倚风险降级判断。评估单位是一个 SoF row 对应的 evidence body。

目录名使用 `risk_of_bias_downgrade`，用于和 article-level `benchmark/online_pipeline/risk_of_bias` 模块区分。数据和 prediction 内部的 GRADE 标准 domain label 仍为 `risk_of_bias`。

## 1. 任务边界

method 需要判断该 SoF row 是否因为纳入研究存在方法学偏倚风险而需要降级。

该 domain 不重新阅读全文生成 RoB 1 study-level judgement；它只基于上游 Risk of Bias 模块输出和 domain evidence 判断 GRADE 是否降级。

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
      <td><code>grade_v3</code></td>
      <td>569</td>
      <td>1</td>
      <td>278</td>
      <td>210</td>
      <td><a href="datasets/grade_v3/schema.md">schema.md</a></td>
    </tr>
    <tr>
      <td><code>grade_v4</code></td>
      <td>510</td>
      <td>1</td>
      <td>253</td>
      <td>182</td>
      <td><a href="datasets/grade_v4/schema.md">schema.md</a></td>
    </tr>
  </tbody>
</table>

`grade_v3` 保留为远端既有基线；`grade_v4` 是当前重建的数据版本。两者并存，运行时应显式指定所用数据集版本。

## 3. 输入依据

默认评估使用 `online_upstream` 输入模式：只允许真实 online pipeline 上游可产生的字段。`Summary of Findings` 表及其脚注是 GRADE gold judgement 的来源，不属于 article-level RoB 或 meta-analysis 上游输入；因此主评估不得使用 `sof_context.footnote_texts`、`sof_context.comment_text` 或 `sof_context.source_summary_of_findings_span_text`。

<table>
  <thead>
    <tr>
      <th>字段</th>
      <th>作用</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>analysis_setting</code></td>
      <td>上游 meta-analysis setting，包括 comparison、outcome、data type 和 effect measure。</td>
    </tr>
    <tr>
      <td><code>evidence_body</code> / <code>included_study_ids</code></td>
      <td>参与该 SoF row 证据综合的研究集合。</td>
    </tr>
    <tr>
      <td><code>domain_evidence</code></td>
      <td>偏倚风险相关证据，主要来自上游 study-level RoB judgements 的汇总。</td>
    </tr>
    <tr>
      <td><code>effect_estimate</code></td>
      <td>该 evidence body 的效应估计上下文，用于理解偏倚风险对结果可信度的影响。</td>
    </tr>
  </tbody>
</table>

### 泄漏风险

`instances.jsonl` 里仍保留 `sof_context`，因为其它 GRADE domain 和历史抽取实验可能会使用同一份 SoF row context。但对本模块的真实 online benchmark 来说，SoF 脚注常直接写出 “Downgraded one level for risk of bias” 等 gold rationale，属于 label-source leakage。

`method_llm` 默认不会把 `sof_context` 放进 prompt。只有显式设置：

```bash
GRADE_ROB_ALLOW_SOF_CONTEXT=1
```

才会进入 `sof_extraction_ablation` 模式。该模式只能用于诊断“从已有 SoF 表抽取结构化 GRADE judgement”的上限，不应作为 online prediction 主结果汇报。

## 4. 输出与指标

Gold 和 prediction 都是一个 GRADE domain judgement：

- `judgement.downgraded`
- `judgement.severity`
- `judgement.levels`
- `judgement.level_evaluable`

主要指标：

- `all_fields_exact_rate`
- `downgraded_exact_rate`
- `severity_exact_rate`
- `levels_exact_rate`
- `evaluable_exact_rate`

## 5. 运行

```bash
PYTHONPATH=backend/src python benchmark/online_pipeline/grade/risk_of_bias_downgrade/evaluation/runner.py \
  --method method_test \
  --run-id smoke-risk-of-bias-downgrade
```

结果写入：

```text
benchmark/online_pipeline/grade/risk_of_bias_downgrade/runs/<run_id>/
```
