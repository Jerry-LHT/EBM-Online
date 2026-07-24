# 任务契约

本目录维护 Online EBM workflow 各模块的稳定任务契约。任务契约说明业务目标、输入输出、粒度、状态边界和
上下游责任，不记录某一版 method 的内部实现、实验结论或一次性调试过程。

实现细节见 `docs/implementation/`；完整 workflow 顺序与模块关系见 `docs/workflow_v3.md`。

## 当前契约

- [完整证据链 Workflow](workflow.md)
- [Q2PICO](q2pico.md)
- [Search Retrieval](search_retrieval.md)
- [Article Qualification](article_qualification.md)
- [Study Screening](study_screening.md)
- [Study PICO Extraction](study_pio.md)
- [Risk of Bias](risk_of_bias.md)
- [Meta-analysis](meta_analysis.md)
- [Meta-analysis Subtask 2：研究级结果数据抽取](meta_analysis/subtask2_study_results.md)
- [Four-domain GRADE Assessment](grade.md)
