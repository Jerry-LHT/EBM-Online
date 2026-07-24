# Q2PICO 任务契约

本文定义 Q2PICO 的稳定业务契约。完整 workflow 顺序见
[`workflow_v3.md`](../workflow_v3.md)；当前代码组织、prompt 和测试方式见
[`docs/implementation/q2pico.md`](../implementation/q2pico.md)。

## 任务目标与粒度

Q2PICO 将一个自然语言临床问题转换为结构化 `QuestionPICO`。调用单位是一个 clinical question
（临床问题）。

这是一个业务任务。问题中显式 outcome 的识别和可选的 protocol-oriented outcome planning 是该任务的
内部处理阶段，不构成两个独立 workflow 模块。

## 输入契约

任务输入包括：

- `question_text`：必填、非空的自然语言临床问题。
- `expand_outcomes`：可选 boolean，默认 `true`；控制是否生成候选 review outcome domains。调用方可显式传
  `false`，只保留原问题支持的显式 `O`。

输入不得包含 benchmark gold、预期 PICO 标签或下游分析结果。

## 输出契约

任务返回 `QuestionPICO`：

- `P`：问题支持的 population、participants、condition、setting 或 subgroup。
- `I`：问题支持的 intervention、treatment、exposure 或 management option。
- `C`：问题支持的 comparator、control、placebo、usual care 或 alternative option。
- `O`：问题明确表达的 outcome domain 或 endpoint（结局领域或具体终点）。
- `O_expanded`：默认生成的 protocol-oriented candidate outcome domains；显式关闭 outcome planning 时为空列表。

五个字段始终存在，类型均为 `list[str]`。问题没有表达某个 `P/I/C/O` slot 时，对应字段为空列表，
不得为了填满 PICO 而臆造信息。

## Outcome 语义边界

`O` 与 `O_expanded` 必须保持来源区分：

- `O` 是 source-faithful extraction，只表达原始问题支持的信息。
- `O_expanded` 是规划候选，可以补充对决策重要的获益或伤害 outcome domains，但不能伪装成原问题内容。

`O_expanded` 不是完整的 protocol outcome specification。完整 specification 还可能需要 outcome importance、
benefit/harm 属性、measurement instrument、metric、aggregation method 和 time point。

## 上下游责任

- 上游负责提供原始问题，不应先把 benchmark 标注写入问题文本。
- Q2PICO 负责结构化问题，不负责生成检索式、检索文章、研究纳排或 synthesis setting。
- Search Retrieval 负责从 `QuestionPICO` 选择适合检索的概念，不应机械使用全部 PICO slots。
- 下游不得把 `O_expanded` 解释为用户明确声明的 outcome，也不得视为已批准的 protocol outcome set。

## 失败与非目标

空 `question_text` 是无效输入。单个 slot 返回空列表不是任务失败；这表示问题没有支持该 slot 的信息。

每个必需 LLM stage（`P`、`I`、`C`、`O`，以及启用时的 `O_expanded`）最多尝试两次：初次调用失败后，
只重试失败的 stage 一次，不重跑已经成功的 slot。任一必需 stage 在第二次尝试后仍失败时，整个 Q2PICO
任务失败，不返回部分 `QuestionPICO`。

本任务不负责：

- 完整 protocol 编写或 outcome set 审批；
- 检索式设计和数据库查询；
- 从文章中提取 study PICO 或研究结果；
- GRADE、risk of bias 或 meta-analysis 判断。
