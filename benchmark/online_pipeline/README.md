# Online Pipeline Benchmark 文档

本文档是当前分支的 online EBM workflow benchmark 总入口。

workflow 模块契约见 [`docs/workflow_v3.md`](../../docs/workflow_v3.md)。本目录只描述 benchmark 如何构建、运行、记录结果，以及每个模块当前使用的数据、输入、gold 输出和指标。

当前 benchmark 直接调用后端内部 Python method，不经过 FastAPI routes。

## 1. 范围

当前 benchmark 按 online pipeline 模块组织。每个 benchmark unit 对齐一个 workflow 模块，或者对齐一个明确的模块子任务 / GRADE domain。

<table>
  <thead>
    <tr>
      <th>模块</th>
      <th>状态</th>
      <th>Benchmark Unit</th>
      <th>Dataset</th>
      <th>README</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>q2pico</code></td>
      <td>已接入</td>
      <td>一个 clinical question</td>
      <td><code>q2crbench3</code></td>
      <td><a href="q2pico/README.md">q2pico/README.md</a></td>
    </tr>
    <tr>
      <td><code>study_screening</code></td>
      <td>已接入</td>
      <td>一个 review question 下的一篇候选文章</td>
      <td><code>csmed_ft</code></td>
      <td><a href="study_screening/README.md">study_screening/README.md</a></td>
    </tr>
    <tr>
      <td><code>study_pio</code></td>
      <td>已接入</td>
      <td>一个 included study</td>
      <td><code>cochrane_study_pio</code></td>
      <td><a href="study_pio/README.md">study_pio/README.md</a></td>
    </tr>
    <tr>
      <td><code>risk_of_bias</code></td>
      <td>已接入</td>
      <td>一个 included study 的 RoB 1 domains 判断</td>
      <td><code>cochrane_rob1</code></td>
      <td><a href="risk_of_bias/README.md">risk_of_bias/README.md</a></td>
    </tr>
    <tr>
      <td><code>meta_analysis</code></td>
      <td>按 subtask 接入</td>
      <td>一个 analysis setting / subtask instance</td>
      <td><code>cochrane_meta_v2</code></td>
      <td><a href="meta_analysis/README.md">meta_analysis/README.md</a></td>
    </tr>
    <tr>
      <td><code>grade</code></td>
      <td>按 domain 接入</td>
      <td>一个 SoF row + 一个 GRADE domain</td>
      <td><code>grade_v4</code></td>
      <td><a href="grade/README.md">grade/README.md</a></td>
    </tr>
    <tr>
      <td><code>search_retrieval</code></td>
      <td>占位</td>
      <td>尚未定义</td>
      <td>无</td>
      <td><a href="search_retrieval/README.md">search_retrieval/README.md</a></td>
    </tr>
  </tbody>
</table>

## 2. 目录结构

```text
benchmark/online_pipeline/
  benchmark.py                 # 统一 build/run/index CLI
  builders.py                  # 模块 builder 分发
  raw_data/                    # 冻结或下载的 source data
  shared/                      # benchmark 共享工具和 builder
  <module>/
    README.md
    builder.py
    datasets/<dataset_name>/
      instances.jsonl
      gold.jsonl
      schema.md
      source_manifest.json
      build_manifest.json
      split_manifest.json
      splits/{smoke,dev,test}/
    evaluation/runner.py
    runs/<run_id>/
```

`meta_analysis` 和 `grade` 使用 subtask/domain 级可运行 dataset，不生成模块级 dataset root：

```text
meta_analysis/<subtask>/datasets/<dataset_name>/
grade/<domain>/datasets/grade_v4/
```

## 3. 使用方式

所有命令从仓库根目录运行。

构建一个 dataset：

```bash
PYTHONPATH=backend/src:. python benchmark/online_pipeline/benchmark.py build \
  --module q2pico \
  --source q2crbench3 \
  --dataset-name q2crbench3
```

运行一个 benchmark：

```bash
PYTHONPATH=backend/src:. python benchmark/online_pipeline/benchmark.py run \
  --module q2pico \
  --dataset-name q2crbench3 \
  --split smoke \
  --method gold \
  --run-id q2pico-smoke \
  --limit 3
```

构建并运行：

```bash
PYTHONPATH=backend/src:. python benchmark/online_pipeline/benchmark.py all \
  --module study_screening \
  --source csmed_ft \
  --dataset-name csmed_ft \
  --split smoke \
  --method gold \
  --run-id csmed-ft-smoke \
  --limit 5
```

运行 Meta Analysis subtask：

```bash
PYTHONPATH=backend/src:. python benchmark/online_pipeline/benchmark.py run \
  --module meta_analysis \
  --subtask subtask2_study_results \
  --dataset-name cochrane_meta_v2-key-filter \
  --split smoke \
  --method method_test \
  --run-id meta-subtask2-smoke \
  --limit 5
```

运行 GRADE domain：

```bash
PYTHONPATH=backend/src:. python benchmark/online_pipeline/benchmark.py run \
  --module grade \
  --domain risk_of_bias_downgrade \
  --dataset-name grade_v4 \
  --split smoke \
  --method method_test \
  --run-id grade-rob-downgrade-v4-smoke \
  --limit 1
```

当前默认可复现版本是 `cochrane_meta_v2` / `cochrane_meta_v2-key-filter` 和 `grade_v4`。其中
`grade/risk_of_bias_downgrade` 同时保留远端既有的 `grade_v3` 与当前 `grade_v4`；其余 GRADE domain 的旧
`grade_v3` 仅保留在本地 archive。

需要 LLM judge 的 evaluator 从仓库根目录的 `llm.local.json` 读取配置：

```bash
--judge-mode llm --llm-config llm.local.json --resume --workers 4
```

## 4. Method 接入

benchmark runner 直接调用 Python method，不调用 HTTP API。

<table>
  <thead>
    <tr>
      <th>Method 名称</th>
      <th>用途</th>
      <th>说明</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>gold</code></td>
      <td>benchmark-only oracle baseline</td>
      <td>用于验证 dataset mapping、runner 逻辑和 metrics 是否正确。</td>
    </tr>
    <tr>
      <td><code>method_test</code></td>
      <td>轻量 smoke method</td>
      <td>用于 domain/subtask runner 提供本地测试 method 的场景。</td>
    </tr>
    <tr>
      <td><code>&lt;module&gt;.&lt;method_name&gt;</code></td>
      <td>真实后端 method</td>
      <td>由 module-specific benchmark adapter 校验并显式映射；单一正式实现可调用 production factory，实验实现可直接调用对应 concrete builder，不经过通用后端 registry。</td>
    </tr>
  </tbody>
</table>

这种方式让 benchmark 执行路径贴近后端实现，同时避免把 API route 设计混入 benchmark 评估。

## 5. Dataset 文件约定

每个可运行 dataset 遵循同一套文件约定。

<table>
  <thead>
    <tr>
      <th>文件</th>
      <th>作用</th>
      <th>含义</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>instances.jsonl</code></td>
      <td>benchmark 输入</td>
      <td>runner 读取后转换为 workflow method input 的记录。</td>
    </tr>
    <tr>
      <td><code>gold.jsonl</code></td>
      <td>参考答案</td>
      <td>deterministic scoring 或 LLM judge prompt 使用的 gold 字段。</td>
    </tr>
    <tr>
      <td><code>schema.md</code></td>
      <td>dataset schema</td>
      <td>与 dataset 放在一起维护的精确字段说明。</td>
    </tr>
    <tr>
      <td><code>source_manifest.json</code></td>
      <td>source provenance</td>
      <td>raw source 名称、位置和 source-specific metadata。</td>
    </tr>
    <tr>
      <td><code>build_manifest.json</code></td>
      <td>build provenance</td>
      <td>builder、seed、dataset name 和可复现构建信息。</td>
    </tr>
    <tr>
      <td><code>split_manifest.json</code></td>
      <td>split metadata</td>
      <td>split 策略和 split counts。</td>
    </tr>
    <tr>
      <td><code>splits/{smoke,dev,test}/</code></td>
      <td>可运行 split</td>
      <td>每个 split 自己的 <code>instances.jsonl</code> 和 <code>gold.jsonl</code>。</td>
    </tr>
  </tbody>
</table>

部分 dataset 还包含共享 article 或 row layer，例如：

- `study_pio/datasets/cochrane_study_pio/articles/`
- `risk_of_bias/datasets/cochrane_rob1/articles/`
- `meta_analysis/subtask2_study_results/datasets/cochrane_meta_v2-key-filter/shared/`
- `grade/<domain>/datasets/grade_v4/shared/row_records.jsonl`

## 6. 运行产物

每次 run 的产物写入对应 module、subtask 或 domain 的 `runs/<run_id>/` 目录。

<table>
  <thead>
    <tr>
      <th>产物</th>
      <th>作用</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>predictions.jsonl</code></td>
      <td>标准化后的 method outputs</td>
    </tr>
    <tr>
      <td><code>prediction_failures.jsonl</code></td>
      <td>method 执行失败的记录</td>
    </tr>
    <tr>
      <td><code>comparisons.jsonl</code></td>
      <td>deterministic evaluator 的 gold/prediction comparison rows</td>
    </tr>
    <tr>
      <td><code>judge_matches.jsonl</code></td>
      <td>LLM judge evaluator 的 match rows</td>
    </tr>
    <tr>
      <td><code>metrics.json</code></td>
      <td>机器可读 run metrics</td>
    </tr>
    <tr>
      <td><code>summary.json</code> / <code>summary.md</code></td>
      <td>人类可读 run summary</td>
    </tr>
    <tr>
      <td><code>run_manifest.json</code></td>
      <td>method、dataset、split 和 runtime metadata</td>
    </tr>
    <tr>
      <td><code>metrics_index.csv</code></td>
      <td>module、subtask 或 domain 级跨 run 对比表</td>
    </tr>
  </tbody>
</table>

## 7. 当前数据分布

下表反映当前仓库中已经构建好的 datasets。

<table>
  <thead>
    <tr>
      <th>Benchmark</th>
      <th>Dataset Path</th>
      <th>All</th>
      <th>Smoke</th>
      <th>Dev</th>
      <th>Test</th>
      <th>Schema</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Q2PICO</td>
      <td><code>q2pico/datasets/q2crbench3</code></td>
      <td>99</td>
      <td>10</td>
      <td>40</td>
      <td>59</td>
      <td><a href="q2pico/datasets/q2crbench3/schema.md">schema.md</a></td>
    </tr>
    <tr>
      <td>Study Screening</td>
      <td><code>study_screening/datasets/csmed_ft</code></td>
      <td>3333</td>
      <td>5</td>
      <td>644</td>
      <td>636</td>
      <td><a href="study_screening/datasets/csmed_ft/schema.md">schema.md</a></td>
    </tr>
    <tr>
      <td>Study PIO</td>
      <td><code>study_pio/datasets/cochrane_study_pio</code></td>
      <td>428</td>
      <td>5</td>
      <td>209</td>
      <td>219</td>
      <td><a href="study_pio/datasets/cochrane_study_pio/schema.md">schema.md</a></td>
    </tr>
    <tr>
      <td>Risk of Bias</td>
      <td><code>risk_of_bias/datasets/cochrane_rob1</code></td>
      <td>348</td>
      <td>5</td>
      <td>171</td>
      <td>177</td>
      <td><a href="risk_of_bias/datasets/cochrane_rob1/schema.md">schema.md</a></td>
    </tr>
    <tr>
      <td>Meta Analysis / Subtask 2</td>
      <td><code>meta_analysis/subtask2_study_results/datasets/cochrane_meta_v2-key-filter</code></td>
      <td>1041</td>
      <td>5</td>
      <td>451</td>
      <td>590</td>
      <td><a href="meta_analysis/subtask2_study_results/datasets/cochrane_meta_v2-key-filter/schema.md">schema.md</a></td>
    </tr>
    <tr>
      <td>Meta Analysis / Subtask 3</td>
      <td><code>meta_analysis/subtask3_analysis_methods/datasets/cochrane_meta_v2</code></td>
      <td>5308</td>
      <td>5</td>
      <td>2638</td>
      <td>2670</td>
      <td><a href="meta_analysis/subtask3_analysis_methods/datasets/cochrane_meta_v2/schema.md">schema.md</a></td>
    </tr>
    <tr>
      <td>Meta Analysis / Subtask 4</td>
      <td><code>meta_analysis/subtask4_subgroup_analysis/datasets/cochrane_meta_v2</code></td>
      <td>3447</td>
      <td>63</td>
      <td>1782</td>
      <td>1665</td>
      <td><a href="meta_analysis/subtask4_subgroup_analysis/datasets/cochrane_meta_v2/schema.md">schema.md</a></td>
    </tr>
    <tr>
      <td>Meta Analysis / Subtask 5</td>
      <td><code>meta_analysis/subtask5_overall_estimates/datasets/cochrane_meta_v2</code></td>
      <td>1108</td>
      <td>5</td>
      <td>533</td>
      <td>575</td>
      <td><a href="meta_analysis/subtask5_overall_estimates/datasets/cochrane_meta_v2/schema.md">schema.md</a></td>
    </tr>
    <tr>
      <td>GRADE / 偏倚风险降级</td>
      <td><code>grade/risk_of_bias_downgrade/datasets/grade_v4</code></td>
      <td>510</td>
      <td>1</td>
      <td>253</td>
      <td>182</td>
      <td><a href="grade/risk_of_bias_downgrade/datasets/grade_v4/schema.md">schema.md</a></td>
    </tr>
    <tr>
      <td>GRADE / 偏倚风险降级（既有基线）</td>
      <td><code>grade/risk_of_bias_downgrade/datasets/grade_v3</code></td>
      <td>569</td>
      <td>1</td>
      <td>278</td>
      <td>210</td>
      <td><a href="grade/risk_of_bias_downgrade/datasets/grade_v3/schema.md">schema.md</a></td>
    </tr>
    <tr>
      <td>GRADE / 不一致性</td>
      <td><code>grade/inconsistency/datasets/grade_v4</code></td>
      <td>632</td>
      <td>5</td>
      <td>253</td>
      <td>182</td>
      <td><a href="grade/inconsistency/datasets/grade_v4/schema.md">schema.md</a></td>
    </tr>
    <tr>
      <td>GRADE / 间接性</td>
      <td><code>grade/indirectness/datasets/grade_v4</code></td>
      <td>632</td>
      <td>4</td>
      <td>253</td>
      <td>182</td>
      <td><a href="grade/indirectness/datasets/grade_v4/schema.md">schema.md</a></td>
    </tr>
    <tr>
      <td>GRADE / 不精确性</td>
      <td><code>grade/imprecision/datasets/grade_v4</code></td>
      <td>630</td>
      <td>5</td>
      <td>252</td>
      <td>181</td>
      <td><a href="grade/imprecision/datasets/grade_v4/schema.md">schema.md</a></td>
    </tr>
  </tbody>
</table>

Study Screening 和 GRADE 的完整 `all` 文件可能包含不在可运行 dev/test release split 中的记录。正式比较 methods 时应优先使用 split 目录。

## 8. 模块数据契约

### 8.1 Q2PICO

<table>
  <thead>
    <tr>
      <th>项目</th>
      <th>内容</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Source</td>
      <td><code>somewordstoolate/Q2CRBench-3</code> / <code>Clinical_Questions</code></td>
    </tr>
    <tr>
      <td>输入字段</td>
      <td><code>instance_id</code>, <code>question_text</code>, <code>metadata</code>, <code>source</code></td>
    </tr>
    <tr>
      <td>Gold 字段</td>
      <td><code>P</code>, <code>I</code>, <code>C</code>, <code>O</code></td>
    </tr>
    <tr>
      <td>预测目标</td>
      <td>workflow <code>question_pico</code></td>
    </tr>
    <tr>
      <td>Evaluator</td>
      <td>LLM judge 或 normalized local matcher</td>
    </tr>
    <tr>
      <td>主要指标</td>
      <td><code>micro_f1</code>, <code>macro_f1</code>, per-slot precision / recall / F1</td>
    </tr>
  </tbody>
</table>

### 8.2 Study Screening

<table>
  <thead>
    <tr>
      <th>项目</th>
      <th>内容</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Source</td>
      <td><code>CSMeD-FT</code> full-text screening fixtures</td>
    </tr>
    <tr>
      <td>输入字段</td>
      <td><code>question_text</code>, <code>screening_criteria</code>, <code>articles</code></td>
    </tr>
    <tr>
      <td>Gold 字段</td>
      <td><code>gold_decision</code>, <code>gold_reason</code>, <code>study_id</code></td>
    </tr>
    <tr>
      <td>预测目标</td>
      <td>一个带 include / exclude decision 的 <code>StudyScreeningResult</code></td>
    </tr>
    <tr>
      <td>Evaluator</td>
      <td>deterministic classification；include 是 positive class</td>
    </tr>
    <tr>
      <td>主要指标</td>
      <td><code>include_precision</code>, <code>include_recall</code>, <code>include_f1</code>, <code>accuracy</code>, <code>false_negative_count</code></td>
    </tr>
  </tbody>
</table>

### 8.3 Study PIO

<table>
  <thead>
    <tr>
      <th>项目</th>
      <th>内容</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Source</td>
      <td><code>raw_data/</code> 下冻结的 Cochrane cleaned SR 和 cleaned article snapshot</td>
    </tr>
    <tr>
      <td>输入字段</td>
      <td><code>question_pico</code>, <code>included_studies</code>, <code>article_ids</code>, <code>study_id</code>, <code>review_id</code></td>
    </tr>
    <tr>
      <td>Gold 字段</td>
      <td><code>population</code>, <code>intervention_comparator</code>, <code>outcomes</code></td>
    </tr>
    <tr>
      <td>预测目标</td>
      <td>当前 included study 的一个 <code>StudyPIOCharacteristics</code> record</td>
    </tr>
    <tr>
      <td>Evaluator</td>
      <td>LLM judge 或 normalized local matcher</td>
    </tr>
    <tr>
      <td>主要指标</td>
      <td><code>macro_f1</code>, <code>micro_f1</code>, field precision / recall / F1, <code>critical_fields_complete_rate</code></td>
    </tr>
  </tbody>
</table>

### 8.4 Risk of Bias

<table>
  <thead>
    <tr>
      <th>项目</th>
      <th>内容</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td>Source</td>
      <td>Cochrane source reviews、study links 和共享 cleaned article snapshot</td>
    </tr>
    <tr>
      <td>输入字段</td>
      <td><code>included_studies</code>, <code>article_ids</code>, <code>study_id</code>, <code>review_id</code></td>
    </tr>
    <tr>
      <td>Gold 字段</td>
      <td><code>risk_of_bias[*].domain</code>, <code>risk_of_bias[*].judgement</code>, <code>support_text</code></td>
    </tr>
    <tr>
      <td>预测目标</td>
      <td>固定 RoB 1 domains 上的 <code>RiskOfBiasAssessment[]</code></td>
    </tr>
    <tr>
      <td>Evaluator</td>
      <td>deterministic fixed-label classification</td>
    </tr>
    <tr>
      <td>主要指标</td>
      <td><code>domain_macro_f1</code>, <code>accuracy</code>, <code>high_risk_recall</code>, <code>domain_coverage_rate</code></td>
    </tr>
  </tbody>
</table>

### 8.5 Meta Analysis

<table>
  <thead>
    <tr>
      <th>Subtask</th>
      <th>输入摘要</th>
      <th>Gold 输出</th>
      <th>主要指标</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>subtask2_study_results</code></td>
      <td><code>analysis_setting</code>、linked articles、included studies、source context</td>
      <td><code>study_result_rows</code></td>
      <td><code>subtask2_exact_row_rate</code>, <code>subtask2_numeric_close_rate</code>, <code>field_completion_rate</code></td>
    </tr>
    <tr>
      <td><code>subtask3_analysis_methods</code></td>
      <td><code>analysis_setting</code>、included studies、source context</td>
      <td><code>analysis_methods</code></td>
      <td><code>subtask3_method_exact_rate</code> 和 method-field exact rates</td>
    </tr>
    <tr>
      <td><code>subtask4_subgroup_analysis</code></td>
      <td><code>analysis_setting</code>、<code>analysis_methods</code>、<code>study_result_rows</code></td>
      <td><code>subgroup_results</code></td>
      <td><code>subtask4_subgroup_join_rate</code>, <code>subtask4_estimate_exact_or_close_rate</code></td>
    </tr>
    <tr>
      <td><code>subtask5_overall_estimates</code></td>
      <td><code>analysis_setting</code>、<code>analysis_methods</code>、<code>study_result_rows</code></td>
      <td><code>overall_estimates</code></td>
      <td>overall estimate exact / close numeric rates</td>
    </tr>
  </tbody>
</table>

### 8.6 GRADE

<table>
  <thead>
    <tr>
      <th>Domain</th>
      <th>判断问题</th>
      <th>主要输入依据</th>
      <th>Gold / Prediction</th>
      <th>主要指标</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>risk_of_bias</code></td>
      <td>判断该 SoF row 对应的 evidence body 是否因为纳入研究存在偏倚风险而需要降级。</td>
      <td><code>sof_context</code>、<code>evidence_body</code>、<code>included_study_ids</code>、上游 RoB 1 study-level judgements、effect estimate 及相关 domain evidence。</td>
      <td>一个 GRADE domain judgement，包括是否降级、严重程度、降级等级和该等级是否可评估。</td>
      <td><code>all_fields_exact_rate</code>、<code>downgraded_exact_rate</code>、<code>severity_exact_rate</code>、<code>levels_exact_rate</code></td>
    </tr>
    <tr>
      <td><code>inconsistency</code></td>
      <td>判断各研究结果是否存在重要方向、大小或统计异质性差异，从而影响合并效应的可信度。</td>
      <td><code>sof_context</code>、<code>analysis_setting</code>、<code>study_result_rows</code>、overall/subgroup effect estimates、heterogeneity summary、subgroup difference evidence。</td>
      <td>一个 GRADE domain judgement，包括是否降级、严重程度、降级等级和该等级是否可评估。</td>
      <td><code>all_fields_exact_rate</code>、<code>downgraded_exact_rate</code>、<code>severity_exact_rate</code>、<code>levels_exact_rate</code></td>
    </tr>
    <tr>
      <td><code>indirectness</code></td>
      <td>判断纳入证据在 population、intervention/comparator、outcome 或研究适用性上是否偏离目标临床问题。</td>
      <td><code>question_text</code>、<code>question_pico</code>、<code>screening_criteria</code>、study-level PIO characteristics、<code>analysis_setting</code>、SoF row outcome/context。</td>
      <td>一个 GRADE domain judgement，包括是否降级、严重程度、降级等级和该等级是否可评估。</td>
      <td><code>all_fields_exact_rate</code>、<code>downgraded_exact_rate</code>、<code>severity_exact_rate</code>、<code>levels_exact_rate</code></td>
    </tr>
    <tr>
      <td><code>imprecision</code></td>
      <td>判断效应估计是否因为置信区间过宽、样本量或事件数不足、跨越重要临床阈值等原因而不精确。</td>
      <td><code>effect_estimate</code>、置信区间、样本量/事件数、effect measure、SoF row absolute/relative effect context、imprecision domain evidence。</td>
      <td>一个 GRADE domain judgement，包括是否降级、严重程度、降级等级和该等级是否可评估。</td>
      <td><code>all_fields_exact_rate</code>、<code>downgraded_exact_rate</code>、<code>severity_exact_rate</code>、<code>levels_exact_rate</code></td>
    </tr>
  </tbody>
</table>

## 9. Raw Data 策略

`raw_data/` 存放重建当前 benchmark dataset 所需的原始或冻结 source material。标准化 benchmark artifacts 应放在各自可运行的 `datasets/<dataset_name>/` 目录下，不放在 `raw_data/`。

<table>
  <thead>
    <tr>
      <th>Raw Data 区域</th>
      <th>使用模块</th>
      <th>作用</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>raw_data/q2crbench3_clinical_questions</code></td>
      <td>Q2PICO</td>
      <td>下载后的 Hugging Face source cache</td>
    </tr>
    <tr>
      <td><code>raw_data/csmed_ft</code></td>
      <td>Study Screening</td>
      <td>下载后的 CSMeD-FT source cache</td>
    </tr>
    <tr>
      <td><code>raw_data/cleaned_sr</code>, <code>raw_data/cleaned_articles</code></td>
      <td>Study PIO, Risk of Bias</td>
      <td>冻结的 cleaned SR 和 article snapshots</td>
    </tr>
    <tr>
      <td><code>raw_data/meta_analysis</code></td>
      <td>Meta Analysis</td>
      <td>官方 Cochrane analysis CSV snapshot 及其 derived intermediate files</td>
    </tr>
    <tr>
      <td><code>raw_data/analysis_settings/grade_required_v1</code></td>
      <td>Meta Analysis, GRADE</td>
      <td>下游 GRADE alignment 需要共享的 analysis settings；只接受 v2 comparison cache/source hash 有效行</td>
    </tr>
    <tr>
      <td><code>raw_data/grade</code></td>
      <td>GRADE</td>
      <td>legacy GRADE source rows、labels、release splits 和 alignment artifacts；普通 build 只读该冻结 snapshot，不依赖外部 sr-cleaned 分支</td>
    </tr>
  </tbody>
</table>

除非明确刷新 source artifacts，否则不要重新运行耗时的 LLM raw cleaning。
