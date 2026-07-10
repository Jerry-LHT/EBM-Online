# Meta-analysis Subtask 2：当前实现说明

本文描述当前源码中的 Subtask 2 实现，而非稳定任务契约。任务目标、输入输出与状态边界见
[`docs/contracts/meta_analysis/subtask2_study_results.md`](../contracts/meta_analysis/subtask2_study_results.md)。

## 入口与目录

当前公共 method 是 `method_source_local_candidate_extraction`：

```text
backend/src/ebm_backend/online_pipeline/infrastructure/methods/meta_analysis/
  subtask2_study_results/
    method_source_local_candidate_extraction.py
    source_local_candidate_extraction/
```

benchmark adapter 将 benchmark instance 转换为 workflow 输入后，通过 backend method loader 调用该 method。
backend 运行时不依赖 benchmark 代码、dataset 或 gold。

## 当前已实现链路

### 1. 任务编排

`orchestrator.py` 从 `study_result_tasks` 或 `study_result_targets` 构造每个 study/article task。不同 task 可并行执行，
结果按原任务顺序回填。`context.py` 根据数据类型确定必需字段：

- 二分类（dichotomous）：两臂的 events（事件数）与 totals（总人数）。
- 连续型（continuous）：两臂的 mean（均值）、SD（标准差）与 total（总人数）。

### 2. 来源准备与候选发现

`source_catalog.py` 可以建立文章来源目录；但当前 `orchestrator._prepare_sources()` 仅将 table source 送入主流程。
每张表以 raw XML 作为单独读取单元。对每个来源，系统并行运行：

- `discover_candidates.txt`：提出文章原始粒度的候选结果及 `matched` / `possible` 等语义状态。
- `profile_source.txt`：生成供后续 recovery 使用的来源概况。

只有 `matched` 与 `possible` 候选进入数值完成阶段；数据类型明确不兼容的候选会降为非活跃状态。

### 3. 候选数值完成

`completion.py` 对每个活跃候选独立执行：

1. 从候选发现时关联的 source 读取材料。
2. 按二分类/连续型和 table/text 选择对应的 material extraction prompt。
3. 调用 field resolution prompt，将材料映射到目标字段、标记可计算字段或保留未解决字段。
4. 对确定性计算计划调用 `tools/calculators.py`。
5. 仍有 open need（未解决字段）时，从尚未读取的 source 中选择恢复来源，提取补充材料后再次 resolution 与计算。

当前 calculator 支持常见事件数/百分比/总人数关系、事件与非事件关系、SE 或 CI 推导 SD、以及受高置信度与无未验证假设限制的通用表达式。工具只做计算与校验，不判断文章语义。

### 4. 输出与可观测性

`finalizer.py` 将候选组装为 `StudyResultRow.result_items[]`：

- 单个 `matched` 且字段完整的 item：`ready_for_estimate`。
- `possible` 即使字段完整，仍为 `needs_resolution`。
- 多个活跃 item：wrapper 标记为 `ambiguous`。
- 无活跃 item：wrapper 标记为 `data_unavailable`。

运行中会在 debug 目录写入 source preparation、candidate discovery、材料读取、resolution、calculation、recovery 和 final row
等 checkpoint。并发受 task、source、source skill、candidate、initial source 和全局 LLM in-flight 配置限制。

## 已存在但尚未在主链启用的能力

仓库中已有 text 的 material/recovery prompt 模板，但当前来源准备只选择 table。因此正文 source 的 discovery、材料读取与
recovery 尚未在该公共 method 的主链启用。是否启用、如何切分文本和如何控制上下文，应在完成任务设计与评测后再决定。

## 待定与需要继续验证的部分

- 候选发现的召回稳定性：需要在 key-filter 的 dev/test 集上持续按单 item 指标验证，不能只依据单个 bad case 调整 prompt。
- 跨 source recovery：当前已实现选择未读 source、补材料、重新 resolution 的机制，但语义绑定质量与恢复收益仍需系统审计。
- 复杂 raw XML 表格：LLM 读取是既定边界，行列理解、共享对照和多臂材料的可靠性仍需通过代表性 case 与测试集评估。
- 连续型与二分类计算：现有 calculator 覆盖常见恢复路径；新的公式应先明确材料语义、准入条件和 deterministic validation，再加入工具。
- 性能：当前存在多层并行与 debug checkpoint，但 source 数、候选数、恢复轮次和 LLM 并发仍需要依据实际运行指标平衡成本与召回。

## 验证入口

- 单元测试：`PYTHONPATH=backend/src:. pytest tests/unit/meta_analysis/subtask2 -q`
- 快速回归：使用 `cochrane_meta_v2-key-filter-dev4`。
- 审计评测：使用 `cochrane_meta_v2-key-filter-test78`。

运行参数与 item-level 指标见 Subtask 2 benchmark
[`README`](../../benchmark/online_pipeline/meta_analysis/subtask2_study_results/README.md)。
