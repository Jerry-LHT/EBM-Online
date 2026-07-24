# Study Screening 任务契约

本文定义 Study Screening 的稳定业务契约。当前实现见
[`docs/implementation/study-screening.md`](../implementation/study-screening.md)。

## 任务目标与粒度

Study Screening 根据 review question、结构化 PICO、screening policy 和候选文章证据执行最终二元排纳。
当前输入与判断单位仍是 article/report，尚未完成多个 reports 到真实 study 的归并。

完整 workflow 在本模块前增加一个可缓存、与具体 review 无关的 article-type qualification，然后使用提前冻结
且 result-blind（不读取文章结果）的 `MetaAnalysisSynthesisPlan` 做两阶段 review 筛选：

1. article-type qualification 只读取文章内容，不读取 PubMed Publication Type/MeSH 标签；判断是否为 primary
   randomized trial results report，明确不合格才排除，不确定和技术失败都继续；
2. 高召回粗筛只读取 title、完整 abstract（若存在）和少量原始正文段落；只有明确的设计、report、P、I
   或 C 不匹配才排除，证据不足必须进入精筛；
3. 精筛读取按 frozen targets 导航的原始正文段落及完整 raw table XML/明确标注的原始 XML 切片，一次调用
   同时判断正式 Review eligibility 与 target-level Meta readiness。

模块级 `POST /modules/study-screening` 仍保留原来的 `abstract | full_text` 单阶段方法，供独立筛选使用；上述
两阶段语义属于完整 workflow 的 production composition。

最终 decision 只有：

- `include`
- `exclude`

criterion judgment 只有 `yes` 和 `no`，不输出 `unclear`。对于必要 inclusion criterion，证据不足以确认满足时
返回 `no`；对于 exclusion criterion，只有证据确认触发时才返回 `yes`。

## 输入契约

HTTP 输入包括：

- `question_text`：非空 review question；
- `question_pico`：Q2PICO 输出；
- `articles`：最多 500 个 `CleanedArticle`，`study_id` 必须唯一；
- `synthesis_plan`：完整 workflow 必需，由 Meta Synthesis Planning 在读取文章前生成并冻结；模块级单阶段
  API 不要求该字段；
- `evidence_scope`：`full_text` 或 `abstract`，默认 `full_text`；
- `rct_only`：默认 `true`；
- `report_scope`：`primary_results_report` 或 `all_study_reports`，默认前者；
- `outcome_eligibility_enabled`：默认 `false`；
- `publication_year_start` / `publication_year_end`：可选结构化年份范围；
- `allowed_languages`：可选 NLM/PubMed language code 集合；
- `exclude_retracted`：默认 `true`。

旧字段 `publication_year_range="YYYY-YYYY"` 暂时兼容，但不能与结构化年份字段同时使用。

`rct_only=true` 会追加稳定系统标准，要求研究使用随机分配。当前 pairwise workflow 还会追加必要 inclusion
criterion，要求个体随机、平行组设计；cluster-randomized、crossover、cluster-crossover 和其他非平行分配设计
均不满足该标准。全文证据无法确认普通个体随机平行组设计时，该必要 inclusion criterion 为 `no`。
`report_scope=primary_results_report` 会追加稳定系统标准，要求当前文章是试验的原创主要结果报告，而不是
protocol、review、editorial、commentary、correction 或 retraction notice。

Primary results report 不等于“目标 outcome 数值已经可以直接提取”。Outcome 默认不发送给 criteria planner；
只有显式开启 `outcome_eligibility_enabled` 时才可规划 outcome-measurement eligibility。完整 workflow 的精筛
并不把数据可用性伪装成 review eligibility criterion，而是额外输出 target-level synthesis readiness。
Review 纳入文章继续进入 Study PIO 和 RoB；只有 Meta-ready 或需要 Meta agent 进一步核查的文章进入 Meta。

## Metadata 契约

`ArticleMetadata` 支持：

- PMID、PMCID、DOI、title、publication year、MeSH；
- PubMed publication types；
- languages；
- trial registration identifiers；
- related article types；
- retracted、retraction notice、correction flags。

明确的 metadata 事实只在下列硬规则中做 deterministic judgment：

- 年份是否在范围内；
- language 是否允许；
- 是否撤稿或属于撤稿通知。

PubMed Publication Type、MeSH、trial identifier 等不得确定性排除，也不发送给 article-type、粗筛或精筛 LLM，
避免把 provider indexing 当作文章内容并产生锚定偏差。文章类型和 RCT 状态由原文证据判断。
年份或语言 policy 已启用但对应 metadata 缺失/无效时，必要 inclusion criterion 判为 `no`。

## 输出契约

`StudyScreeningResult` 包含：

- `screening_criteria`：review-specific criteria 加稳定系统 criteria；
- `decisions`：按输入文章顺序排列；
- `included_articles`：decision 为 `include` 的 article-level IDs；
- `excluded_articles`：decision 为 `exclude` 的 article-level IDs；
- `included_studies`：当前为兼容既有下游保留，值与 `included_articles` 相同。
- `coarse_decisions`：完整 workflow 的粗筛结果、证据 spans 和实际输入字符/来源数量；
- `synthesis_readiness`：按 article ID 保存每个 frozen target 的可执行性；
- `methodologically_eligible_unsupported_studies`：方法学上符合 review 且有定量结果，但只有当前 runtime
  不支持的数据形态（例如 adjusted contrast-only）的文章。
- `meta_ready_studies`：至少一个 target 已建立当前 Meta 接受的数据表示；
- `meta_investigation_studies`：target 可能可分析，但需要 Meta evidence agent 继续读原始来源；
- `meta_unavailable_no_readable_table_studies`：Review 已纳入，但没有非空 canonical `raw_xml` 表格，因当前
  Meta candidate discovery 的 table-local 边界而不进入 Meta；仍进入 Study PIO 和 RoB。

每个 `ScreeningDecision` 包含 decision、rationale、首个决定性 exclusion reason、criterion judgments 和经过
输入证据子串校验的 source spans。每个 judgment 标明 `decision_source=deterministic|llm`。完整 workflow 的
decision 还包含 `meta_entry_target_ids`、`meta_investigation_target_ids`、
`methodologically_eligible_unsupported_target_ids`、`meta_routing_status`、可选 `meta_unavailable_reason` 以及
精筛输入大小。

Target readiness 有四种：

- `current_meta_supported`：target 语义匹配，并有当前 runtime 接受或可确定性推导的双臂二分类
  `events/N`、连续型 `mean/SD/N`、可确定性推导的兼容 arm-level 输入，或适合 generic inverse-variance
  （通用逆方差法）的直接 effect + CI/SE；
- `needs_meta_investigation`：target 看起来符合且可能可分析，但受限于部分来源覆盖、跨来源绑定、arm 别名、
  分母作用域、timepoint、result frame 或 uncertainty，需要 Meta agent 复核；
- `methodologically_eligible_unsupported`：target 方法学上可用且存在定量结果，但仅有调整后/组间 contrast
  等当前 runtime 不支持的表示；
- `not_eligible`：target 不匹配，或当前读取的文章证据不能建立可用定量结果。

LLM 只判断证据语义与材料形态，不做数值计算。Target key 到 frozen `target_id` 的绑定、source span 校验、
最终 include/exclude 聚合和列表顺序均由代码确定。

最终聚合规则：

1. 任一 exclusion criterion 为 `yes`，最终 `exclude`；
2. 否则任一 inclusion criterion 为 `no`，最终 `exclude`；
3. 其他情况最终 `include`。Meta readiness 不参与这三个 Review eligibility 聚合规则。

完整 workflow 在 eligibility 聚合后独立应用 Meta routing：`current_meta_supported` 或
`needs_meta_investigation` 且存在非空 canonical raw table 才进入 Meta。无表格是确定性的当前实现边界，不是
医学排除，也不表示原文没有结果。若只有 `methodologically_eligible_unsupported`，必须保留独立状态，不能
表述为文章没有结果。

## 失败语义

- criteria planning 首次失败后 retry 一次；
- 粗筛和精筛分别按文章独立执行，首次失败后各自 retry 一次；底层 SDK retry 关闭，因此每个 stage 确实最多
  两次 provider 调用；
- JSON Schema、criterion judgment 或 reason 的结构校验失败计入同一 retry budget。`evidence_spans` 是可选
  provenance：工程会保留可在当前输入证据中逐字或经格式归一化匹配的 spans，并丢弃无法追溯的 spans，不改变
  criterion judgment；
- 任一必须 LLM stage 在两次尝试后仍失败，整个任务失败；技术失败不得转换成 exclusion；
- deterministic 年份、语言、撤稿以及 Meta raw-table existence 规则不是技术失败，不 retry。
- `ScreeningDecision.exclusion_reason` 返回触发排除的具体 judgment reason，而不是 criterion 标题；完整
  criterion 与 judgement 仍保留在 `criterion_judgments` 中。

API 稳定错误：

- HTTP 400：`study_screening_invalid_input`；
- HTTP 503：`study_screening_configuration_unavailable`；
- HTTP 502：`study_screening_criteria_retry_exhausted`；
- HTTP 502：`study_screening_article_retry_exhausted`。

## 方法学边界

Cochrane 建议最终 inclusion decision 尽可能基于全文。完整 workflow 因此把 title/abstract/少量正文只用于
高召回粗筛，正式判断仍读取定向全文和原始表格。所有 LLM evidence calls 使用共享 model-context budget，
预留 schema、输出与安全空间；不采用 append-only 全文。Section title 为空或很短、table caption 缺失不会使
source 不可见：导航同时使用正文或 raw XML 内容。正文优先传完整 XML paragraph；超限才输出有坐标的
`section_excerpt`。小表传完整 raw XML；大表只传有字符坐标并明确标记 partial 的 exact `table_slice`。
Partial coverage 不能证明“文章没有报告”。导航只选择材料，不做确定性表格解析或数值抽取。

本模块不负责 report-to-study collation、数值抽取、Risk of Bias 或 Meta-analysis。多报告归并前不能把
`included_articles` 当成已经去重的真实 studies。
