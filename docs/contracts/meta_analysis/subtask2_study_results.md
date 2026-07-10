# Meta-analysis Subtask 2：研究级结果数据抽取契约

本文定义 Meta-analysis Subtask 2 的稳定业务契约。完整 workflow 顺序以
[`workflow_v3.md`](../../workflow_v3.md) 为准；具体实现与当前待定项见
[`docs/implementation/meta-analysis-subtask2.md`](../../implementation/meta-analysis-subtask2.md)。

## 任务目标与粒度

Subtask 2 从一项纳入研究对应的文章证据中，找回该研究可贡献给某个 review analysis setting（系统综述分析设定）
的研究级结果数据。

任务输入的 review setting 来自上游 workflow，通常包含 outcome（结局）、comparison（比较）、data type
（数据类型），并可能包含 timepoint（时间点）或 subgroup（亚组）约束。任务的调用单位是一个 review setting
与一个 study/article task；方法的输出可以包含多个文章原始粒度的结果候选。

review setting 可能比文章实际报告的结果设定更宽。例如 review 只要求短期结局，而文章分别报告 4 周与 12 周。
此时应保留两个文章报告的候选，不应仅为得到单一答案而合并、臆造或强行选择其中之一。

## 输入契约

每个抽取任务至少需要：

- `analysis_setting`：上游定义的 review setting。
- study/article task：当前研究、文章和 setting 的关联信息。
- `extraction_hint`：可选的非数值辅助上下文，例如上游保留的脚注或研究行注释。它只能辅助语义匹配，不能覆盖文章证据。
- article evidence：文章正文和原始表格 XML。

上游不应把 benchmark gold、目标行索引或评测规则作为 method 输入。

## 输出契约

方法返回 `StudyResultRow`。每个 row 使用统一的 `result_items[]` 表示当前研究在该 review setting 下的文章结果候选。
一个 result item 至少表达：

- article-local setting：文章实际报告的结局、比较、时间点、亚组、量表或统计口径等语义；只能保留原文支持的信息。
- `match_status`：该文章结果与 review setting 的语义关系。
- `result_data`：当前由文章证据支持的数值字段；可以完整、部分完整或为空。
- 状态与证据引用：说明该 item 是否可直接参与下游分析，或仍需恢复、选择或人工复核。

数值不得跨不同 result item 拼接。下游必须在单个 item 内判断字段是否齐全、是否可计算，以及是否能进入 estimate。

## 语义与不确定性边界

`match_status` 只表达语义对齐，不表达数值完整性：

- `matched`：文章报告的结果设定与 review setting 直接一致。
- `possible`：结果属于相同或兼容的结果家族，但 review setting 较宽，或文章没有清楚报告全部对齐维度，无法唯一确认。

`possible` 不是错误。在 review setting 宽泛时，多个 `possible` item 是对文章证据不确定性的正确表达，可由下游分析
或人工复核进一步处理。明显不兼容的文章结果不进入活跃 `result_items[]`。

## 证据与计算边界

- 原始表格 XML 必须交由 LLM 阅读；工程代码不得以确定性表格解析、行列清洗或数值提取替代文章表格理解。
- LLM 负责阅读证据、判断结果与数值材料的语义范围、选择兼容材料，并提出恢复或计算操作。
- 确定性工具负责算术、公式校验、结果组装与 trace 构造。LLM 不得静默计算最终数值，也不得在证据不足时生成新数值。
- 当直接结果缺失时，可以保留中间数值材料供后续恢复；若材料范围不清楚或与候选冲突，应保留不确定状态，而不是强行补值。

## 分层责任

- backend：实现真实 EBM workflow 的输入、输出和运行行为。
- benchmark：负责 dataset 构建、实例转换、gold、指标、诊断和实验产物。
- benchmark 专用的重排、归一化或判分逻辑不得反向改变 backend 的任务语义。
