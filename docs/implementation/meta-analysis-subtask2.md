# Meta-analysis Study Evidence：当前实现说明

本文描述当前 production Study Evidence adapter。稳定任务契约见
[`Study-level Result Data Extraction`](../contracts/meta_analysis/subtask2_study_results.md)。

## 入口与目录

```text
backend/src/ebm_backend/online_pipeline/infrastructure/methods/meta_analysis/
  factory.py
  study_evidence/
    article_evidence_agent/
      method.py
      calculators.py
      schemas.py
      prompts/
    source_workspace_agent/       # 当前 production Study Evidence adapter
      method.py
      source_workspace.py
      evidence_state.py
      deterministic_bridge.py
      schemas.py
      prompts/
```

Production factory 只构造 `source_workspace_agent`。`article_evidence_agent` 包中的 schema、calculator 和
确定性 assembly helper 仍由当前 production adapter 复用，因此属于运行时源码，但不再作为独立 factory method
暴露。原 `source_local_candidate_extraction + semantic_rules` 以及更早的 extraction variants 不属于维护源码；
本地历史快照仅可放在被 Git 忽略的 `archive/` 中。Backend、benchmark production adapter 和维护测试均不得依赖
这些本地快照。

## Production 调用粒度（未改变）

Application 以一篇 included article 为一个独立任务，一次传入该 review 的全部冻结
`SynthesisTarget[]`。Evidence Agent 一次浏览文章、一次建立 `StudyMap`，并让每张选中的原始表同时服务所有
targets，避免按 target 重复读取同一长文章。

每篇文章的输出包含：

- 每个 target 一个有序 `StudyResultRow`；
- 每个 target 一个 `CandidateResolutionRecord`；
- 零到多个已解析 `MetaAnalysisDataRow`；
- article-level coverage，记录已读 section/table、warning 和 complete/incomplete/technical failure 状态。

外部 `MetaAnalysisRequest` 与 `MetaAnalysisResultPackage` 未因内部方法替换而改变。

下面是当前 production source-workspace method 的实际调用方式。

## Source-workspace Evidence Agent（当前 production）

入口为
`build_production_study_evidence_agent`。
它保持相同的外部 Study Evidence 输出形状，但内部把
文章作为不可变 source workspace 管理：所有预算内 raw table window 先做一次 table census，标题作为
`<study_id>::front::title` source，XML 中的 Abstract section 作为可重读 section；正文检索也会把目标人群纳入
查询。标题、摘要和 section 只能帮助研究语义与定位，candidate 仍必须来自单一当前 raw table。

调用顺序是：

1. `table_census`：每次 LLM 调用只读取一张原始表，并以有界并发（上限 4）覆盖所有预算内非空表，产生严格
   table-local candidates 和 typed materials；不做确定性表格解析，也不把多张原始表拼入同一次上下文。
2. `investigation`：最多 2 轮，第一次直接提供 title/Abstract 和有限 section search window；模型可请求最小的
   section/table source reread。每次读取后都必须由下一轮模型观察并消费；最后一轮只允许 `finish`，不会执行
   一个没有后续观察轮的 fetch。Notebook 只保存结构化状态，不把完整历史追加进上下文。
3. `arm_reconciliation`：把各表产生的 source-local arm observations（来源、原标签、描述、角色和 candidate 引用）
   交给模型做一次文章级语义归并。模型显式给出 observation partition；工程代码只校验分区并分配稳定 arm ID。
   `Control`、`Treatment` 等通用角色词本身不能证明身份相同；具体干预、剂量、频率或原文映射一致时才归并。
4. `resolution`：向模型提供 result-blind candidate/material projection，隐藏 numeric values、effect magnitude、
   CI/P value；模型选择 candidate、arm mapping、field evidence 和必要的 context source refs。
5. `source_verification + cross_source_adjudication`：Resolver 先由工程代码生成 required/optional source dependency
   plan。required source（selected candidate、selected field evidence 和显式 context refs）独立重读，只产出带
   source scope 的 evidence cards；alternative materials 仅保留作审计，不会阻塞 required source。随后裁决器只基于这些结构化证据卡做跨来源兼容选择，不再次接收多张 raw tables；
   随后裁决器只基于这些结构化证据卡做跨来源兼容选择，不再次接收多张 raw tables。只有 `confirmed` 或由证据明确
   修正后的 `corrected` decision 才进入 deterministic bridge。
6. `deterministic_bridge`：代码验证 typed materials，执行允许的 events/N、mean/SD/N 转换和多臂/跨表兼容检查；
   LLM 不做最终算术。

### v12 的数值选择、研究臂身份与作用域边界

StudyMap 中每个实际随机研究臂由工程代码分配稳定的 article-local `arm_id`。每张表先保留自己的 arm observation，
包括 source ref、原标签、描述、角色和 candidate 引用；LLM 再根据具体干预语义和原文映射显式划分 canonical arms。
工程代码不通过字符串相似度自动合并，也不把共享 `Control`、`Treatment`、`experimental group` 等角色名称视为
同一研究臂。这样既能合并同一干预在不同表中的别名，又能保留多臂研究中名称相似但实际不同的剂量或方案。

StudyMap 更新后，工程代码通过严格规范化 canonical label 或唯一 alias，把 candidate 中的原表 arm 绑定到
`article_arm_id`。Resolution 和 verification 使用 `arm_id` 选择研究臂，原表格名称作为 `observed_arm_label` 保留审计；
若 observed label 唯一指向另一个 ID，verification 输出校验失败并按一次 retry 处理。最终 deterministic bridge 和其复用的
arm calculator/assembly 在存在 ID 时都只按 ID 收集材料，不再使用宽松 label equivalence 反向猜测身份。只有 candidate arm
尚未绑定且 verification 给出的原表名称与它严格一致时，才允许完成一次 verification-bound identity；宽松语义相似度不能
进入这条路径。多种名称映射到同一个 `arm_id` 时只算一个研究臂；两个不同 `arm_id` 即使都属于 review-level
intervention，也继续作为真实多臂处理。

Verification payload 将 proposal 决策改为 candidate/material ID 引用；完整 candidate 只在
`candidate_context` 中出现一次，非 candidate-owned 的跨表/正文材料放在 `support_material_context`，原始表格和
必要正文仍完整保留在 `raw_source_bundle`。这是对象去重，不减少验证器可读取的证据类型。

Result-blind resolution 是“提出候选并定位证据”的阶段，不是最终的分母裁决。只要模型能够定位一个可信的
article-local candidate（即使 arm mapping 或某些字段仍不完整），就会标记为 provisional 并送入 verification；验证器
会在 bounded raw table 中补齐缺失字段。不会因为 N 不是明确写成 `analyzed N` 就提前返回 `unresolved`。

Verification 读取原始表头、cell、脚注和正文，比较每个候选解释的完整 scope：outcome/measure/timepoint、arm、analysis
population、participant flow/attrition，以及是否有明确矛盾。它让 LLM 选择证据支持最强的数，而不是使用固定的
“表头优先”或“脚注优先”规则。随机化/基线 N 可以被选择，但必须标记为 `supported_inference`（或显式
`assumption`），不能伪装成直接报告的 analyzed N。

每个最终字段还记录 `selection_basis`、`selection_confidence` 和 `selection_rationale`。代码只校验引用、材料类型、
直接/推断标签的一致性和计算；它不替模型判断哪个 N 的语义 scope 更合理。只有没有可辩护候选，或完整证据下两个
解释确实无法区分时，verification 才返回 `unresolved`。这保留了可审计的保守边界，同时避免把“需要原文裁决”误判为
“没有数据”。

每个最终字段还必须返回 `evidence_scope`：article-local outcome/measure、timepoint、arm、analysis population、result
frame、row/item、column-header path、denominator scope、实际链接的 footnotes、带独立 source ref/kind 的 supporting quotes 和
`scope_status`。它是 provenance 和审计契约，不会覆盖 candidate 的既有 identity/local setting。
footnote 的文本必须可定位于候选表；整表脚注可以没有 marker。一个 census observation 的 StudyMap 可引用同一 raw
bundle 中其他表的事实，但 candidate 的 result block 和核心数值继续严格属于自己的单张表。

确定性 bridge 另外生成 `scope_assessment`。当字段使用 `supported_inference`、非 high confidence 或非 complete
scope 时，贡献仍保留（自动化原则是选择证据最强的可用数），并在 derivation/result item 中列出 warning；既有
`analysis_disposition=ready_for_estimate` 词汇保持不变，避免破坏下游 adapter，但下游不能把该 scope assessment
误读为明确报告的 analyzed denominator。

验证后，工程代码根据通用风险信号决定是否执行至多一轮 `scope_audit`：包括 raw table 中存在脚注/交叉引用结构、
跨表 field binding、非 high confidence、非直接 denominator、模型标记的 competing interpretation、scope_status 非
complete 或验证上下文超预算。审计器收到初始 verdict、风险信号和重新组装的原始来源；它不投票，也不使用固定的表头/脚注
优先级。它必须重新报告全部最终字段，并可确认、修正或在证据真正无法区分时返回 `unresolved`。审计后不再递归触发第二轮。

v8 在上述身份和 scope gate 之上增加 continuous direct-effect 路径。v9 保持 table-local candidate 边界，允许同一
bundle 内跨表 StudyMap 事实引用、允许无 marker 的可定位 table-wide footnote，并增加 target-level reason code；方法/
schema version 同时升级以使旧语义缓存失效。模型只从当前 candidate table 选择匹配的
MD 与 SE/CI，明确 experimental/control 的真实 arm 和报告方向；verification 重新读取原始来源。确定性 bridge
校验 effect/CI/SE 作用域，用双侧正态 CI 换算 SE，把 `control - experimental` 归一为
`experimental - control`，并生成 `GenericInverseVarianceResultData`。若两个臂的 result denominator 可确认，则
保存 participant count；否则保持为空。该行随后与 arm-level MD 使用同一 inverse-variance 统计池，不走第二套
Meta 算法。直接 SMD、ratio effect、P-only 推导及正文/图片 candidate discovery 仍不在当前边界。

v10 将 table census 改为一表一次调用，并把最终核验拆为逐来源 verification 与无 raw-table 的跨来源裁决；v11
进一步加入 source-local arm observation 的显式语义分区，并统一连续型 scale direction（量表高分代表更好或更差）
的判断契约。对于 post-intervention MD，方向未知不再丢弃原始 experimental-minus-control 数值，而是标记
`clinical_direction_status=unknown`；change-from-baseline 在变化方向未知时仍保持 unresolved，避免符号静默反转。
v12 将直接连续效应的原文证据拆为 `direct_effect` 与 `direct_uncertainty`：后者保存匹配的原文 SE 或 CI，最终
`standard_error` 只由确定性代码产生。Verification 与 adjudication payload 显式列出互斥的合法结果表示，避免把
不完整 arm-level 字段与 direct-effect 字段混为一组。经过逐来源验证且被最终跨来源裁决选中的 supporting evidence
会携带 `verified_field`、稳定 `article_arm_id`、source ref 和 candidate-local setting；计算层按 arm ID 和字段侧别
绑定，并允许 events、N、mean、SD 及白名单中间材料补齐既有 table-local candidate。它不能创建 candidate，也不能
绕过 source verification、target adjudication 或 calculator 校验。
v15 将 required source-verification path 限定为 resolver 已选择的 candidate/field materials，并让冻结的
`statistic_type_priority` 约束 verifier 可见的 result representations。被排除的 candidate 仍进入 resolution
provenance，但不再因可选字段的 quote 或结构错误阻塞主路径。跨来源 adjudication 区分硬语义冲突与不完整 scope：
完整数值表示可在保留 provisional scope warning 的情况下进入确定性 bridge。

v16 在 direct-effect GIV 的语义边界上允许 source-local verification 保留
`comparison_direction=unclear`，但不允许 confirmed/corrected adjudication 将其直接带入计算。跨来源裁决必须返回
`direct_effect_semantics`：比较方向、change-score 方向、证据基础、置信度和可审计理由。该方向只能依据已验证的
arm identity、量表方向、同一结果的来源解释等 grounded evidence 推断，不能依据治疗预期或重新编造数值。
确定性 bridge 使用裁决后的方向乘数，并同时记录 source direction、adjudicated direction 和 alignment，无法稳定判定时仍返回
`unresolved`。这不是新增 evidence-reading stage，也不改变候选选择、数值提取或统计计算边界。

当前由 `METHOD_VERSION/SCHEMA_VERSION/POLICY_VERSION=source_workspace_agent_v16_direction_adjudication` 标识；版本变化会使旧的
table-census/semantic cache 失效，避免跨 source-budget 合同复用语义结果。

每个阶段最多首次调用加一次 retry；provider/output failure 与文章证据不足分别记录。除顶层状态外，bridge 还为每个
未纳入 target 写入 machine-readable reason code，例如 `no_eligible_table_candidate`、
`no_compatible_table_candidate` 或 `unresolved_table_candidate`。source cache 以 source hash、
plan、prompt/schema 和 method 版本区分，debug artifact 记录每个阶段的输入摘要、调用状态和来源定位。

跨正文/表格 support 的 `source_spans` 会明确区分 `section` 与 `table_id`。共享稳定 data-row provenance 仍沿用旧
字段名 `field_provenance.table_ids`，其中可能暂时保存 section ref；修改这个字段名属于外部合同变更，不在本次
experimental method 切换范围内。

当前 limits：每篇最多 12 个冻结 target、32 张表和 32 个完整 table transport windows；每次 census 固定一张表，
最多 2 轮 investigation、8 个 section read windows。table-window 预算按表轮转分配，避免一张超长表
占满预算；未读完的表写入 `coverage.partial_table_ids`，coverage 为 incomplete。section investigation、verification 和单次
scope audit 各最多 160,000 字符、24 个完整 source windows，scope audit 最多一轮。完整来源能放入预算时优先发送完整 raw
source；不能放入时发送 grounded windows 加来源首尾窗口，并标记不完整。字符数或窗口数上限截断都会写入
transport metadata 会区分 `char_budget_limited`、`source_window_limited`、`search_result_limited` 和
`source_content_partial`；只有真实字符预算截断才作为 stage context limit。原有 `context_budget_exceeded` 字段保留作
兼容输出，但不会把搜索候选上限误判成模型上下文溢出。coverage warning 不会静默伪装成完整 source bundle。考虑字符预算可能使每个 table window
单独成 bundle，理论最坏上限为每篇 59 个 LLM stage calls、每个 stage 首次加一次 retry，因此最多 118 次 provider
attempts；一般文章远低于该上限。这些是工程上限，不是文章语义规则。`ArticleTable.raw_xml` 是正式输入字段，旧的
`rows[*]._raw_xml` 只作兼容回退。空 caption、空 section title 不会阻止 raw source 读取。当前方法的 unit tests 位于
`tests/unit/meta_analysis/test_source_workspace_agent.py`，live test 明确 opt-in。

少量 `gpt-5.4` 真实验证使用显式 test-only 开关，不改变本地默认模型：

```bash
RUN_LIVE_SOURCE_WORKSPACE=1 \
META_SOURCE_WORKSPACE_LIVE_MODEL=gpt-5.4 \
PYTHONPATH=backend/src:. \
.venv/bin/python -m pytest -q -s tests/integration/meta_analysis/test_live_source_workspace_agent.py
```

## ResultBlock 与 candidate

一个 candidate 对应一张表中的一个 `ResultBlock`：同一 outcome construct、measure、unit、timepoint、
population/subgroup、analysis population、result frame 和 statistic definition 下的全部 arms。任一维度改变
就拆成不同 block。Candidate ID 由 table、local setting 和 arms 确定性生成，不由 LLM生成。

Candidate discovery 的证据边界严格是当前 raw table 的 caption、hierarchical headers、rows 和 footnotes：

- 不传 abstract、Methods、Results prose 或其他表；
- 不用正文解释当前表没有建立的 arm code；
- 二分类保留 event/non-event count、percentage 及 analyzed/result-denominator/randomized/baseline N；
- 连续型保留 mean、SD、variance、SE、CI 及其 arm/between-group scope；
- effect estimate、t/F statistic 和 P value 可以作为 typed material 保留，但当前不用于 arm-level final row；
- LLM 不从这些材料推导缺失字段，推导只发生在后置白名单 calculator；
- 不确定的 cell/arm 绑定保留 null/uncertainty，不猜测。

每个 candidate 还保留模型的原始 `reported_statistic_type`，并由代码根据 typed materials 生成
`analysis_input_representation`。例如完整二分类 arm 数据为
`dichotomous_arm_events_total`，连续型经 arm-level SE 转换 SD 后为
`continuous_arm_mean_sd_total`。两者不再依赖模型自由文本保持一致；冲突时记录
`statistic_type_status=conflict`，但不因为描述字段冲突而丢弃有完整来源的数值材料。

每个 arm 带可核对的 source locator。单层结果可是一段原文；层级表头与数值 cell 必须共同建立含义时，可由多个
原文 fragment 组成并逐段检查存在性。Quote/locator 检查只产生 trace warning，最终 selected result 仍由独立
raw-table verification 复核；工程代码不以确定性表格解析替代 LLM 阅读。

## Resolution、跨表与计算

优先选择单个完整 ResultBlock。多臂 trial 可以选择同一 block 内的多个 eligible experimental/control arms；
二分类加总 events/totals，连续型使用样本量加权 mean 和正式 pooled SD 公式，全部由确定性代码执行。

跨表只用于同一文章中“一个 result block 缺少必要字段、另一 candidate 或 supporting material 明确补充该字段”的窄场景。Resolver 必须显式选择 candidate/material ID，并满足：

- 当组合多个 result block 时，outcome label/measure、timepoint、`analysis_input_representation` 和 analysis population 在每个来源 block 中均明确；当只有一个 result block、其余只是分母/participant-flow supporting material 时，不再强制 result block 额外填写不存在的 analysis-population 标签，但 supporting material 的显式 scope 不能与结果冲突，且必须保留 verifier 的来源与选择理由；
- outcome、unit、timepoint、population/subgroup、analysis population、result frame、change definition、scale
  direction 和 statistic definition 不冲突；
- 每个借用字段都有明确 material、candidate（适用时）、table 和 arm provenance；
- outcome-complete N 只有在 outcome/timepoint/arm scope 与 candidate 完全兼容时才可转为 analyzed N；
- randomized/baseline N 还必须有同一 outcome/timepoint/arm 的零失访证据，且没有冲突的 analyzed N。

这里的区别是业务边界而不是放宽数值校验：多个结果块的 identity gate 防止把不同结果拼在一起；单结果加支持材料是常见的“表中有均值/SD、正文或 caption 有 N”场景，不能因为文章没有正式命名 analysis population 就把已有的原文证据判成工程失败。

当前白名单转换是：

- 二分类：直接 events+outcome result denominator；non-events+denominator；reported percentage+denominator（只有报告精度唯一确定一个整数 events 时）。`events/N` 或与 event percentage 精确闭合的 N 可确认为 result denominator，但单独的 enrollment N 不可；
- 连续型：直接 mean+SD+analyzed N；variance 开方得到 SD；arm-mean SE 与 N 得到 SD；arm-mean CI 与 N 使用
  `t(df=N-1)` 得到 SD；
- between-group SE/CI 和 effect estimate 不会被误当作 arm SD；当它们在同一个 continuous MD candidate 中具有
  一致作用域时，可以进入 v8 direct-effect GIV 白名单。P/t/F statistics 仍不会触发任意公式。

同一臂的 counts、percentage 和 N 会做闭合/舍入一致性检查；冲突、作用域不明确或带未消解 uncertainty 的材料
不会进入最终计算。每个声称为 directly reported 的 value/CI bound 还必须实际出现在它的 source locator 数字片段
中；例如模型从 events/N 自行算出的 non-events 不会被当作直接材料。每个最终字段记录 input material IDs、source
tables、公式和假设。LLM 不进行算术。

缺少身份字段、值冲突、arm alias 不唯一或 provenance 不完整时返回 `unresolved`。连续型结果还必须明确为
`post_intervention` 或具有明确 subtraction order 的 `change_from_baseline`。LLM 不计算、合并或覆盖
数值；确定性 assembly 失败不会回退到猜测。连续型 effect alignment 完整时状态为 `ready`，否则为
`uncertain`，与下游 analysis-method contract 一致。

## 并发、重试与失败

- Application 最多并行 16 篇文章，使用 `executor.map` 保持 `included_studies` 顺序。
- 单篇文章内最多并行抽取 4 张互相独立的 table；所有 LLM 外呼仍受共享 client 的进程级 32-slot 上限约束。
- 仅当 candidate 缺最终 primitive 时，最多对 8 张已选支持表做一次 material-recovery call；没有缺口时为零额外调用。
- 每个 LLM stage 只允许首次调用加一次 retry。可重试 provider error 和非法 LLM output 可进入第二次；
  非可重试 provider error 立即失败，未知程序异常不重试。
- Source-workspace 的单次 LLM 请求使用 300 秒方法级 timeout；这是针对 GPT-5.4 长表格和严格结构化输出延迟的
  技术上限，不改变 context budget、prompt、retry 次数或证据判断规则。
- 一篇文章在 retry 后仍为 provider/output failure 时，其他文章继续。该文章为 `technical_failure`，coverage
  标记不完整，不能伪装成 `data_unavailable`。
- Provider error 由共享 LLM client 分类为 timeout、upstream connection、server、rate limit、authentication、
  request rejection 或 transport error；成功返回但违反 stage validator 的结果分类为 `invalid_model_output`。
  Application 将细类、失败 stage、attempt、status/request ID 和有界详情写入 resolution 与 dataset provenance，
  顶层 `technical_failure` 状态保持兼容。每次 attempt 的 debug artifact 与失败 metadata 还保存实际 input summary，
  便于区分 context/预算问题、provider timeout 和模型输出校验失败。
- 缺少全局配置、输入契约错误或程序错误仍使整个 Meta-analysis 调用失败。

设置 `META_STUDY_EVIDENCE_DEBUG_DIR` 后，每篇文章写入 input、controller turns、table maps、table candidates、
resolution、verification 和 final artifacts。Artifacts 包含 source IDs、warnings 和状态转移；完整 trace 不塞入
紧凑业务输出。

## Benchmark 接入

Benchmark production method 名称仍是 `method_article_evidence_agent`（兼容名称，实际调用 source-workspace production adapter）。Adapter 从 benchmark instance 的
`analysis_setting` 构造冻结 targets，按 article 调用 backend method，再返回 `study_result_rows` 供 Subtask 2
指标评估。Backend 不 import benchmark、gold、dataset 或 evaluator。

主开发集仍为 `cochrane_meta_v2-key-filter`；更严格 variant 只用于定向审计，未过滤全集只用于 robustness audit。

## 验证入口

```bash
PYTHONPATH=backend/src:. .venv/bin/python -m pytest -q tests/unit/meta_analysis
```

真实模型测试必须显式 opt-in，并优先使用 `gpt-5.4-mini`。当前方法没有大模型 fallback；启用更大模型需要另行
批准。

### 当前验证覆盖与已知限制

截至 2026-07-20，`tests/unit/meta_analysis` 有 155 个单元测试，整个 `tests/unit` 有 496 个；其中
source-workspace 方法有 32 个单元测试，calculator 有 8 个。单元测试使用 fake caller，不代表 155 篇真实文章。
在显式 `gpt-5.4` 的 source-only 真实 smoke 中，二分类 Desai 2018 已通过，连续型 Janyacharoen 2018 已通过（原始
Table 4 的 12 周 KOOS：68.3/8.9/20 对 51.6/1.2/20）。Li 2020 的连续型数值均值和 SD 稳定提取，但对照组
13 周单元格带有 `f` 脚注（`n=22`）而表头为通用 `n=24`；该类结构现在会触发通用 scope audit，而不是由代码规定哪一处
优先。连续型计算、scope provenance 和原文可追溯性仍需用少量受控 live run 验证，不能把单次模型结果当作方法学真值。
Production factory 只暴露 source-workspace method。

待办：当前 source-workspace 只会把已验证的臂级 `events/N` 或 `mean/SD/N` 组装为正式
`MetaAnalysisDataRow.result_data`。对于文章直接报告的组间 `MD + CI/SE` 等 Generic Inverse Variance 输入，方法可以
发现并保存 effect estimate、SE、CI 等 typed materials，但尚未定义稳定的 direct-effect result-data 契约，也未接入
Subtask 3-5 的统计入口。未来实现前需要先明确原始证据、中间确定性推导和最终标准化统计输入的分层，以及 effect
measure、分析尺度、方向、adjusted/unadjusted 和 target compatibility 的门禁；本轮暂不修改代码或 prompt。
