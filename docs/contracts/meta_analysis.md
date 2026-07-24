# Meta-analysis 任务契约

本文定义 Online EBM workflow 中 Meta-analysis 阶段的稳定业务契约。当前实现见
[`Meta-analysis 实现说明`](../implementation/meta-analysis.md)，Subtask 2 的细化语义见
[`Study-level Result Data Extraction`](meta_analysis/subtask2_study_results.md)。

## 任务目标与边界

Meta-analysis 把问题级计划、已纳入研究的文章证据和研究内候选结果转换为可审计的统计分析数据集与
effect estimates。当前流程为：

```text
result-blind Synthesis Plan
  -> per-article Evidence Agent over all frozen targets
  -> table-local ResultBlock candidates
  -> result-blind article resolution and verification
  -> SynthesisAnalysisDataset
  -> Analysis Method Decision
  -> Overall/Subgroup estimates
```

这里的 Synthesis Plan 是拆分后的、仅属于 Meta-analysis 的 protocol fragment，不是完整系统综述
protocol。Study PIO 与 Risk of Bias 是 screening 后的平行业务分支，不是 Meta-analysis 输入；它们以后
由 GRADE 使用。

本契约的方法学边界依据 Cochrane Handbook：Chapter 3 要求对一项研究内的多个 outcome/measure/
timepoint 使用事先规定且与结果无关的选择规则；Chapter 9 把 protocol-stage synthesis PICO 与纳入研究后
的 study-characteristic/data-availability 检查区分为不同阶段；Chapter 10 要求在合并前先明确数据类型、
effect measure 与临床可合并性。参见 [Chapter 3](https://training.cochrane.org/handbook/current/chapter-03)、
[Chapter 9](https://training.cochrane.org/handbook/current/chapter-09) 和
[Chapter 10](https://training.cochrane.org/handbook/current/chapter-10)。

## 输入契约

- `review_id`：当前 review 的稳定 ID。
- `question_text` 与 `question_pico`：临床问题及其结构化 PICO。
- `screening_criteria`：已经冻结的 review 纳排标准；只供 Meta Synthesis Plan 理解 review scope。
- `included_studies`：Study Screening 确定的 study/article IDs。
- `articles`：与 `included_studies` 严格一一对应的 `CleanedArticle[]`，包含清洗 XML 正文与原始表格材料。

Subtask 1 只接收 `review_id`、问题、PICO 与 `screening_criteria`。它不得接收或读取 articles、included
study IDs、Study PIO、Risk of Bias 或 observed result data，以避免事后根据研究结果改变计划。
完整 workflow 在正式 Screening 前调用该 planning capability，并把同一个 frozen
`MetaAnalysisSynthesisPlan` 传入后续 Meta execution；独立 Meta API 未预先提供 plan 时仍在 execute 开始处调用
同一 planner。两条路径的 prompt、输入语义、plan schema 和统计行为相同，不会因执行位置提前而读取文章。
当前 plan version 为 `5`。每个 target 自身绑定一个结构化 `timepoint`，明确 label、strategy、
target/window、unit、anchor、planning basis 与 rationale；`ResultSelectionPolicy` 冻结 outcome measure、
analysis population、continuous endpoint/change frame、statistic type 与 source priorities，以及无法消解并列时的
`unresolved` policy。MD 可以按冻结 priority 同时允许 `post_intervention` 与 `change_from_baseline`；SMD 必须
只冻结其中一种 frame。
timepoint 不在 selection policy 中重复保存，也不再使用自由文本 `best_semantic_match`。上游未规定细节时可使用有
明确 rationale 的 result-blind `clinical_convention`；无法形成可辩护规则时以
`insufficient_planning_basis` 停止该 target。
Version 5 还为 subgroup target 冻结 `scope`（`study_level` 或 `participant_level`）与
`membership_relation`。参与者亚组只有在两个 level 明确互斥时才具备研究内交互计算资格；该元数据来自
result-blind plan，不由 Subtask 2 从结果数值推断。

Study Evidence 阶段以一篇 article 为任务，一次接收全部冻结 `SynthesisTarget[]`。它允许在 review target
较宽时返回多个更细的 article-local candidates；不得为了强制一篇 study 只返回一行而损失候选召回。Candidate
Discovery 只读取当前调用的 raw table（caption、hierarchical headers、rows、footnotes），不读取 abstract、
Methods、其他正文或其他 table。正文只能按需建立 trial design、arm meaning、follow-up 和 analysis population
的 `StudyMap`，不能用于发现数值或补写当前表未建立的 arm/value mapping。

一个 candidate 是单张表中的一个 `ResultBlock`：同一 outcome、measure/unit、timepoint、population/subgroup、
analysis population、result frame 和 statistic definition 下的全部 arms。`population_or_subgroup`（临床样本/
亚组）与 `analysis_population`（统计分析集，例如 ITT、mITT、PP）必须分开；未明确表达时保留为空。
Continuous candidate 的 endpoint/change frame、change definition 和 scale direction 也只能来自当前表。

内部 method 名称不属于 HTTP 或 application 契约。

## 输出契约

`MetaAnalysisResultPackage` 包含：

- `synthesis_plan`：`MetaAnalysisSynthesisPlan`，含 plan version/hash、零到十二个冻结 targets，以及
  `unsupported_targets` 对当前无法进入统计流程的 outcome 及原因的记录。
- `study_result_rows`：Subtask 2 原始宽召回输出；保留每个 study/target 的 candidate result items。
- `candidate_resolution_records`：每个 target × study 的 resolved、unresolved、data_unavailable、
  unsupported_dependency 或 technical_failure 决定、操作、来源 candidates 与原因。
- `meta_analysis_data_rows`：Candidate Resolution 后的正式单研究分析行；包含确定的臂级数据，或连续型 MD 的
  direct effect + SE 通用逆方差数据，并在
  Subtask 4/5 后补全单研究 effect、CI、variance、standard error 与当前 estimate 的 weight。
- `synthesis_analysis_datasets`：统计门禁与审计对象；通过 `data_row_ids` 引用当前 setting 可进入
  Subtask 3–5 的 data rows，不再嵌入 `selected_study_results`。
- `analysis_settings`：在 candidate resolution 后形成的最终分析单元；包含冻结 target 的
  `population_scope`，`eligible_study_ids` 是实际已消解的 studies。
- `analysis_methods`：每个 setting 的 effect measure、analysis model、统计方法、interval method、
  `statistical_policy_id` 与实际 evidence body。
- `subgroup_estimates`、`subgroup_difference_tests` 与 `overall_estimates`：可计算时产生的统计结果；estimate
  通过 `included_data_row_ids` 连接单研究贡献，并继续保留 `included_study_ids` 供 GRADE/SoF 使用。

`MetaAnalysisDataRow` 在 Resolution 后首先以 `analysis_status = pending` 进入 Subtask 3。Subtask 4/5 只对
当前支持且由 method 纳入的 rows 计算统计字段；最终结果包中每行必须为 `included`、`excluded` 或
`not_analyzed`，不得残留 `pending`。`included` 行必须有 `analysis_effect`、展示尺度的 `effect_value`/CI、
`variance`、`standard_error`、未归一化 `weight` 与 0–1 `weight_fraction`；同一 computed estimate 内
`weight_fraction` 总和约为 1。RR/OR 在 log scale 计算但在原始比例尺度展示。

下游 GRADE 通过 matched estimate 的 `included_data_row_ids` 取得这些正式分析行。当前
`risk_of_bias` 使用完整且归一化的 `weight_fraction` 表达各研究对证据体的信息贡献，`inconsistency`
同时使用单研究 effect/CI/analysis scale 与 `weight_fraction` 构造定量证据画像。GRADE 不从原始事件数、
mean/SD/N 或样本量重新推断 Meta weight；权重不完整时按各 domain 自身契约显式降级为 unavailable/fallback。

`target_id` 在下游复用为 `setting_id`，从计划、候选、消解、dataset 到 estimate 保持稳定连接。
`setting_family_id` 由 review、comparison、outcome/measure、timepoint、data type、effect measure 与可执行的
selection-policy 字段组成，不包含 subgroup level、rationale、decision-basis 文案或 planning-basis provenance；
同一 overall/subgroup analysis family 使用同一 ID。
`candidate_id` 只属于 article-local candidate 与 resolution provenance，不属于 final `AnalysisSetting`、
`OverallEstimate`、`SubgroupEstimate`、`SubgroupDifferenceTest` 或 GRADE SoF row。旧 benchmark 数据仍需要该
评测 join key 时，由 benchmark adapter 在 backend 输出之后补回，不能污染 backend runtime contract。

## 统计参考政策

当前稳定政策 ID 为 `cochrane_revman_v1`，参考基线冻结于 2026-07-16。政策来源优先级固定为：

1. Cochrane Handbook 的适用边界、解释与推荐；
2. RevMan 公布的统计算法；
3. 前两者未规定时采用可引用的原始统计方法文献；
4. benchmark gold 仅用于回归诊断，不得覆盖前三层。

当 gold 与实现不一致时，必须先分类为输入数据、方法配置、参考版本或公式实现差异。只有公式实现差异才修改
计算代码；方法/版本差异通过显式 metadata 与 versioned fixture 保留。政策升级必须产生新的 policy ID、迁移说明
和新旧参考测试，不静默改变 `cochrane_revman_v1` 的含义。

所有二分类 estimate 的 `effect_direction_convention` 固定为 `experimental_relative_to_control`；RR/OR 表示实验组
相对对照组，RD 表示实验组风险减对照组风险。该字段说明方向约定，不声明某个方向一定代表临床获益。

## Article Resolution 规则

Resolver 在一篇文章内同时处理全部 targets，但仍为每个 target 产生独立决定：

1. LLM 只读取 target semantics、StudyMap、candidate setting、arm labels、字段可用性和 uncertainty；不读取
   result magnitude、效应方向、置信区间或 P 值。
2. 优先选择一个完整 table-local ResultBlock。唯一性、数值完整或结果更有利都不能替代 comparison、outcome、
   measure、timepoint、population/subgroup、analysis population、data type 和冻结选择政策的一致性。
3. 选中的结果必须回到对应 raw table 独立验证。最多接受一次证据明确的 correction；无法明确修正时为
   `unresolved`。
4. 每个 study 对每个 target 最多形成一个 contribution。多臂可以在同一 block 内选择多个 eligible arms；
   二分类加总 events/totals，连续型使用样本量加权 mean 与正式 pooled-SD 公式。所有算术和 primitive validation
   由代码执行，LLM 不计算。连续型 MD 也可从同一表格中直接报告的 MD + SE/双侧 CI 形成 GIV contribution；
   LLM 判断比较作用域和方向，代码完成 CI 到 SE、方向归一与统计合并。
5. 跨表只允许补充同一结果缺失字段，并要求每个来源都明确相同 outcome/measure、timepoint、statistic
   definition、analysis population、result frame、subgroup、arm identity 和 unit；每个借用字段必须有
   candidate/table/arm provenance。Randomized 或 baseline N 不能自动当作 analyzed denominator。
6. 身份字段缺失、字段冲突、arm alias 不唯一、跨表 provenance 不完整或必要依赖不清时保持
   `unresolved`/`unsupported_dependency`，不得猜测。
7. Continuous contribution 保留原始 mean/SD/N，并输出确定性 `effect_multiplier`。MD multiplier 统一
   endpoint/change 的减法方向；SMD multiplier 同时统一 change 定义和量表高低方向。方差和权重不变。

因此 `study_result_rows` 是候选层，不是统计输入；`meta_analysis_data_rows` 是唯一统计行，
`SynthesisAnalysisDataset.data_row_ids` 是统计门禁。

## 执行、并发与失败语义

- 所有 Meta LLM 外呼受统一 client 的进程级 32 请求并发上限约束。
- Application 最多以 16 个 workers 并发处理独立 articles；每篇文章一次处理全部 targets。
- 单篇文章内最多并行抽取四个独立 table bundles；最多读取 32 个 table windows，investigation 最多两轮、
  六个 section queries 和八个 section windows。默认 bootstrap 只使用其中一部分，为后续按需 search/read 保留预算。
- Subtask 4 与 Subtask 5 在 Subtask 3 完成后并行执行。
- 并发输出始终按 plan target 顺序及 `included_studies` 顺序组装，保证确定性。
- 某 study 没有可用于 target 的 table-local candidate 是业务结果，不是整个请求异常。输出同时保留
  `extraction_status_reason`：`no_eligible_table_candidate` 表示完整表格覆盖未发现同数据类型候选，
  `no_compatible_table_candidate` 表示有表格候选但没有兼容的比较/结局/时间点/字段。正文中报告但不满足
  raw-table candidate 边界的结果必须在 reason detail 中明确说明，不能表述为文章完全没有数据。
- 某 article 的 provider/output error 在 retry 后仍失败时记为 `technical_failure`，coverage 明确不完整；其他
  articles 继续，不能把技术失败伪装成无数据。配置、输入、adapter contract 或程序错误仍使整个请求失败。
- `technical_failure` 是顶层业务状态，不再是唯一诊断标签。每条失败 resolution 与 dataset provenance 同时保留
  `failure_code`、有界 `failure_detail` 及 stage/attempt/status/request metadata。当前稳定细类包括
  `provider_timeout`、`provider_upstream_connection_error`、`provider_server_error`、
  `provider_rate_limited`、`provider_authentication_error`、`provider_request_rejected`、
  `provider_transport_error`、`provider_incomplete_response`、`invalid_model_json` 和
  `invalid_model_output`。请求在调用前无法放入配置的 context window 时使用 `context_budget_exceeded`。当前还细分
  `model_output_source_scope_violation` 与
  `model_output_footnote_provenance_invalid`。模型输出违反业务校验与 provider 调用失败必须分开统计。
  混合失败还保留逐 attempt history，避免只看最后一次错误而丢掉先前的 timeout、HTTP 或 validation 失败。
- Planning 和 Evidence Agent 的实际 LLM 调用均为首次加一次 retry；SDK 与
  JSON-marker 隐式 retry 被关闭。只有标记为 retryable 的 provider 错误以及 LLM 输出契约错误进入第二次调用，
  非可重试 provider 错误立即失败，未知程序异常不 retry。
- Synthesis Planning、table census、investigation、arm reconciliation、resolution、source verification 和
  cross-source adjudication 均使用 strict JSON Schema；
  第二次仍失败时保留有界 validation reason 供审计。

HTTP 稳定错误码为 `meta_analysis_configuration_unavailable`、
`meta_analysis_stage_invocation_failed`、`meta_analysis_stage_retry_exhausted`、
`meta_analysis_invalid_method_output` 和 `meta_analysis_invalid_input`。配置缺失或 provider 失败不得伪装成
`data_unavailable` 或空结果；`data_unavailable` 只表示文章证据中确实没有可用候选。
Meta provider/output 错误响应还携带上述 `failure_code` 与有界详情；对外稳定 HTTP code 与内部失败细类承担不同
层次的职责。

`included_studies` 不得重复；每个 ID 必须严格匹配且只匹配一篇 `CleanedArticle.study_id`。缺失或重复
匹配直接失败，不静默跳过。

## 当前能力与限制

- 支持 pairwise `Dichotomous` arm-level data，以及 `Continuous` arm-level data 或直接报告的 MD + SE/CI。
- Synthesis Planning 必须将其他数据形态记录为 `unsupported_targets`，不得把它们强制映射为二分类或
  连续型；没有 supported target 时，后续抽取与统计阶段不执行。
- 支持二分类 RR、OR、RD，以及连续型 MD、Hedges g SMD；冻结计划必须给出与 data type 兼容的效应量。
- SMD 统一为 `positive_favors_experimental`；量表方向不明的 study 以
  `uncertain_smd_scale_direction` 排除。Change-score 减法方向不明时以
  `uncertain_change_score_definition` 排除。
- Method Selection 只实现冻结计划，不推断 effect measure 或 model。缺少效应量或 common/varying-effects
  假设时返回 `invalid_plan`；效应量与数据类型不兼容时返回 `incompatible_effect_measure`，且不根据
  heterogeneity test 补选模型。
- common-effect 二分类使用 Mantel–Haenszel，common-effect 连续型使用 inverse variance；random-effects
  使用 inverse variance；研究数至少为 2 时使用 REML，当前 method realization 使用 Wald 95% CI。
  单研究 target 若计划为 varying-effects，仍保留 random-effects 语义，但不声称可估计 between-study
  heterogeneity。Overall prediction interval 仅在 random-effects 且研究数至少为 5 时启用；Wald 使用
  标准正态临界值，实际采用 HKSJ 时使用相应 t 临界值。Subgroup estimate 当前不声明 prediction interval。
- Hedges g 的研究内方差使用 RevMan 的 `N - 3.94` 小样本公式。Random-effects + REML 的 I² 使用
  τ² 与 typical within-study variance 定义；common-effect 继续报告 Q-based I²，并通过 `i2_method` 区分。
- RR/OR 的 continuity correction 只用于需要修正的单研究 effect/variance；固定效应 MH 汇总继续使用观察到的
  2×2 counts。RD 不因零单元格自动修正；双零事件研究可进入固定效应 MH-RD，但不能进入会产生无限权重的
  inverse-variance 分析。
- `study_level` subgroup difference 使用独立 study evidence bodies 的 Q-between 检验。`participant_level`
  subgroup 仍分别输出 subgroup estimates；正式检验只支持恰好两个、明确互斥且至少两项研究同时报告两层的
  情况，先计算每项研究内 interaction 再跨研究汇总。重叠、关系未知、超过两层或配对研究不足时返回明确的
  `not_applicable`/`insufficient_paired_studies`，不猜测协方差。
- 当前 direct-effect GIV 只支持 natural-scale Mean Difference；不支持 direct SMD、ratio measure 的 log-scale
  GIV、仅有 P value 的反推，或从正文/图片发现新的 candidate。直接效应的 participant count 无可靠证据时为空，
  不阻止 Meta 估计，但需要样本量的 GRADE domain 可以返回 `unclear`。
- Study Screening 已排除 cluster/crossover 和其他非个体随机平行组设计；Meta 不重新识别这些设计，也不实现
  cluster/crossover adjustment。当前仍不处理 time-to-event、rate、ordinal、count 或 adjusted contrast-only data。
- 完整 workflow 的 staged Screening 只把至少一个 frozen target 可映射为当前 arm-level 或 direct-MD contract 的文章送入
  Meta。方法学上合格但只有当前不支持的 representation 的文章保留在 Screening audit 中；
  Meta extraction/resolution/statistics 本身未因此修改。
- Multi-arm shared-control 在 arm identity、临床等价性与 control primitive data 均确认时可合并；共享组拆分、
  network meta-analysis 和无法确认的 dependency 仍不支持。
- Meta-analysis 不重新 screening，不评估 Risk of Bias，也不产生 GRADE judgement。

## 当前收敛范围

当前 production contract 以“个体随机、平行组、pairwise、arm-level 二分类或连续型数据”为收敛边界。
在该边界内，计划、表格候选抽取、Candidate Resolution、`MetaAnalysisDataRow`、方法选择、overall/subgroup
estimate、正式 participant-level interaction 条件、单研究 weight 及 GRADE handoff 已形成完整链路。
`cochrane_revman_v1` 的现有方法矩阵与上述输入/失败语义视为稳定行为；后续只在真实失败案例、权威方法政策
升级或下游契约变化时重新打开设计。

“已收敛”不表示支持所有系统综述统计场景。复杂表格中 endpoint、change 与 adjusted contrast 同时出现时，
LLM 仍可能无法形成完整候选；此时必须保留 partial/unresolved/data_unavailable 并阻止错误数据进入统计。
SMD/change、复杂 subgroup 与 multi-arm 仍受本契约前述明确条件约束；cluster/crossover adjustment、
time-to-event、rate/count、ordinal、adjusted-contrast-only、共享组拆分和 network meta-analysis 不属于当前范围。
