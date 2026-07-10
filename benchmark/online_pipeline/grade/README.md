# GRADE Benchmark

本 benchmark 对齐 `docs/workflow_v3.md` 中的 Module 7：Four-domain GRADE Assessment。

GRADE benchmark 的基本单位不是完整 workflow，而是一个已经对齐到 workflow analysis setting 的 SoF row，以及其中一个 GRADE downgrade domain。

- 最终 workflow 单位：一个 `SoF row`
- benchmark 评估单位：一个 `SoF row` + 一个 GRADE domain
- 当前覆盖 domain：`risk_of_bias`、`inconsistency`、`indirectness`、`imprecision`
- `risk_of_bias` 的 benchmark 目录名为 `risk_of_bias_downgrade`，用于和 article-level Risk of Bias 模块区分；内部 GRADE domain label 仍为 `risk_of_bias`。
- 保留规则：一个 benchmark SoF row 必须能唯一对齐到一个 workflow analysis setting

模块级 builder 会从同一套 SoF row alignment 构建四个 domain 数据集，但每个 domain 拥有独立的 dataset、evaluator 和 runs 目录。

## 1. 目录结构

```text
benchmark/online_pipeline/grade/risk_of_bias_downgrade/
  datasets/grade_v4/
  evaluation/runner.py
  runs/

benchmark/online_pipeline/grade/inconsistency/
  datasets/grade_v4/
  evaluation/runner.py
  runs/

benchmark/online_pipeline/grade/indirectness/
  datasets/grade_v4/
  evaluation/runner.py
  runs/

benchmark/online_pipeline/grade/imprecision/
  datasets/grade_v4/
  evaluation/runner.py
  runs/
```

每个 domain dataset 包含：

- `instances.jsonl`：domain 输入记录
- `gold.jsonl`：标准 GRADE domain judgement
- `schema.md`：该 domain dataset 的字段说明
- `splits/{smoke,dev,test}`：可运行 split
- `shared/row_records.jsonl`：该 domain dataset 使用的 canonical SoF row 记录

当前不会生成 `grade/datasets/<dataset_name>/` 这种模块级 dataset。builder 只写入可直接运行的 domain dataset，并返回 `dataset_dirs` 映射。

## 2. Domain 文档

四个 domain 共享同一个 SoF row / evidence body 上下文，但判断依据不同。每个 domain runner 只评估本 domain 的 judgement，不评估 final certainty，也不评估 publication bias。各 domain 的详细任务边界、输入输出和运行示例由各自目录维护。

<table>
  <thead>
    <tr>
      <th>Domain</th>
      <th>中文含义</th>
      <th>All</th>
      <th>Smoke</th>
      <th>Dev</th>
      <th>Test</th>
      <th>Schema</th>
      <th>文档</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>risk_of_bias</code></td>
      <td>偏倚风险降级</td>
      <td>510</td>
      <td>1</td>
      <td>253</td>
      <td>182</td>
      <td><a href="risk_of_bias_downgrade/datasets/grade_v4/schema.md">schema.md</a></td>
      <td><a href="risk_of_bias_downgrade/README.md">README.md</a></td>
    </tr>
    <tr>
      <td><code>inconsistency</code></td>
      <td>不一致性</td>
      <td>632</td>
      <td>5</td>
      <td>253</td>
      <td>182</td>
      <td><a href="inconsistency/datasets/grade_v4/schema.md">schema.md</a></td>
      <td><a href="inconsistency/README.md">README.md</a></td>
    </tr>
    <tr>
      <td><code>indirectness</code></td>
      <td>间接性</td>
      <td>632</td>
      <td>4</td>
      <td>253</td>
      <td>182</td>
      <td><a href="indirectness/datasets/grade_v4/schema.md">schema.md</a></td>
      <td><a href="indirectness/README.md">README.md</a></td>
    </tr>
    <tr>
      <td><code>imprecision</code></td>
      <td>不精确性</td>
      <td>630</td>
      <td>5</td>
      <td>252</td>
      <td>181</td>
      <td><a href="imprecision/datasets/grade_v4/schema.md">schema.md</a></td>
      <td><a href="imprecision/README.md">README.md</a></td>
    </tr>
  </tbody>
</table>

## 3. 输入与输出

每条 `instances.jsonl` 记录表示一个 SoF row 在一个 domain 下的评估输入。四个 domain 共享大部分字段，但 `domain_evidence` 的含义随 domain 变化。

<table>
  <thead>
    <tr>
      <th>字段</th>
      <th>含义</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>instance_id</code></td>
      <td>domain 级样本 ID</td>
    </tr>
    <tr>
      <td><code>review_id</code> / <code>sample_id</code> / <code>sof_row_id</code></td>
      <td>来源 review、样本和 SoF row 标识</td>
    </tr>
    <tr>
      <td><code>domain</code></td>
      <td>当前样本对应的 GRADE domain</td>
    </tr>
    <tr>
      <td><code>question_text</code> / <code>question_pico</code></td>
      <td>目标临床问题及 question-level PICO；主要用于 indirectness。imprecision 的 <code>method_llm_web</code> 不使用该字段，避免 SR 标题定位真实 SoF/gold。</td>
    </tr>
    <tr>
      <td><code>sof_context</code></td>
      <td>SoF row 的原始上下文。注意：SoF 脚注和 summary span 是 GRADE gold 的来源，可能直接泄漏 downgrade rationale；online prediction 主评估不得使用这些 label-source 字段。</td>
    </tr>
    <tr>
      <td><code>analysis_setting</code></td>
      <td>该 SoF row 对齐到的 workflow analysis setting</td>
    </tr>
    <tr>
      <td><code>evidence_body</code> / <code>included_study_ids</code></td>
      <td>参与该 SoF row 证据综合的研究集合</td>
    </tr>
    <tr>
      <td><code>study_result_rows</code></td>
      <td>Meta Analysis study-level result rows；主要用于 inconsistency 和 imprecision</td>
    </tr>
    <tr>
      <td><code>effect_estimate</code></td>
      <td>该 SoF row 的效应估计、置信区间和相关统计量</td>
    </tr>
    <tr>
      <td><code>domain_evidence</code></td>
      <td>当前 domain 专属证据，例如 RoB judgement 汇总、异质性信息、PIO 间接性证据或不精确性证据</td>
    </tr>
  </tbody>
</table>

`gold.jsonl` 的核心字段如下：

<table>
  <thead>
    <tr>
      <th>字段</th>
      <th>含义</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>instance_id</code></td>
      <td>对应输入样本</td>
    </tr>
    <tr>
      <td><code>domain</code></td>
      <td>当前 GRADE domain</td>
    </tr>
    <tr>
      <td><code>sof_row_id</code></td>
      <td>对应 SoF row</td>
    </tr>
    <tr>
      <td><code>judgement.downgraded</code></td>
      <td>是否降级</td>
    </tr>
    <tr>
      <td><code>judgement.severity</code></td>
      <td>降级严重程度标签</td>
    </tr>
    <tr>
      <td><code>judgement.levels</code></td>
      <td>降级等级数</td>
    </tr>
    <tr>
      <td><code>judgement.level_evaluable</code></td>
      <td>该降级等级是否可评估</td>
    </tr>
  </tbody>
</table>

## 4. 原始数据

GRADE source rows 和 domain labels：

```text
benchmark/online_pipeline/raw_data/grade/source/legacy_grade_benchmark_v2/intermediate/04_sof_rows_cleaned.jsonl
benchmark/online_pipeline/raw_data/grade/source/legacy_grade_benchmark_v2/intermediate/05_sof_gold_domains.jsonl
benchmark/online_pipeline/raw_data/grade/source/legacy_release_splits/
```

GRADE 需要共享的 analysis settings：

```text
benchmark/online_pipeline/raw_data/analysis_settings/grade_required_v1/
```

正式 GRADE v4 alignment 产物：

```text
benchmark/online_pipeline/raw_data/grade/intermediate/alignment_v3/
```

`grade_v4` 要求 `alignment_v3/alignment_summary.json` 的 `builder_version` 为
`online-pipeline-builder-v4-grade-alignment` 且 `mode = "llm"`。旧 `grade_v3`
数据与其衍生 alignment 已归入本地 `archive/`，不能被静默包装成 `grade_v4`。builder 不再使用
legacy `benchmark_core*.jsonl` 或旧版 SoF-analysis alignment 文件作为对齐输入。

## 5. 构建

从已完成的 v4 `alignment_v3` 产物构建四个 domain dataset：

```bash
PYTHONPATH=backend/src python benchmark/online_pipeline/grade/raw_builder.py build-dataset-v3 \
  --dataset-name grade_v4 \
  --shared-settings-root benchmark/online_pipeline/raw_data/analysis_settings/grade_required_v1
```

如需完整重建 alignment：

```bash
PYTHONPATH=backend/src python benchmark/online_pipeline/grade/raw_builder.py all-v3 \
  --config llm.local.json \
  --api-mode responses \
  --model gpt-5.4-mini \
  --workers 8 \
  --resume \
  --dataset-name grade_v4 \
  --shared-settings-root benchmark/online_pipeline/raw_data/analysis_settings/grade_required_v1
```

## 6. 评估

### 输入泄漏约束

GRADE 数据集中保留了 SoF row context 以支持对齐审计和抽取型实验，但真实 online prediction 只能使用上游 pipeline 可产生的信息，例如 analysis setting、effect estimate、included studies、study-level RoB、study results 和 PICO/characteristics 等。来自已有 Summary of Findings 表的 `footnote_texts`、`comment_text`、`source_summary_of_findings_span_text` 可能直接包含人工 GRADE 降级理由，不能作为主评估输入。

如需评估 SoF 抽取能力，应在 run id 和报告中明确标注为 extraction/ablation，不得与 online prediction 结果混在一起。

评估命令由各 domain README 维护。runner 比较真实的 GRADE judgement 字段：

- `downgraded_exact_rate`：是否降级完全一致
- `severity_exact_rate`：严重程度标签完全一致
- `levels_exact_rate`：降级等级数完全一致
- `evaluable_exact_rate`：等级是否可评估完全一致
- `all_fields_exact_rate`：上述核心字段全部一致

`imprecision` 额外报告 PRF-oriented 指标：

- `downgrade_precision/recall/f1_on_evaluable`
- `level_macro_precision/recall/f1_on_evaluable`
- `level_ordinal_mae_on_evaluable`

这些指标将 `unclear` / `level_evaluable=false` 样本排除在主 PRF/MAE 分母之外，并单独统计 coverage 与 threshold research 质量。

结果写入各 domain 的 `runs/` 目录。

## 7. 历史目录策略

旧版 root-level `datasets/`、`evaluation/` 和 `runs/` 目录已归档到：

```text
benchmark/online_pipeline/archive/20260617_subtask_domain_layout/grade/
```
