# 文档

`workflow_v3.md` 是当前分支维护中的 workflow 规范文档。

## 当前文档

- [Online EBM Workflow 规范](workflow_v3.md)
- [Meta-analysis 自动化 Evidence Agent 解决方案（source-workspace production method）](meta-analysis-agentic-solution.md)
- [任务契约](contracts/README.md)
- [完整证据链 Workflow 任务契约](contracts/workflow.md)
- [Q2PICO 任务契约](contracts/q2pico.md)
- [Search Retrieval 任务契约](contracts/search_retrieval.md)
- [Article Qualification 任务契约](contracts/article_qualification.md)
- [Study Screening 任务契约](contracts/study_screening.md)
- [Study PICO Extraction 任务契约](contracts/study_pio.md)
- [Risk of Bias 任务契约](contracts/risk_of_bias.md)
- [Meta-analysis 任务契约](contracts/meta_analysis.md)
- [Meta-analysis Subtask 2 任务契约](contracts/meta_analysis/subtask2_study_results.md)
- [Four-domain GRADE Assessment 任务契约](contracts/grade.md)
- [实现文档](implementation/README.md)
- [Backend 框架文档](../backend/README.md)
- [Online Pipeline Benchmark 文档](../benchmark/online_pipeline/README.md)

## 说明

历史架构、设计、指南和计划文档在当前分支中不再维护，已归档到 `archive/`。

当前分支维护七个模块级 API、`POST /workflow` 完整证据链 API，以及 benchmark 直接调用的内部 Python
methods。子任务级 HTTP API 不属于当前分支契约。

七个 module-level API 均已接入专用 application use case 和 module-specific infrastructure factory。
各模块的当前调用边界、concrete adapter、已知限制和测试方式以 `implementation/` 目录中的实现文档为准。
