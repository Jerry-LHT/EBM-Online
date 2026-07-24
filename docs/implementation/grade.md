# GRADE 实现说明

## Application orchestration

`RunGrade` 为每个可估计的 SoF row 构造一次只读 evidence body，然后以固定上限 4 并发执行：

```text
risk_of_bias | inconsistency | indirectness | imprecision
```

多个 SoF rows 顺序处理，不叠加 row-level 并发。`executor.map` 按固定 domain order 返回结果，因此输出
不受任务完成顺序影响。Domain method 自己返回的 `unclear` 是正常 judgement；未处理技术异常会使整个
GRADE run 失败，不静默生成不完整 SoF row。

Evidence body 直接使用 final `AnalysisSetting.population_scope`、comparison、outcome、timepoint 和 subgroup。
Indirectness adapters 的 compact setting payload 保留这个临床人群 scope；不会从 Study Result Discovery 的
source-local population 反向构造 review target。`SoFRowGRADEAssessment` 与 estimate ref 均不复制
analysis-level `candidate_id`，连接键是稳定的 setting IDs。

Application 定义四个语义明确的 ports，composition root 显式注入四个 adapters。Backend 不存在 GRADE
module coordinator、动态 loader、通用 method registry 或 infrastructure base class。

## 正式组合

Composition root 只调用 GRADE factory 的四个 `build_production_grade_*()`，不传递 domain method
name。当前 production factory 组合为：

- Risk of Bias：`risk_of_bias/method_evidence_body_llm`
- Inconsistency：`inconsistency/method_policy_deterministic`
- Indirectness：`indirectness/method_staged_applicability`
- Imprecision：`imprecision/method_expert_threshold_ci`

## Method isolation

GRADE 根层只保留 `factory.py`。每个 domain 根层只包含 concrete method 目录；所有 evidence packing、
decision、normalization、numeric helpers、registry、prompt loader 和 prompt assets 都归属于一个具体 method。
Concrete methods 不互相 import，也没有 domain-level 或 GRADE-level `common.py`。

保留的 deterministic/twostep methods 同样是完整自包含包，但不接入正式 HTTP API。所有 prompt 资源由
所属 method 的 `prompts/` 管理。

## Risk of Bias method

Application 从 matched estimate 的 `included_study_ids` 构造 typed `GRADERiskOfBiasInput`。全部贡献研究按
estimate 顺序保留；找不到 study-level RoB 的研究生成 `rob_available = false` 的占位记录。已有 RoB 根据
实际 assessed domains 标记为 core-5、full-7 或 custom，并由 Application 确定性生成 domain summary。
存在 assessment 但 domains 为空时，也生成相同的 unavailable 占位记录，不进入 LLM 证据。
Application 根据 matched estimate 的 `included_data_row_ids` 读取 Meta-analysis DataRow 上的
`weight_fraction`。权重完整、有效且归一化时使用 `meta_analysis_weight`；否则正式 workflow 回退到
`study_count`，并且不从 participant count 或其它字段估算权重。

`method_evidence_body_llm` 只让模型输出语义判断：`assessment_status`、`severity`、`rationale` 和精确的
study/domain evidence references。严格 schema 和工程校验拒绝额外字段、未知 study ID 及未评估 domain。
工程层再将 `not_serious`、`serious`、`very_serious` 映射为稳定的 0/1/2 downgrade levels，并在公开输出
中使用 `assessment_status=assessed|insufficient_evidence`。一次初始调用
失败后只 retry 一次；重试耗尽向上抛出稳定技术错误，不降级成正常 judgement。
Retry 只捕获 retryable provider 错误和结构化/语义校验错误；非可重试 provider 错误在第一次立即失败，未知
程序异常不 retry，也不包装成 provider 错误。配置、provider、retry exhausted 与非法 judgement 分别具有稳定
错误类型和 API code；SDK 与 JSON-marker 隐式 retry 均被关闭。

旧 `risk_of_bias/method_llm` 包继续保留供历史 benchmark method 选择，但 production factory 不再使用它。
Backend runtime 不读取 benchmark 数据、权重或标签。

## Inconsistency method

Application 为每个 matched estimate 构建 typed `GRADEInconsistencyInput`。它不把整个 Meta-analysis package
交给 method：只选择 `included_data_row_ids` 且 `estimate_id` 精确匹配的 included DataRows，并直接使用 DataRow
顶层最终 `effect_value`、CI 和 `weight_fraction`，不从原始事件数或均值重新计算。相关 subgroup 结果按
`setting_family_id` 连接。

`method_policy_deterministic` 分为三个边界明确的阶段：

1. Result-blind policy generation：LLM 只看 target setting、contributing studies 的结构化 Study PIO、以及
   已计划的 subgroup factor/level 名称。Prompt payload 不含实际 study/pooled effects、heterogeneity 或 subgroup
   统计结果。LLM 生成严格 schema 的 effect-range policy 和 plausible effect modifiers；没有足够临床依据时返回
   `no_effect_only`。
2. Deterministic evidence profiling：代码把实际 point estimates、pooled point estimate 和 pooled CI 映射到
   冻结范围，计算每个范围的 study/weight 分布、跨越阈值数量、CI overlap，并原样整理 I²/Q、prediction interval 与
   subgroup-difference tests。代码不在这里用固定 count/weight/I² cut-off 决定等级。
3. Bounded judgement：第二个 LLM 只接收冻结 policy 与客观 evidence profile，按照 GRADE 的临床异质性思想
   判断 observed variation 是否足以改变决策、是否可能主要来自 imprecision，以及是否由预先生成且有 subgroup
   test 支持的 effect modifier 解释。Judge 只输出结构化 `decision_basis`，不生成自由文本事实叙述。严格解析器
   禁止它修改阈值、重算 pooled point/CI range、补造 modifier/test、引用错误 DataRow，或在没有跨阈值时
   downgrade。bounded judge 的既有内部 schema 仍使用 `none`、`serious`、`very_serious`；工程输出边界
   将内部 `none` 归一化为公开的 `not_serious`，不修改 prompt，并从已校验事实确定性组装 rationale。

同一临床范围内的 estimates 不因 I² 高而自动 downgrade。跨越重要临床范围是 downgrade 的必要边界但不是
充分条件；最终仍由 bounded judge 结合整个 evidence body 的分布、精确度和可解释性判断。横跨重要获益与重要
伤害才允许 very serious，但不会因此被工程代码自动判成 very serious。没有临床边界时只允许最高 serious，避免
在无法判断临床重要性时自动降两级。单研究不调用 LLM，确定性输出 `severity=not_serious`、0 级和
`assessment_status=single_study_not_estimable`；多研究但 effect coverage 不完整输出
`assessment_status=insufficient_evidence`，全部 estimates 在同一冻结范围则输出已评估的 0 级。

Production factory 已切换到新包。旧 `method_local_llm_profile` 与 `method_deterministic` 仍各自保留，没有被新方法
import，也未改变其历史 benchmark 行为。新方法的 LLM 配置显式设置 SDK retry 为 0；policy 与 judge 各自执行
严格的首次加一次 retry。API 将配置、带 stage 的非可重试调用、retry exhaustion、非法 policy 和非法 judgement
分别映射为稳定 domain 错误码。

## Indirectness method

Application 为每个 matched estimate 构建 typed `GRADEIndirectnessInput`。正式贡献行严格取自 estimate 的
`included_data_row_ids`，并要求 DataRow 的 `estimate_id` 精确匹配且状态为 included；同 setting 的其它行不进入
方法。每行通过 study ID 连接 `StudyPIOCharacteristics`，再以唯一精确 label 匹配 intervention、comparator、
outcome 和 timepoint。未找到或多重匹配都会保留为结构化 coverage/mapping status。

`method_staged_applicability` 使用以下流程：

1. `classification.py` 定义严格 result-blind schema。LLM 对每个 DataRow 的 P/I/C/O 分别输出 information status、
   overall directness 和可选 facet factors。Timepoint、setting、subgroup 等只嵌套在相应 PICO domain；缺失信息
   必须输出 not-assessable 且 factors 为空。
2. `aggregation.py` 按 `domain + facet + mechanism` 确定性构造 concern groups，并分别保存 less-direct、
   more-direct DataRows 及已有 Meta-analysis weight。权重完整性同时检查字段覆盖与总和；只有完整且总和在容差内
   等于 1 的权重参与 group/range 汇总，其他情况不归一化并使用 study/DataRow count。
3. `threshold.py` 通过 deterministic gate 判断是否需要一套 outcome-row clinical policy。需要时调用 result-blind
   threshold LLM；不需要时工程层直接产生 `not_needed`。RR/OR 的生成阈值使用 risk-difference scale，并要求
   明确的 model baseline-risk scenario。
4. `effect_ranges.py` 确定性完成 MD/SMD/RD/RR/OR 的 no-effect 值、ratio-to-absolute-risk 转换、study range、
   concern 两侧 concordance 与 baseline sensitivity；不重新合并 effect，也不把 CI width 当成 indirectness。
   非法数值与不可能的绝对风险转换按 DataRow 记录为 `unclassifiable`；OR baseline range 会检查端点、中点和区间内
   极值点。range 的 count/weight 分布由代码计算，LLM 不执行加总。
5. `judgement.py` 根据当前 evidence profile 动态生成严格 schema，约束最终 LLM 精确评价全部冻结 concern group，
   并预先限制 group ID/数量、severity、coverage 与 baseline-risk 枚举。Parser 确定性恢复 domain、DataRow 与
   mechanism，禁止补造/改写 concern；very serious 要求重大 applicability limit，但不要求固定 group 数量。
6. `decision.py` 保留 bounded judge 的既有 none/serious/very-serious/unclear schema，在工程边界将 none
   归一化为公开的 `not_serious`，并从结构化事实确定性组装
   rationale；`decision_basis` 也根据 severity、coverage 和 concern groups 确定性派生，模型不生成这些
   可由工程组装的字段或最终事实叙述。

三个实际 LLM stage 各自执行首次加一次 retry，SDK retry 固定为 0；本方法也关闭共享 Client 内部的 JSON-marker
兼容重试，使真实 provider 调用预算仍由 stage 统一控制；threshold stage 只在 gate 开启时执行。
预期 provider 与严格输出校验失败使用各自 stage 错误；未知程序异常不被宽泛捕获。Production factory 只使用
正式 adapter。成功结果的内部 `decision_features.execution_trace` 记录各 stage 尝试次数、threshold gate、权重状态、
数值告警、baseline 计算点和 concern range 汇总；公开 `GRADEDomainJudgement` 使用新增的
`assessment_status` 区分已评估、单研究不可估计和输入不足。旧 indirectness methods 不属于维护源码；
本地快照仅可放在被 Git 忽略的 `indirectness/archive/` 中，production factory、benchmark adapter 和维护测试
均不依赖这些快照。

## Imprecision method

Application 从 matched estimate 的 `included_data_row_ids` 构造 typed `GRADEImprecisionInput`，并同时要求
DataRow 的 `estimate_id` 精确相等、状态为 included、data type 与 setting 一致。缺失行进入 coverage；同 setting
但未被当前 estimate 纳入的行不会进入方法。输入不连接 Study PIO 或 Risk of Bias。

`method_expert_threshold_ci` 分为三个边界：

1. `threshold.py` 的 result-blind LLM contract 只接收 Analysis Setting 和 effect measure 对应的必需阈值量纲。
   它生成严格为正的重要获益/伤害幅度、outcome direction、依据和来源；严格 parser 检查量纲、有限值、URL、
   confidence 和 unavailable 语义。工程层根据 estimate 的 direction convention 分配符号：SMD 使用
   `positive_favors_experimental`，其它 measure 使用原量表或 experimental-relative-to-control 约定。
2. `calculator.py` 只用 matched estimate 和精确贡献行构造 numeric profile。RR 使用 `p0 × RR`，OR 使用
   `OR × p0 / (1 - p0 + OR × p0)` 转换处理风险，再输出每 1000 人绝对风险差；RD、MD、SMD 在各自量纲处理。
   在计算前要求完整 DataRow coverage，并交叉验证 estimate participant count 与贡献行人数。非法/非 95% CI、
   effect 不在 CI 内、方向不匹配、ratio baseline 不可得或转换产生不可能概率时形成业务不可评估原因。
3. `decision.py` 确定性判断 CI 穿越冻结临床边界的情况；未穿越时由 `ois.py` 使用同一临床阈值计算 OIS。二分类
   OIS 使用 comparator risk 和绝对风险差阈值，连续型使用 MID/SMD 与 pooled SD；未满足 OIS 降 1 级，无法计算
   返回 `unclear`。LLM 不读取当前结果、不计算数值，也不输出最终 downgrade 等级。最终 rationale 由工程层写入
   CI、阈值、threshold basis/confidence 及 OIS，确保 application 丢弃内部 debug 后仍可审计。

阈值 stage 首次调用失败后只 retry 一次，SDK retry 和 JSON-marker retry 均为 0。Provider、配置和非法结构输出
分别使用稳定错误；阈值或数值证据确实不可得、专家阈值只有 low confidence、或 OIS 不可计算时返回 `unclear`。
`imprecision/method_llm_web` 作为明确的 benchmark 对照方法保留；它不被 production factory import，也不影响
正式 `method_expert_threshold_ci` 的业务行为。

生产阈值方法同时兼容统一 LLM client 的 `responses` 和 `chat` 模式：Responses 模式可以附带
`web_search` 工具；Chat 模式不发送 Chat endpoint 不支持的工具参数，仍使用同一 result-blind 严格 JSON
阈值契约和 deterministic decision。当前生产配置使用 Chat 时不会因为该 domain 的旧 Responses-only
限制在工厂构造阶段失败。
