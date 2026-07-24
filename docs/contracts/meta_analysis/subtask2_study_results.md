# Meta-analysis Study Evidence 契约

本文定义 Meta-analysis 中研究级证据抽取与解析的稳定业务语义。具体实现见
[`meta-analysis-subtask2.md`](../../implementation/meta-analysis-subtask2.md)。

## 任务目标与粒度

该阶段从一篇已纳入 RCT 文章中，找回它可贡献给全部冻结 synthesis targets 的 arm-level 数据。调用粒度为
`one included study/article × all frozen targets`，不是按 target 重复读取文章。

冻结 review target 可能比文章本地报告更宽。方法应保留多个合理的 article-local candidates，直到证据足以按
预先冻结、与结果大小无关的规则选出一个贡献；不能为了强制形成一行而合并不同 outcome、measure、timepoint、
subgroup 或 analysis population。

## 输入

每个 article task 接收：

- `review_id` 与冻结 plan hash；
- 全部 `SynthesisTarget[]`，包括 population、comparison、outcome、timepoint、subgroup、data type、
  result-selection policy 和 effect-measure plan；
- `study_id`；
- 当前 `CleanedArticle` 的 section catalog/text 与 raw table XML。

Target 只定义相关性和最终选择边界，不是 source-local 字段模板。Backend 输入不得包含 benchmark gold、目标行
索引、评分结果或人工答案。

## 表格证据边界

每个 candidate 必须只从当前一次 table call 的 raw table 发现：caption、hierarchical headers、rows 和
footnotes。Candidate discovery/repair 不得接收 article body、abstract、Methods、其他 table 或由正文推导的 arm
mapping。当前表无法建立某个维度或 arm/value 绑定时，保留 uncertainty/null 或不返回 candidate。

Candidate discovery 的每次 LLM 调用固定只包含一张 raw table。跨表支持材料通过独立的 source-local 调用提取，
并保留各自 `source_ref`；这不允许其他来源改写 candidate 的本地 identity，也不允许正文产生 candidate。一个已经
存在的 table-local candidate 可以在最终 verification/adjudication 后由其他表或正文补充 typed numeric evidence，
但这些材料必须继续标记为自己的来源，不能伪装成 candidate table 的内容。

正文可由 article controller 按需读取，用于建立 `StudyMap`、定位 participant flow、follow-up、analysis population
和其他具体证据缺口。正文不得产生新的 result candidate 或覆盖 candidate identity；只有被 source-local verifier
结构化、被 cross-source adjudicator 明确选择、且通过 arm/scope/type 门禁的正文数值才能补充最终 data row。

每个 StudyMap 中的真实随机研究臂具有 article-local `arm_id`。各表先产生 source-local arm observation；LLM 根据
具体方案、剂量、频率和原文映射显式把 observations 划分为 canonical arms，工程代码验证每个 observation 只属于
一个分组并分配稳定 ID。共享 experimental/control 角色或 `Control`、`Treatment` 等通用名称不表示两个真实臂相同。
Candidate 的原表 arm 通过 source-qualified observation 绑定到唯一 `arm_id`；resolution、verification、最终字段绑定和
确定性多臂汇编均以该 ID 为身份依据。

原始表格由 LLM 直接理解；工程代码不得用确定性 row/column 清洗或解析代替。LLM 抽取 directly reported
typed materials，包括 counts、percentage、不同语义的 N、mean、SD、variance、SE、CI、effect/test statistics，
但不做最终算术。确定性代码负责白名单转换、数值验证、多臂合并、跨表门禁、provenance 和最终统计行组装。

## Candidate 粒度

一个 candidate 是一张表中的一个 `ResultBlock`，同时包含：

- outcome label/measure 与 unit；
- timepoint；
- clinical population/subgroup 与 statistical analysis population（如 ITT、mITT、PP）；
- statistic definition；
- continuous endpoint/change frame、change definition 与 scale direction（适用时）；
- `reported_statistic_type`：模型从当前表格读到的原始统计描述，仅用于审计；
- `reported_statistic_kinds`：代码从 typed materials 汇总出的报告材料类型；一张表可以同时有
  `event_count`、`result_denominator`、`percentage` 和 `p_value`；
- `analysis_input_representation`：代码根据材料和数据类型确定的分析表示，例如
  `dichotomous_arm_events_total`、`continuous_arm_mean_sd_total` 或
  `continuous_direct_effect_se`；
- `statistic_type_status`：原始描述与材料的一致性，取 `consistent`、`conflict`、`derived` 或 `unclear`；
- 同一结果框架下表中报告的全部 arms；
- 每个直接值或中间统计材料的类型、statistical scope、source locator、table ID、source hash 与 uncertainties。

Source locator 可以是一个连续原文片段，或在层级表头场景下由 header/cell 多个原文片段组成；它用于定位和
verification，不是由工程代码重新解释表结构的入口。

Source-workspace verification 的每个最终字段还携带 `evidence_scope`。该对象明确记录
`outcome_label`、`outcome_measure`、`timepoint`、article-local `arm_label`、`analysis_population`、
`result_frame`、`row_or_item_label`、`column_header_path`、`denominator_scope`、实际链接的
`footnote_links`、带独立 `source_ref/source_kind/quote` 的 `supporting_quotes` 和 `scope_status`（`complete`、
`requires_audit` 或 `incomplete`）。这些字段用于
审计和 provenance，不是工程代码用来规定表头或脚注优先级的规则，也不会改写 candidate 的 local setting。
脚注链接的 `text` 必须可在 candidate source 中定位；`marker` 可为空，以支持无标记的 table-wide footnote。

确定性 bridge 根据最终字段的 `scope_status`、selection basis、confidence 和 denominator scope 生成
`scope_assessment`（`complete` 或 `provisional`）。它只表达剩余证据范围不确定性，不重新选择数值，也不改变既有
`analysis_disposition=ready_for_estimate`；provisional contribution 仍可进入自动分析，但其 warning 必须保留在
derivation/result item 中供下游审计。

不同 ResultBlock 的数值不能在 candidate 层拼接。Candidate 可以不完整；不完整不等于 `data_unavailable`。

不完整 candidate 可产生明确的 typed material needs。方法可以对已选择的其他表执行一次有界 supporting-material
recovery，但该调用不得改变 candidate identity 或执行算术；它只返回带独立 source locator/scope 的材料。

## Resolution 与跨表

Resolution 对每个 target 返回且只返回一个状态：`resolved`、`data_unavailable`、`unresolved` 或
`unsupported_dependency`。Provider/output 技术失败由 application 记录为 `technical_failure`，与业务上的无数据
严格区分。

选择不得读取 effect magnitude、direction、CI、P value 或“看起来更有利”的结果。多臂选择、来源优先级、
timepoint 和 analysis population 必须遵守冻结 target policy。

“同属 experimental role”与“同一个真实 arm”是不同概念。多个不同 `arm_id` 是否共同进入一个 target 由冻结 comparison
和 result-selection policy 决定；进入同一 target 后才由确定性代码合并。每篇 study 对每个 target 最多产生一个 contribution，
从而避免共享对照被当作多个独立研究重复计入同一分析。

默认只使用一个完整 ResultBlock。跨表补字段只有在每个来源都明确同一 outcome、measure、timepoint、analysis
population、`analysis_input_representation`、result frame、subgroup、arm identity 和 unit 时允许，并要求 Resolver 显式
选择 source candidate/support material，最终保留 material/candidate/table/arm provenance。Randomized/baseline
enrollment 不能由代码自动当作 follow-up analyzed denominator；在 source-workspace verification 中，若原文没有更具体的
分母且完整报告没有相反的失访/排除证据，LLM 可以把它选为最有证据支持的分母，但必须标记为
`supported_inference` 或 `assumption`，并保留选择理由和置信度。身份不完整、冲突或确实无法区分时保持
`unresolved`。

二分类多臂合并为 events 与 totals 分别加总；连续型多臂合并使用样本量加权 mean 与包含组间均值差异的 pooled
SD。Events 和 N 必须是有限整数，SD 非负。直接与一个结果配对的 `events/N`、percentage denominator 或
mean/SD column N 属于 result denominator，不要求文章另写 analyzed set；它与单独的 randomized/baseline N
严格区分。允许的前置转换仅限 versioned calculator 白名单：non-events/percentage 与 result denominator 得
events，variance/arm-mean SE/arm-mean CI 与 result denominator 得 SD。百分比必须在报告精度下唯一确定
events；arm-level CI 使用 `t(df=N-1)`。Between-group uncertainty 和 P/t/F statistics 不得冒充 arm SD。`P value` 等附加统计量
可以和 events/N、mean/SD/N 同时存在，不覆盖主要分析表示。所有公式由代码
执行，LLM 不产生最终计算结果。

连续型 Mean Difference 还支持直接报告的组间效应路径：同一个表格 candidate 必须提供 MD 与匹配的 SE，或 MD 与
双侧 CI。LLM 负责确认 outcome、timepoint、analysis population、比较的两个真实研究臂、比较方向和统计作用域；代码
按 CI level 确定性换算 SE，并把 `control - experimental` 归一为 `experimental - control`。直接效应不能与另一个
outcome、timepoint、分析人群或 model 的不确定性拼接。可明确绑定到该结果的两臂分析样本量会相加写入
`participant_count`；无法确认时保持为空，不以 randomized/baseline N 猜测。该路径生成
`GenericInverseVarianceResultData(effect_value, standard_error, effect_measure, analysis_scale, participant_count)`，
可与同一 setting 内的 arm-level MD 一起进入确定性 inverse-variance（逆方差）合并。当前不支持 direct SMD、
比值效应的 log-scale GIV、P value 单独反推 SE 或由正文/图片发现新的 candidate。

内部 evidence contract 使用 `direct_effect` 与 `direct_uncertainty`，因为原文可能报告 CI 而不是 SE。
`direct_uncertainty` 只接受与该 effect 作用域一致的 SE 或 CI；CI 到最终 `standard_error` 的换算由确定性代码完成。
同一个 evidence ID 不能同时承担 effect 与 uncertainty，二者即使共享同一原文单元格也必须是两条独立 typed evidence。

非 candidate-owned supporting evidence 进入统计组装前必须已经属于最终 adjudication verdict，并保留
`verified_field`、`article_arm_id`、source ref/kind 和 evidence scope。计算层优先按稳定 arm ID 匹配，再按字段的
experimental/control 侧别过滤，并只接受 calculator 白名单 material kind。Legacy、未经最终裁决的 support 仍使用
既有严格 local-setting gate；verified support 不会再因 candidate 表中缺少 timepoint 字符串而被第二次字符串规则推翻。

连续型裁决还必须记录 scale direction、判断依据和置信度。LLM 可依据原文定义或通用量表知识判断“高分更好/更差”；
无法可靠判断时标记 `unclear`。对于 post-intervention MD，原始 experimental-minus-control 数值仍可进入统计分析，
但必须携带 `clinical_direction_status=unknown`，下游不得把正负号直接解释为临床获益；对于 change-from-baseline，若
量表方向或变化值定义不足以确定符号，则保持 unresolved。

## 输出

每篇文章返回：

- `StudyResultRow[]`：按输入 target 顺序，一 target 一行，保留 table-local candidates 与 dispositions；
- `CandidateResolutionRecord[]`：按输入 target 顺序，一 target 一个决策和证据来源；
- `MetaAnalysisDataRow[]`：仅包含确定性验证和 assembly 成功的 resolved contributions；
- coverage：expected targets、已读 section/table、`table_transport_status`、
  `investigation_status`、warnings 和 complete/incomplete/technical status。Target 的正向
  `resolved` 与 article-level `incomplete_source_coverage` 可以同时出现；后者是覆盖警告，不会把已验证的
  contribution 改写成 unresolved。

`study_result_rows` 是候选与审计层；`meta_analysis_data_rows` 才是统计输入。每个 study 对每个 target 至多形成一个
正式 contribution。由中间材料得到的字段必须携带 input material IDs、source tables、公式和假设。source-workspace
verification 还会在 `derivation.input_values.field_selection` 中按最终字段保存一组 arm-level 选择记录，每条记录包含
`arm_label`、`basis`、`confidence`、`rationale` 和 `evidence_scope`；单臂时该组只有一条，多臂时每个被选研究臂各有一条。这些是审计
信息，不是下游重新计算的输入。

`result_data` 的两种连续型形状承担不同责任：臂级 `ContinuousResultData` 保存 mean/SD/N 原始统计输入；
`GenericInverseVarianceResultData` 保存文章直接报告且已完成方向归一的单研究效应与 SE。二者不会互相伪造，最终
`effect_value`、variance、weight 和 pooled estimate 仍统一由确定性统计代码产生。

## 失败语义

- 完整表格覆盖后没有合格 table-local candidate：业务上为未提取结果，同时以
  `no_eligible_table_candidate` 或 `no_compatible_table_candidate` 说明具体原因。
- 有候选但语义、依赖或必要身份无法唯一确认：`unresolved`/`unsupported_dependency`。
- Controller 达到 source budget 或仍有合理来源未读：coverage 为 `incomplete_source_coverage`，不得声明确定的
  `data_unavailable`。已有 candidate 的 proposal 仍可进入 required-source verification；只有通过严格 source
  verification 和 deterministic assembly 才能成为 resolved。
- Verification dependency 中的 alternative materials 是 optional/audit-only source。optional source 不被调用或
 失败时，不得阻塞 selected candidate；selected candidate source、selected field evidence source 和显式 context
  source 属于 required dependency，失败按 technical/output failure 处理。
- Required-source verification 只接收 resolver 选中的 candidate 和字段材料；resolver 已排除的 candidate 继续保留在
  resolution provenance 中，但不进入同一次必需调用。冻结的 `statistic_type_priority` 同时约束 verifier 可返回的
  result representation，未列出的 direct-effect 或 arm-level 表示不能因恰好出现在原表中而阻塞已选路径。
- 数值字段构成一个可辩护的完整 representation、但 analysis population、denominator linkage 或精确 timepoint
  描述仍不完整时，adjudication 应保留最佳支持结果并由 bridge 标记为 provisional；只有必需数值缺失、硬语义不兼容或
  证据确实无法区分时才保持 `unresolved`。
- 每篇最多接收 12 个冻结 target；table census 最多覆盖 32 张表和 32 个完整 transport windows。窗口预算按表轮转，
  被部分读取的表写入 `coverage.partial_table_ids`，并按 incomplete coverage 处理。
- 一篇文章的 provider/output stage 在首次加一次 retry 后仍失败：该 article 为 `technical_failure`，其他文章继续。
- `technical_failure` 必须附带结构化失败细类。Provider timeout、上游连接失败、HTTP server/rate-limit/auth/request
  错误与 `invalid_model_output` 分开记录，并保留 stage、attempt count、retry exhaustion、HTTP status、request ID 和
  有界原始详情（适用时）。已知的 source scope 和 footnote provenance 违反分别使用
  `model_output_source_scope_violation` 与 `model_output_footnote_provenance_invalid`；这些诊断字段不能改变文章的
  EBM disposition。
- 配置缺失、输入不合法、adapter contract 破坏或未知程序错误：整个 Meta-analysis 调用失败。

## 分层责任

Backend 定义真实 workflow 行为；benchmark 只构造 case、调用 public adapter、计算指标和保存 artifacts。
Benchmark-specific gold mapping 或 normalization 不得进入 backend runtime。
