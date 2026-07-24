# Meta-analysis 实现说明

## 当前调用链

```text
POST /modules/meta-analysis
  -> interfaces/api/dependencies.py
  -> RunMetaAnalysis.execute(...)
     -> SynthesisPlanningPort
     -> StudyEvidencePort             # one article × all frozen targets
     -> AnalysisMethodsPort
     -> SubgroupAnalysisPort          # parallel with overall
     -> OverallEstimatesPort
  -> MetaAnalysisResultPackage
```

`RunMetaAnalysis` 位于 application，负责 EBM stage 顺序、article-level 并发、target/study 参数传递、部分失败
政策、确定性输出顺序和 domain package 组装。Infrastructure 只实现各 concrete capability，不反向调用 use case。

## 目录与 factory

```text
infrastructure/methods/meta_analysis/
  factory.py
  synthesis_planning/synthesis_plan_llm/
  study_evidence/source_workspace_agent/
    method.py
    context.py
    working_state.py
    evidence_state.py
    source_workspace.py
    schemas.py
    prompts/
  analysis_method_selection/contextual/
  subgroup_analysis/statistical/
  overall_estimation/statistical/
```

`factory.py` 暴露当前 production builders；Study Evidence 默认使用
`source_workspace_agent`。`article_evidence_agent` 包仅保留当前 production 复用的 schema、calculator 和
确定性 assembly helper，不再作为独立 factory method 暴露。旧的 `source_local_candidate_extraction +
semantic_rules` 和更早实验不属于维护源码；本地历史快照仅可放在被 Git 忽略的 `archive/` 中。Factory、
application、API、benchmark production adapter 和维护测试均不得导入这些本地快照。

Method name 不进入 HTTP/application contract，也不存在跨业务 registry、resolver、dynamic loader 或 service
locator。API composition root 一次加载 `LLMConfig`，再注入 planning 和 Evidence Agent；当前运行中修改
`llm.local.json` 只影响下一次 use-case construction。

## Synthesis Planning

`synthesis_plan_llm` 只接收 question、PICO 和 frozen screening criteria。它拒绝 articles、included studies、
Study PIO、Risk of Bias 和 observed result values，避免根据结果事后改变计划。

`RunMetaAnalysis.plan(...)` 暴露这一步的 application-level 调用。完整 workflow 在 Screening criteria 确定后、
文章判定前调用它；生成的 domain plan 先供 staged Screening 做 target-level evidence navigation，之后原样传给
`RunMetaAnalysis.execute(..., synthesis_plan=...)`。独立 Meta API 省略该参数时仍会内部 planning。Planner method、
prompt 和 plan contract 没有两套实现。

工程边界负责 supported data type、target/family ID、最多十二个 targets、去重、plan version/hash 和
`frozen/not_plannable`。当前支持 `Dichotomous` 与 `Continuous`；time-to-event、rate/count、未二分 ordinal 等
进入 `unsupported_targets`。没有 supported target 时 application 直接返回计划，不调用 Evidence Agent 或统计
adapter。

每个 target 冻结 comparison、outcome/measure、结构化 timepoint、subgroup、result-selection policy、effect
measure 和 common/varying-effects assumption。Timepoint、analysis population、endpoint/change frame 和 source
priority 的选择规则必须 result-blind；无法形成有依据的规则时 target 为 `insufficient_planning_basis`。

## Article Evidence Agent

Application 为每篇 included article 调用一次当前的 `source_workspace_agent`，一次传入全部冻结 targets。文章被视为
不可变 source workspace；raw table 以完整 transport window 传给 LLM，不做确定性表格解析。每个 target 最多一行
`StudyResultRow`、一条 resolution record，并可产生一个 deterministic-assembled `MetaAnalysisDataRow`。

调用顺序是：

1. `table_census` 并行读取预算内的 raw table windows，发现 article-local ResultBlock 和 typed materials；候选必须
   来自单一当前表，表格 caption、表头、cell、脚注都由 LLM 解释。
2. `investigation` 最多两轮，根据 source catalog、StudyMap 和 evidence needs 搜索或重读少量 section；正文只补充研究
   设计、臂标签、随访、分析人群或跨表 supporting material，不把正文数字伪装成 candidate table 事实。
3. `arm_reconciliation` 只接收 source-local arm observations 和 arm-related StudyMap 投影，不接收 synthesis targets；
   它建立 article-level arm identity，但不选择分析结果。
4. `result_blind_resolution` 隐藏候选数值和效应方向，只选择 article-local candidate、比较臂、需要的 field/material
   和来源，不做算术。
5. `source_verification` 对每个原始来源独立重读，核对 outcome/measure/timepoint、arm、result frame、分析人群、
   denominator scope 和 quote；一个来源看不到另一个来源的 raw content。
6. `cross_source_adjudication` 只读取已经 grounded 的 source reviews，不携带 raw source，在兼容性门禁后选择最终字段。
7. `deterministic_bridge` 只在代码验证 provenance、作用域和 typed materials 后，计算 events/N、mean/SD/N、跨表补字段
   及多臂合并。LLM 不做最终算术。

### Context 与工作状态

Raw XML/section text 始终保存在不可变 `SourceWorkspace`，不会被摘要替代。`context.py` 为 census、investigation、arm
reconciliation、result-blind resolution、source verification 和 adjudication 分别建立字段白名单；每次调用只投影该
stage 需要的 target、candidate、material 和 StudyMap 信息。Source hash、article hash、字符偏移、plan notes、analysis
model 及 trace state 不进入无关调用。长 target/candidate/material/source IDs 使用可逆的 call-local aliases，artifact
保留映射。

`working_state.py` 把 table census 产生的 evidence needs 记录为 `pending/resolved/blocked/superseded` 工作项。Investigator
只能用本轮已读或 notebook 已有来源关闭 need；完成项退出 active context，但完整状态保留在 debug artifact。初始 section
bootstrap 最多使用三个 query 和四个 read windows，并至少为后续 agent action 保留一个 search/read 单元（总预算大于一时）。

调用前预算同时计算 system、JSON payload、strict schema、provider overhead 和最大输出，不再只统计 raw-source chars。
预算来自 `LLMConfig.context_window_tokens`；无法容纳 protected raw evidence 时在 provider 调用前返回明确的
`context_budget_exceeded` technical failure。当前阶段不会有损压缩或截断一张已选中的 raw table window。

候选保留 outcome、measure、unit、timepoint、population/subgroup、analysis population、continuous frame/change
definition、scale direction、统计材料和不确定性。二分类与连续型共用同一证据管线；当前支持 pairwise arm-level
events/N 和 mean/SD/N（含白名单的 percentage、variance、arm-level SE/CI 转换）。Randomized/baseline N 不自动等同
analyzed N，若模型只能选出最佳支持的推断值，会在 `scope_assessment` 中标记 warning，而不伪装成直接报告。

Candidate ID、source hash、study/target IDs 和 trace metadata 由代码生成。最终业务输出按 target 排序；候选与完整 provenance
留在 extraction/resolution/debug 层，统计阶段只消费 `MetaAnalysisDataRow[]`。

## Analysis Method 与估计

Subtask 3 接收 final `AnalysisSetting` 和 resolved `MetaAnalysisDataRow[]`。它只实现 plan 预设的 effect measure 与
common/varying-effects model，不根据 observed heterogeneity 事后选模型。缺少计划字段返回 `invalid_plan`，
data type 与 effect measure 不兼容返回 `incompatible_effect_measure`。

Subtask 3 完成后 application 以两个 workers 并行调用 subgroup 和 overall adapters。当前统计 policy 为
`cochrane_revman_v1`：

- binary RR/OR/RD 与 continuous MD/Hedges g SMD；
- common-effect binary 使用 Mantel-Haenszel，common-effect continuous 使用 inverse variance；
- varying-effects 使用 inverse variance，`k >= 2` 时使用 REML，当前 CI 为 Wald；
- overall random-effects 且 `k >= 5` 时才启用 prediction interval；
- Hedges g variance 使用 RevMan `N - 3.94` 小样本公式；
- REML I2 使用 tau2/typical within-study variance，common-effect 使用 Q-based I2；
- RR/OR 单研究 continuity correction 不改写 fixed MH 的 observed counts/weights；
- endpoint/change 或 SMD scale direction 不满足 frozen policy 的 row 在 method selection 阶段明确排除。

Final data rows 必须从 `pending` 转为 `included`、`excluded` 或 `not_analyzed`。Included row 带 study effect、CI、
variance、standard error、raw weight 和同一 estimate 内归一化的 `weight_fraction`。

Study-level subgroup 使用独立 evidence bodies 的 Q-between。Participant-level interaction 只支持两个明确互斥
levels 且至少两个 paired studies：先计算 each-study within-study interaction，再跨研究汇总。关系未知、重叠、
超过两个 levels 或配对不足时不生成未经支持的检验。

## 并发与失败

- 共享 LLM client 进程级上限为 32 个同时在途请求。
- Application 最多并行 16 篇 articles，`executor.map` 保持 `included_studies` 顺序。
- 单篇 article 的 table census bundle 最多并行四个；每篇最多 32 张表、32 个完整 table windows，窗口预算按表轮转。
- section investigation 与 source verification 都有独立字符/窗口上限；source 预算耗尽会标记 incomplete coverage。
- Subgroup/overall adapters 在 method selection 后以两个 workers 并行。
- 每个 LLM stage 为首次加一次 retry；SDK retries 和 JSON-marker compatibility retry 在 method config 中关闭。
- 可重试 provider error 与非法 LLM output 可进入第二次调用；非可重试 provider error 立即失败，未知程序异常不
  retry。

单篇 article 的 `MetaAnalysisInvocationError`/`MetaAnalysisOutputError` 在 retry 后仍失败时，application 生成
`technical_failure` rows/records 和 incomplete coverage，其他 articles 继续。结果 estimates 会携带 partial
coverage note。真实无数据才是 `data_unavailable`。配置缺失、输入错误、adapter contract 错误和未知程序异常
仍终止整个 Meta-analysis 请求。

HTTP 错误继续使用 `meta_analysis_configuration_unavailable`、`meta_analysis_stage_invocation_failed`、
`meta_analysis_stage_retry_exhausted`、`meta_analysis_invalid_method_output` 和 `meta_analysis_invalid_input`。

## Observability

设置 `META_STUDY_EVIDENCE_DEBUG_DIR` 后，Evidence Agent 按 article context 写入：

- 输入 target/source catalog 与版本；
- 每个 LLM attempt 在请求发出前写入 `started`，完成后原位更新为 accepted/provider error/invalid output；
- `call_ledger.jsonl` 中的逐 attempt 状态、耗时、request ID、provider usage 和输入组件 token 估算；
- 每个 table census merge、investigation round、arm reconciliation、resolution 和 verification 的 state checkpoint；
- canonical evidence、working decision state 与 coverage/warnings 的分层调试视图；
- final rows、records、coverage 和 warnings。

完整 raw sources 和长 trace 只在 debug artifacts 中，业务 package 保持紧凑。当前 source-workspace
method/schema versions 为 `source_workspace_agent_v16_direction_adjudication`；typed-material 确定性转换继续使用
`cochrane_arm_material_calculator_v1`。共享的确定性 helper 继续由 production source-workspace adapter 使用。

## GRADE 交接

Application 使用 matched estimate 的 `included_data_row_ids` 选择最终 data rows。完整、有限且归一化的
`weight_fraction` 传给 GRADE Risk of Bias；单研究 effect/CI/analysis scale 与 weight 传给 Inconsistency。
GRADE 不重新计算 Meta study effect 或 weight。

Article-local candidate IDs 只保留在 extraction/resolution provenance；final `AnalysisSetting`、overall/subgroup
estimate、subgroup test 和 GRADE row 不含 candidate ID。Legacy benchmark 若需要评测 join key，由 benchmark
adapter 在 backend 输出后补充。

## API 与 workflow

`MetaAnalysisRequest` 要求 `screening_criteria`，且 `included_studies` 与 `articles` 严格一一对应、各最多 500 项。
完整 workflow 在 Search 后先生成 Screening criteria 与 result-blind Meta plan，再运行 staged Screening；随后
并行启动 Study PIO、RoB 和使用同一 frozen plan 的 Meta。三者互不作为彼此输入。Workflow 保留 Meta 的
plan、candidate rows、resolution records、datasets、data rows、methods 和 estimates，文章全文本身不返回最终下游。

## 验证

普通回归：

```bash
PYTHONPATH=backend/src:. pytest -q tests/unit/meta_analysis tests/integration/meta_analysis
```

Live E2E 默认 skip，需 `RUN_LIVE_META_E2E=1`。新 Evidence Agent 首轮只使用 `gpt-5.4-mini`，没有大模型 fallback；
切换 GPT-5.4 或 `openai/gpt-5.6-terra` 需要用户批准。Benchmark production method 名称仍为
`method_article_evidence_agent`（名称保持兼容，实际调用 production factory 的 source-workspace adapter），主要开发数据集为
`cochrane_meta_v2-key-filter`。

当前支持边界仍是个体随机平行组、pairwise、arm-level binary/continuous data。Cluster/crossover adjustment、
time-to-event、rate/count、ordinal、adjusted-contrast-only、shared-control splitting 与 network meta-analysis 不在
当前 production 范围。
