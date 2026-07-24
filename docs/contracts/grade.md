# Four-domain GRADE Assessment 任务契约

本文定义对 Meta-analysis evidence body 生成四个 GRADE downgrade domain judgements 的稳定业务契约。
当前实现见 [`GRADE 实现说明`](../implementation/grade.md)。

## 任务目标与粒度

评估单位是一个 selected `AnalysisSetting` 及其 matched effect estimate 定义的 evidence body。当前每个
evaluation unit 严格 1:1 输出一个 `SoFRowGRADEAssessment`。本模块只评估：

- `risk_of_bias`
- `inconsistency`
- `indirectness`
- `imprecision`

不评估 publication bias，不输出五域总体 certainty label。

## 输入契约

- `review_id` 与 `question_text`。
- `question_pico`：indirectness 判断的 target PICO。
- `screening_criteria`：review eligibility 上下文。
- `study_characteristics`：各 study 实际 PIO 特征。
- `risk_of_bias`：study-level RoB 1 assessments。
- `meta_analysis_result`：settings、study rows、effect estimates 和 subgroup 结果。

Module API 的 `study_characteristics` 与 `risk_of_bias` 各最多接收 500 项；正式 workflow 的 SoF row 数仍由
Meta-analysis synthesis target 上限约束。

## Evidence body 选择

Application 按 `analysis_settings` 顺序处理：

1. overall setting 匹配同 `setting_id` 的 `OverallEstimate`；subgroup setting 匹配 `SubgroupEstimate`。
2. 找不到 matched estimate 的 setting 不产生 SoF row。
3. estimate 的 `included_study_ids` 定义 evidence body。
4. 按该 ID 集合过滤 study characteristics 和 Risk of Bias assessments，并显式记录缺失 IDs。

GRADE 不重新筛选 study、抽取 result data 或计算 effect estimate。

## GRADE Risk of Bias 输入边界

`risk_of_bias` domain 使用专用的 `GRADERiskOfBiasInput`，不接收通用 evidence-body 字典。该输入只包含：

- 当前 setting 的 population、comparison、outcome/measure、timepoint 和 subgroup；
- matched estimate 定义的全部 contributing study IDs；
- 每项研究已有的 RoB 1 domain judgement 与 rationale；
- `rob_available`、已评估/未评估 domains 和整体 coverage；
- 可用时由 Meta-analysis 提供的归一化 study contribution weight；
- 由 Application 确定性汇总的 domain 计数和权重分布。

同一输入允许 `rob1_core_5`、`rob1_full_7` 和配置子集形成的 `rob1_custom`。未评估 domain 不得按
low risk 处理。缺少 RoB 的贡献研究仍保留在 `contributing_studies` 和权重分母中，但标记
`rob_available = false`，不能作为具体 domain 判断证据。
存在 `RiskOfBiasAssessment` 但没有任何 domain judgement 时，同样按缺少可用 RoB 处理；如果整个
evidence body 都没有可用 RoB，最终输出 `level_evaluable = false`（当前稳定输出表示为 `unclear`）。

`contribution_basis = meta_analysis_weight` 时，每项贡献研究都必须有 0–1 的 `weight_fraction` 且总和约等于
1。Application 从 matched estimate 的 `included_data_row_ids` 对应 DataRow 读取该值；只要权重缺失、无效
或不能完整覆盖 contributing studies，就使用 `study_count`，并把所有 weight 设为 null，方法不得推断权重。
本 domain 不接收 pooled effect value、confidence interval、heterogeneity、SoF footnote 或其它 GRADE
domain 结论。

## GRADE Inconsistency 输入边界

`inconsistency` domain 使用独立的 `GRADEInconsistencyInput`。Application 以 matched estimate 的
`included_data_row_ids` 为唯一行集合，并按该顺序读取 DataRow 顶层已经计算完成的：

- study effect、95% CI、analysis scale 与 `weight_fraction`；
- matched overall/subgroup estimate 的 pooled effect、CI、heterogeneity 和 prediction interval；
- 同 `setting_family_id` 的 subgroup estimates 与 subgroup-difference tests；
- 当前 contributing studies 的结构化 Study PIO。

DataRow 必须同时匹配当前 `estimate_id`；同 setting 中未被 matched estimate 纳入的行、其它 estimate 的行和
excluded 行不得进入判断。Coverage 显式记录预期、可用和缺失 DataRow。权重只用于描述各效应范围对合并结果的
贡献，不替代临床阈值，也不由 GRADE 重新计算或推断。

该方法是全自动的，不接受人工阈值输入。LLM 在看不到 study effects、pooled effect、I²/Q、subgroup results
和 benchmark label 的情况下，只根据 target setting、Study PIO 与预先存在的 subgroup 名称生成：

- 当前 outcome/effect measure 的重要获益、无重要效应、重要伤害范围；
- 结果盲的 plausible effect modifiers（可能的效应修饰因素）。

如果上下文不足以支持数值临床边界，policy LLM 必须返回 `no_effect_only`，不得制造阈值。工程层严格校验并冻结
policy，再确定性计算 study effects 所处范围、范围内 study/weight 分布、CI overlap、heterogeneity、pooled point
range、pooled CI ranges 与 subgroup test 等客观证据画像。第二个 bounded judge LLM 只依据冻结 policy 和该画像进行 GRADE
判断：它不能修改阈值、补造 effect modifier、引用未知 DataRow，或用固定的 study count、weight、I² cut-off
代替临床判断。I²/Q 是辅助信号，不单独决定 downgrade。可信的预设/结果盲 effect modifier 只有在已有
subgroup-difference test 支持、且 subgroup 内没有明显残余不一致时，才可解释总体 variation。

Judge 不生成自由文本事实叙述。它必须原样回传确定性 pooled point/CI range 字段，并选择结构化
`decision_basis`；任何范围重算或回传不一致都会触发该 stage 的 retry。最终 `rationale` 由工程层使用已校验的
range、study count、weight、threshold span 和 Judge 的结构化临床结论组装，避免数值事实正确但自然语言过程错误。

工程层只保留不需要语义裁量的稳定出口：单研究为 not serious；DataRow coverage 不完整为 `unclear`；全部
point estimates 落在同一个冻结效应范围时为 not serious。其余最终 severity 由 bounded judge 输出并经工程
约束校验：serious 至少需要跨越一个冻结阈值，very serious 至少需要跨越两个冻结阈值；工程代码不依据某个
benchmark case 硬编码最终等级。

单研究 evidence body 的 inconsistency 确定性输出 not serious（0 级）且不调用 LLM。多研究但 matched
DataRow coverage 不完整时输出 `unclear`/`level_evaluable = false`，不把工程缺失伪装成临床判断。

## GRADE Indirectness 输入边界

`indirectness` domain 使用独立的 `GRADEIndirectnessInput`。Application 以 matched estimate 的
`included_data_row_ids` 为唯一贡献行集合，并要求 DataRow 同时匹配当前 `estimate_id` 且
`analysis_status = included`。输入明确包含：

- review-level P/I/C/O 与 screening criteria；
- 当前 setting 的 population、comparison、outcome/measure、timepoint、subgroup 与 effect measure；
- matched estimate 的身份、纳入行/研究、pooled effect/CI；
- 每个贡献 DataRow 的 study ID、实际 comparison/outcome/timepoint/subgroup、study-level P/I/C/O 映射、
  study effect/CI、`weight_fraction` 和可计算的 observed control risk；
- 同 `setting_family_id` 的 subgroup estimates/tests；
- DataRow、Study PIO、映射和权重 coverage。

Study PIO 与 DataRow 的 I/C/O/timepoint 只做大小写与空白归一化后的唯一精确 label 匹配。无法唯一匹配时保留
candidates 和明确 mapping status，不用工程关键词猜测临床等价关系。Pooled effect、study effect 与 weight
只作为 evidence-body judgement 的辅助信息；方法不重新计算 Meta-analysis，也不使用固定权重或 study-count
cut-off 自动决定 downgrade。

正式方法分为五个边界：

1. Result-blind study classification：第一个 LLM 只看 target、eligibility、Study PIO 和当前 result mapping，
   不接收 effect、CI、weight、heterogeneity 或 subgroup results；逐 DataRow 分类 P/I/C/O directness。Timepoint、
   setting、subgroup 等是 PICO 内部 facet，不是独立最终 domain。Target 未指定的可选 facet 不构造差异；Study
   信息缺失只形成 coverage。
2. Deterministic concern grouping：只有 probably-not/not-sufficiently-direct，且具有 possible/likely/very-likely
   效应差异与可信机制的 factor，才按 `domain + facet + mechanism` 组成冻结 concern group。
3. Conditional result-blind threshold：仅当 concern 存在可比较的 more-direct 与 less-direct studies，或 ratio
   measure 存在 population baseline-risk concern 时，LLM 为整个 SoF outcome row 生成一套临床阈值 policy。
   阈值阶段看不到 study/meta result；没有可信临床边界时合法返回 `no_effect_only` 或 `unavailable`。
4. Deterministic evidence profiling：代码按冻结阈值映射 MD/SMD/RD/RR/OR study effects，汇总 concern 两侧的
   clinical range、weight 与 concordance。RR/OR 需要绝对风险差时，可使用明确标注为 model assumption 的 target
   baseline-risk scenario；observed study control risks 与该 scenario 分开，方法不重算 Meta-analysis。权重只有在
   所有贡献 DataRow 都提供且总和于 `0.001` 容差内等于 1 时才用于 judgement；缺失或总和非法时保留明确的
   `incomplete`/`invalid` 状态，并回退到 DataRow/study count，不做静默归一化。非有限 effect、非法 RD、非正
   RR/OR 或会产生不可能概率的 ratio/baseline 组合只把对应行标记为数值不可分类，不升级成整个 domain 的工程错误。
5. Bounded judgement：最终 LLM 必须逐个评价已有 concern group，只能使用冻结分类、coverage、weight、范围
   concordance、baseline sensitivity 与 direct-comparison status；不能补造 concern，也不能用 group 数量公式
   推导 very serious。Judge schema 会按当前 evidence 动态限定 group ID/数量、可选 severity、coverage flag 和
   baseline-risk 状态；parser 仍执行交叉字段语义校验。

`decision_basis` 不由 LLM 重复生成；工程层根据已校验的 severity、coverage 和 concern groups 确定性派生该
trace 字段，并同时组装事实 rationale。

目标 baseline risk 当前未由上游提供，因此方法不得由 observed control risks 伪造 target baseline risk。必要时
threshold LLM 可基于 target population/outcome 产生明确标注为 `model_scenario` 的概率区间，只用于绝对效应敏感性
分析；它本身不能触发 downgrade。实际 coverage 不足可以形成业务 `unclear`，provider 或结构输出失败不能伪装
成 unclear。OR 的 baseline sensitivity 同时检查区间端点、中点以及区间内的绝对风险差极值点，避免仅检查端点
漏掉临床范围跨越。

## GRADE Imprecision 输入边界

`imprecision` domain 使用独立的 `GRADEImprecisionInput`，只接收判断精确性所需的信息：

- 当前 `AnalysisSetting` 的 population、comparison、outcome/measure、timepoint、subgroup、data type 和 effect measure；
- matched overall/subgroup estimate 的身份、状态、effect、95% CI、participant count、effect-direction convention
  和纳入 IDs；
- 严格按 estimate 的 `included_data_row_ids`、`estimate_id` 与 `analysis_status = included` 连接的原始
  `MetaAnalysisDataRow.result_data`；
- 预期、可用和缺失 DataRow 的明确 coverage。

本 domain 不接收 Study PIO、Risk of Bias、heterogeneity、prediction interval、其它 GRADE judgement 或 benchmark
信息。RR/OR 的 comparator baseline risk 只从当前 estimate 的精确贡献行事件数聚合；不能从其它 study、其它
estimate 或模型假设补造。全部 effect measure 都要求完整 DataRow coverage，estimate participant count 必须与
贡献行总人数一致；无法核对时返回业务 `unclear`，而不是继续使用可能不一致的信息量。

临床阈值 LLM 是结果盲的：它只看到 target setting 和所需量纲，看不到 pooled effect、CI、participant count、
event count 或贡献行。模型只输出严格为正的重要获益/伤害幅度和原临床量表方向；工程代码再依据 Meta-analysis 的
`experimental_relative_to_control`、`original_measure_direction` 或 `positive_favors_experimental` 约定确定最终
符号，尤其保证 SMD 与上游统一的“正值代表 experimental 更好”方向一致。模型通过直接来源或明确的专家判断
形成阈值；低可信专家阈值、无法形成可辩护阈值或不适用来源均返回业务 `unclear`。

阈值冻结后，代码确定性完成 RR、OR、RD、MD、SMD 的数值换算及 CI crossing 判断：CI 同时跨越重要获益和
重要伤害边界为 very serious，跨越其中一个为 serious。CI 不跨临床边界时，代码使用同一临床阈值计算 OIS
（optimal information size，最佳信息量）：二分类使用贡献行 comparator risk 和绝对风险差边界，连续型使用
MID/SMD 边界与贡献行 pooled SD。OIS 未满足为 serious，满足为不降级；无法计算则为 `unclear`，不使用固定研究数
或 benchmark cut-off。

无可用/低可信阈值、非 95% CI、未计算 estimate、方向约定缺失、非法数值、必要 DataRow 缺失、样本量不一致或
OIS 无法评价时输出 `unclear`。成功 judgement 的 rationale 必须保留实际绝对/连续 CI、获益/伤害阈值、阈值依据
与 OIS 实际/所需样本量，使公开输出无需依赖内部 debug 即可审计。LLM 配置、provider 调用和严格结构输出失败是
技术错误，不能伪装成业务 `unclear`。

## 输出契约

`GradeResult` 包含 `review_id`、`question_text` 和有序 `sof_rows`。每个 row 包含：

- setting 身份、`population_scope`、comparison、outcome、timepoint 和 subgroup。
- `effect_estimate_ref` 及 `included_study_ids`。
- 固定四个 `GRADEDomainJudgement`。

每个 domain judgement 包含 `downgraded`、`severity`、`levels`、`level_evaluable`、`assessment_status`、
`rationale` 和 `source_spans`。公开 `severity` 使用 `not_serious`、`serious`、`very_serious` 或
`unclear`。`assessment_status` 使用 `assessed`、`single_study_not_estimable` 或
`insufficient_evidence`，用于区分已评估、单研究无法估计研究间不一致、以及输入不足。

SoF row 与 matched estimate 通过 `setting_id`/`setting_family_id` 连接，不携带分析层 `candidate_id`。
Article-local candidate IDs 只属于 Meta-analysis 的候选解析 provenance，不是 GRADE evidence-body identity。

## 并发、顺序与失败

同一 SoF row 的四域是语义独立的执行单元，Application 以有界并发（最多 4 workers）运行它们。
输出始终按 `risk_of_bias`、`inconsistency`、`indirectness`、`imprecision` 的业务顺序组装；
多个 rows 按 setting 顺序串行处理。未处理的 domain 技术异常使整个 run 失败，不返回静默缺域的 row。

内部 domain method 名称不属于 HTTP 或 application 契约。

GRADE RoB LLM 的业务调用上限为首次调用加一次 retry，并关闭 SDK 与 JSON-marker 隐式 retry。只有 retryable
provider 错误和非法结构化/语义输出进入第二次调用；非可重试 provider 错误立即失败，未知程序异常直接向上
抛出。HTTP 分别使用 `grade_risk_of_bias_configuration_unavailable`、
`grade_risk_of_bias_invocation_failed`、`grade_risk_of_bias_retry_exhausted` 和
`grade_risk_of_bias_invalid_judgement_output`。当全部贡献研究都没有 RoB 证据时，不调用 LLM，确定性输出
`level_evaluable = false`。

GRADE Inconsistency 的 policy generation 与 bounded judgement 是两个独立 LLM stage；每个 stage 最多首次调用
加一次 retry，并禁用 SDK 与 JSON-marker 内层自动 retry，确保真实 provider 调用预算不会叠加。非可重试 provider 错误立即
失败；非法 policy 或 judgement 在各自第二次仍不合法时，以该 domain 的稳定错误失败。
HTTP 错误码为 `grade_inconsistency_configuration_unavailable`、
`grade_inconsistency_invocation_failed`、`grade_inconsistency_retry_exhausted` 和
`grade_inconsistency_invalid_policy_output`、`grade_inconsistency_invalid_judgement_output`。调用类错误额外返回
`stage = policy_generation | judgement`。

GRADE Indirectness 的 result-blind study classification、conditional threshold generation 与 bounded
evidence-body judgement 是相互独立的 LLM stages；只有确定性 gate 判断 threshold 有信息价值时才执行中间 stage。
每个实际执行的 stage 最多首次调用加一次 retry，并禁用 SDK 内层自动 retry。非可重试 provider 错误立即
失败，未知程序异常直接上抛。HTTP 错误码为
`grade_indirectness_configuration_unavailable`、`grade_indirectness_invocation_failed`、
`grade_indirectness_retry_exhausted`、`grade_indirectness_invalid_classification_output` 和
`grade_indirectness_invalid_threshold_output`、`grade_indirectness_invalid_judgement_output`，调用类错误同时返回
`study_classification | threshold_generation | evidence_body_judgement` stage。

GRADE Imprecision 只有一个 result-blind threshold-generation LLM stage，业务调用上限为首次加一次 retry，并禁用
SDK 与 JSON-marker 内层 retry。非可重试 provider 错误立即失败，未知程序异常直接上抛。HTTP 错误码为
`grade_imprecision_configuration_unavailable`、`grade_imprecision_invocation_failed`、
`grade_imprecision_retry_exhausted` 和 `grade_imprecision_invalid_threshold_output`；调用类错误的 stage 固定为
`threshold_generation`。
