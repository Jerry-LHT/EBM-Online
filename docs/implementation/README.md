# 实现文档

本目录维护后端实现层面的文档。

设计文档回答“系统应该是什么”，实现文档回答“代码应该怎么落地、边界在哪里、后续开发按什么规则推进”。

当前这组文档描述已收口的后端实现，以及仍在迭代中的模块实现状态。不要把某个模块的完成状态自动外推到其他模块。

## 当前文档

- [后端框架实现设计](backend-framework.md)
- [Q2PICO 实现说明](q2pico.md)
- [Search Retrieval 实现说明](search-retrieval.md)
- [Study Screening 实现说明](study-screening.md)
- [Meta-analysis Subtask 2 当前实现](meta-analysis-subtask2.md)

## 当前覆盖范围

当前实现文档重点覆盖已经完成后端重构收口的部分：

- `q2pico`
- `search_retrieval`
- `study_screening`
- 这三个模块对应的 application / infrastructure / interface 分层约束

Meta-analysis Subtask 2 已有一个可运行的公共 method，但其候选召回、复杂表格读取与 recovery 仍在持续验证，
不应视为完全收口的实现。

其他模块仍可能处于过渡态，代码应以仓库中的当前实现为准，后续在进入真实开发前再分别补实现文档。

## 文档原则

- 记录稳定的实现边界，不记录一次性调试过程。
- 优先说明业务能力、调用链、模块职责和测试方式。
- 不让 benchmark、实验 method 或具体技术实现反向定义正式后端架构。
- 当实现与设计发生偏差时，先更新实现文档，再调整代码。
- 如果某个模块仍处于过渡期，要明确写出“当前已收口部分”和“仍保留的兼容层”，避免文档把局部状态误写成全局完成状态。
