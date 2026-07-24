# GRADE Indirectness Method

生产方法位于 `method_staged_applicability/`，公开输入仍为
`GRADEIndirectnessInput`，公开 domain judgement 契约不变。

## 当前流程

```text
typed GRADEIndirectnessInput
  -> result-blind P/I/C/O applicability classification
  -> deterministic concern grouping
  -> conditional result-blind clinical-threshold planning
  -> deterministic effect-range and weight profiling
  -> bounded evidence-body judgement
  -> validated output and deterministic rationale
```

分类 LLM 只接收 target、screening criteria、Study PIO 与 mapping，不接收 effect、CI、
weight、heterogeneity 或 subgroup result。Setting、subgroup、follow-up time 等信息只作为
P/I/C/O 的可选 facet；target 未规定的 facet 不构造差异，Study 信息缺失只进入 coverage，不能成为
indirectness concern。

工程层只把 `probably_not_sufficiently_direct` / `not_sufficiently_direct` 且具有可信效应差异机制的
factor 组成 concern group。临床阈值不是固定必调阶段：只有 concern 具备可比较的 more-direct 与
less-direct studies，或者存在 ratio measure 的 population baseline-risk concern 时才调用一次
threshold LLM。阈值调用保持 result-blind；每个 SoF outcome row 只产生一套 policy。

Ratio measure 的生成阈值使用绝对风险差尺度。没有上游 target baseline risk 时，LLM 只能明确生成
`model_scenario` 概率区间；它与 study observed control risks 分开保存，只能用于敏感性分析，不能单独
触发 downgrade。MD、SMD、RD、RR、OR 的效应映射与范围汇总由确定性代码完成，方法不重算 Meta-analysis。
非有限 effect、非法 RD、非正 RR/OR 与不可能的 ratio-to-risk 转换按行标记为不可分类；OR 的 baseline range
检查端点、中点和区间内极值点。

Meta-analysis weight 只有在所有贡献 DataRow 都有值且总和在 `0.001` 容差内等于 1 时才使用。缺失或总和非法时
记录 `incomplete`/`invalid`，不静默归一化，Judge 使用已有的 study/DataRow count。range 内的 count/weight
分布由确定性代码生成。

最终 judge 只能逐个评价冻结的 concern group，并使用 coverage、weight、effect-range concordance、
baseline sensitivity 与 direct-comparison status。它不能新建或修改 concern。`very_serious` 依据是否存在
重大 applicability limitation，不使用 concern 数量公式。其 JSON schema 根据当前 evidence 动态限定 group、
severity、coverage 和 baseline-risk 状态，减少模型先生成非法组合再由 parser 拒绝的波动。

三个实际 LLM stage（classification、conditional threshold、judgement）各自最多首次调用加一次 retry，
SDK retry 固定为 0，且本方法关闭共享 Client 的 JSON-marker 内部重试，真实 provider 调用不会绕过 stage 预算。
合法的 `not_needed`、`no_effect_only` 或 `unavailable` threshold 是业务状态；provider
失败或两次非法结构输出抛出带 stage 的稳定技术错误，不能转成临床 `unclear`。

成功结果的内部 trace 记录 stage 尝试次数、threshold gate、权重完整性、数值告警、baseline 计算点和 concern
range 汇总；产品公开的 GRADE domain judgement 字段保持不变。

历史 `method_llm` 与 `method_llm_twostep` 不属于维护源码；本地快照仅可放在被 Git 忽略的
`archive/` 中。Production factory、benchmark adapter 和维护测试均不依赖这些快照。

## 禁止输入

- benchmark gold label、alignment rationale 或测试代码；
- SoF comment、footnote 或 review conclusion；
- classification/threshold 阶段的 study effect、pooled effect、weight 或 observed control risk；
- 通过 contributing control arms 伪造的 target baseline risk。

开发纪律见 `development_guardrails.md`：方法以 GRADE/Cochrane 的真实工作流语义为准，不按单个 benchmark
case 打补丁。
