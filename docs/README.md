# 文档

`workflow_v3.md` 是当前分支维护中的 workflow 规范文档。

## 当前文档

- [Online EBM Workflow 规范](workflow_v3.md)
- [任务契约](contracts/README.md)
- [Meta-analysis Subtask 2 任务契约](contracts/meta_analysis/subtask2_study_results.md)
- [实现文档](implementation/README.md)
- [Backend 框架文档](../backend/README.md)
- [Online Pipeline Benchmark 文档](../benchmark/online_pipeline/README.md)

## 说明

历史架构、设计、指南和计划文档在当前分支中不再维护，已归档到 `archive/`。

当前分支维护的后端接口边界是模块级 API，以及 benchmark 直接调用的内部 Python methods。workflow 级 HTTP API 和子任务级 HTTP API 不属于当前分支契约。

当前实现状态上，`q2pico`、`search-retrieval` 和 `study-screening` 已经接入正式后端实现；它们的调用边界、application/infrastructure 分层和测试方式以 `implementation/` 目录中的实现文档为准。
