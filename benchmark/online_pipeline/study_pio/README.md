# Study PIO Benchmark

本 benchmark 评估 Study-level PIO Characteristics Extraction 模块。评估单位是一个 included study。

该模块从纳入研究的文章内容中抽取与当前问题相关的 study-level population、intervention/comparator 和 outcomes。它不生成 question-level PICO，也不做文献筛选。

## 1. 数据来源

Cochrane benchmark source 来自本地 `sr-cleaned` 相关材料，并已冻结到：

```text
benchmark/online_pipeline/raw_data/
```

由于 `sr-cleaned/` 本身不提交，当前 benchmark 使用已冻结的最小 source snapshot。

Gold 字段来自 cleaned SR：

```text
characteristics_of_studies.included[*]
```

字段映射：

- `participants` -> `population`
- `interventions` -> `intervention_comparator`
- `outcomes` -> `outcomes`

`instances.jsonl` 只存 `article_ids`，不重复存全文内容。cleaned article content 按 article 写入：

```text
datasets/cochrane_study_pio/articles/
```

并通过 `article_index.jsonl` join。

builder 正常构建时读取：

```text
benchmark/online_pipeline/raw_data/cleaned_articles/
```

不会重新清洗 PMC XML。`raw_data/pmc_xml/` 只作为 provenance 保留，并在刷新冻结 cleaned article snapshot 时作为补充输入。

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
      <td><code>cochrane_study_pio</code></td>
      <td>428</td>
      <td>5</td>
      <td>209</td>
      <td>219</td>
      <td><a href="datasets/cochrane_study_pio/schema.md">schema.md</a></td>
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
      <td><code>question_pico</code>, <code>included_studies</code>, <code>article_ids</code>, <code>study_id</code>, <code>review_id</code></td>
    </tr>
    <tr>
      <td>Gold</td>
      <td><code>population</code>, <code>intervention_comparator</code>, <code>outcomes</code></td>
    </tr>
    <tr>
      <td>预测目标</td>
      <td>当前 included study 的一个 <code>StudyPIOCharacteristics</code> record</td>
    </tr>
    <tr>
      <td>指标</td>
      <td><code>macro_f1</code>, <code>micro_f1</code>, field precision / recall / F1, <code>critical_fields_complete_rate</code></td>
    </tr>
  </tbody>
</table>

## 4. 构建

```bash
PYTHONPATH=backend/src:. python benchmark/online_pipeline/benchmark.py build \
  --module study_pio \
  --source cochrane_study_pio \
  --dataset-name cochrane_study_pio \
  --seed 42
```

## 5. 运行示例

使用 LLM judge 的 smoke run：

```bash
PYTHONPATH=backend/src:. python benchmark/online_pipeline/benchmark.py run \
  --module study_pio \
  --dataset-name cochrane_study_pio \
  --split smoke \
  --method gold \
  --run-id cochrane-study-pio-smoke-gold \
  --limit 5 \
  --judge-mode llm \
  --llm-config llm.local.json \
  --resume \
  --workers 2
```

judge 会比较 study-level `population`、`intervention_comparator` 和 `outcomes` 的 semantic claims。每次 run 会实时写入 `judge_matches.jsonl`，中断后可以通过 `--resume` 继续。

`--judge-mode normalized` 保留用于本地快速测试和 debug，但不是 Study PIO 的主评估方式。

当前正式预测 method：

```text
study_pio.extraction_study_pico_slotwise_llm
```

历史 spec `study_pio.method_llm` 由 benchmark adapter 映射到同一个正式 method。旧 `method_rule` 不属于维护
源码；本地快照仅可放在被 Git 忽略的 `archive/` 中。

预测 runner 使用 `--workers` 对相互独立的 benchmark instances 做有界并发。每个 instance 调用
`RunStudyPIO(max_workers=1)`，避免与 runner 的 instance-level 并发形成嵌套线程池；输出与 artifacts 仍按
现有 runner 规则写入。
