# Study Screening 实现说明

本文档记录 `study_screening` 模块当前的真实后端实现边界。

当前实现目标不是 benchmark 标签拟合，而是独立后端里可复用的真实 EBM 候选全文排纳能力。

## 1. 模块职责

`study_screening` 负责完成这条业务链路：

```text
question_text + QuestionPICO + constraints + retrieved articles
-> criteria planning
-> criterion-wise article judgment
-> binary include/exclude aggregation
-> StudyScreeningResult
```

它对应的是 retrieval 之后、进入后续 study PIO / risk of bias / synthesis 之前的正式排纳步骤。

## 2. 分层边界

Application 负责编排 screening 的主流程：

```text
RunStudyScreening.execute(question_text, question_pico, constraints, articles)
```

当前分层里，Application 负责：

- 接收 screening 输入
- 调 infrastructure method
- 返回 `StudyScreeningResult`

Infrastructure 负责具体能力实现：

- criteria planning prompt
- article criterion judgment prompt
- article section selection
- criterion judgment aggregation
- LLM 调用与 JSON 解析

调用方向保持为：

```text
interfaces/api -> application/use_cases -> application/ports -> infrastructure/methods
```

当前主调用链是：

```text
POST /modules/study-screening
-> interfaces/api/routes_modules.py
-> interfaces/api/dependencies.py
-> application/use_cases/run_study_screening.py
-> application/ports/evidence_review.py
-> infrastructure/methods/study_screening/
```

## 3. 当前实现结构

当前正式 method 为：

```text
default
```

当前目录结构：

```text
backend/src/ebm_backend/online_pipeline/infrastructure/methods/study_screening/
  method.py
  factory.py
  criteria_planner.py
  article_screener.py
  section_selector.py
  prompts/
    study_screening_criteria_planning_v1.txt
    study_screening_article_criterion_judge_v1.txt
```

## 4. 方法设计

当前方法采用两段式设计：

1. `criteria_planner`
2. `article_criterion_judge`

### 4.1 Criteria planning

输入：

- `question_text`
- `QuestionPICO`
- `WorkflowConstraints`

`WorkflowConstraints.publication_year_range` 是可选年限过滤约束。若提供，工程侧会确保它进入 `ScreeningCriteria.inclusion_criteria`。

输出：

- `ScreeningCriteria.inclusion_criteria`
- `ScreeningCriteria.exclusion_criteria`
- `ScreeningCriteria.rationale`

目标是把 review question 操作化成可执行的排纳 rubric，而不是机械重复 PICO 文本。

### 4.2 Article criterion judgment

对每篇 `CleanedArticle`：

- 先用 deterministic section selection 选出 screening 相关 sections
- 再用 LLM 逐条判断 criterion

这一阶段只接收 `ScreeningCriteria` 和候选文章 evidence bundle。它不再重复接收 `QuestionPICO`、PMID、PMCID 等上游识别信息；发表年份作为 article metadata 保留，因为它可能用于判断年限过滤 criterion。

LLM 只输出：

- `yes`
- `no`
- `unclear`

以及：

- 简短 `reason`
- `evidence_spans`
- `overall_note`

LLM 不直接决定最终工程态 `include/exclude`。

### 4.3 Binary aggregation

最终 decision 由代码聚合：

- 任一 exclusion criterion = `yes` -> `exclude`
- 任一 inclusion criterion = `no` -> `exclude`
- 其他情况 -> `include`

这意味着：

- prompt 内部允许 `unclear`
- 最终 API 仍然保持二元 `include/exclude`
- 默认采用保守映射：没有明确排除信号时，不因 `unclear` 自动排除

## 5. EBM 语义约束

当前 prompt 与方法约束遵循真实 EBM screening 语义，而不是 benchmark 拟合：

- 只根据文章中明确证据判断，不脑补未写出的研究细节
- `outcome` 默认不是硬性纳排标准，除非问题本身明确把某 endpoint 当 eligibility definition
- 若提供 `publication_year_range`，它会作为显式 eligibility criterion 进入 screening
- 不因结果不完整、没有可提取数值、或 outcome 未按后续 synthesis 需要的格式报告而排除文章
- 优先依据 title、abstract、methods、participants、interventions、results 等 section 判断 eligibility

## 6. 当前输入语义

当前 `study_screening` 使用的是检索后的 `CleanedArticle` 列表。

需要明确：

- 当前 `study_id` 实际上仍是 article-level proxy
- 当前模块还没有实现多报告合并后的真正 study-level collation
- 因此本版 screening 更准确地说是：
  `retrieved full-text-capable article screening`

这和 Cochrane 严格意义上的 study-level collation 仍有差距，但足以承接当前后端 workflow。

## 7. 测试

单元测试按模块放在：

```text
tests/unit/study_screening/
```

覆盖：

- section selection
- criteria planner
- article screener
- method aggregation
- use case delegation
- factory

真实外部冒烟测试放在：

```text
tests/integration/study_screening/test_live_llm_screening.py
```

默认关闭，需显式打开：

```bash
RUN_LIVE_LLM_TESTS=1 PYTHONPATH=backend/src:. pytest tests/integration/study_screening/test_live_llm_screening.py -q
```

## 8. 非目标

首版明确不做：

- active learning / ranking
- 多 reviewer / 多 agent 协商
- multi-report study collation
- benchmark-specific criteria patch
