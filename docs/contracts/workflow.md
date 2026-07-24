# 完整证据链 Workflow 任务契约

本文定义 `POST /workflow`、`GET /workflow/runs/{run_id}`、
`GET /workflow/runs/{run_id}/evidence-package` 和 application `RunOnlineEBMWorkflow` 的稳定业务边界。
Workflow 的产品产物是紧凑的完整循证医学证据链，不是单独的 GRADE 结果，也不是内部调试对象的完整转储。

## 输入

- `review_id`、自然语言 `question_text`。
- `expand_outcomes`，默认开启 Q2PICO outcome expansion。
- 检索来源、可选引文清单上限和全文处理上限；默认分页保留最多 10,000 条引文，并最多处理 500 篇全文。
- RCT 开关与可选发表年份约束。

当前 HTTP 入口固定使用全文筛选。来源和数量属于接口配置，不暴露内部 method name。

## 执行顺序

1. 顺序执行 Q2PICO 和 Search Retrieval；检索分页保留引文清单，只为最多 500 篇有 PMC XML 的文章形成
   `CleanedArticle`。
2. 对全文先执行确定性 precheck（撤稿、显式年份范围），再执行可缓存的 content-based article-type
   qualification。该 LLM 阶段不读取 PubMed Publication Type/MeSH；明确非 primary RCT results report 才排除，
   不确定或技术失败继续。
3. 生成 Screening criteria 和 result-blind Meta synthesis plan，随后执行高召回粗筛和一次定向全文精筛。
   精筛同时输出 Review eligibility 与 per-target Meta readiness，两者不互相改写。
4. Review included 的所有文章进入 Study PIO 和 study-level RoB 1，不按 retrieval/screening 顺序做科学性
   top-N 截断。只有 `meta_ready` / `needs_meta_investigation` 且存在非空 canonical raw table 的文章进入 Meta；
   无表文章仍保留 Review 纳入。
5. Study PIO、RoB 和 Meta 以最多三个 worker 并发；Meta 使用前面同一个 frozen plan，不重复 planning。
6. 三个并行分支全部成功后，执行 Four-domain GRADE。
7. Stage 记录和并行结果始终按固定业务顺序输出。

## 内部审计结果

application `RunOnlineEBMWorkflow` 和持久化层继续使用完整的 `OnlineEBMWorkflowResult`，其中包含：

- 服务端生成、唯一标识本次执行的 `run_id`；
- `persistence_status`（`succeeded | partial | failed | disabled`）以及持久化异常时的
  `persistence_error_code=workflow_persistence_failed`；
- `question_pico`；
- `search_retrieval` 轻量摘要；
- `article_precheck` 和 `article_qualification` 漏斗结果；
- `study_screening` criteria、coarse decisions、target readiness、最终 decisions、included study IDs，以及
  methodologically eligible but runtime-unsupported study IDs；
- `study_selection`：全部 Review eligible、进入 Study PIO/RoB 的 IDs、进入 Meta 的 IDs，以及因当前 Meta
  边界未进入 Meta 的 IDs；不存在科学性 top-N 截断；
- `study_pio`；
- study-level `risk_of_bias`；
- 完整 `meta_analysis` package，包括 synthesis plan、analysis settings、study result/data rows、分析方法、
  subgroup 与 overall estimates；
- `grade`；
- 每个 stage 的 `status`、output 或 error。

检索到的 `CleanedArticle`、文章全文和详细 metadata 是流程内部证据材料，不属于 workflow 输出。检索摘要
只保留来源、实际 query、命中/返回数量、warnings 和 `retrieved_study_ids`，足以连接后续证据对象而不复制原文。

`GET /workflow/runs/{run_id}` 返回该完整审计结果，供运行排错、溯源和恢复检查使用；它不是推荐给普通下游的
产品契约。

## 下游 EvidencePackage

`POST /workflow` 和 `GET /workflow/runs/{run_id}/evidence-package` 返回版本化的
`EvidencePackage`。其固定顶层结构为：

- `schema_version`、`run_id`、`review_id`；
- `status`：分别表示程序执行、证据完整性和是否适合继续交给下游；
- `protocol`：原始问题、review PICO、最终 screening inclusion/exclusion criteria；
- `search_summary`：各来源命中、引文清单、全文取回及 warning codes，并保留 precheck、文章类型、Review
  筛选和 Meta routing 各层漏斗计数；
- `studies[]`：每个纳入 study 的紧凑 Study PIO 与 article-level RoB 1 domains/overall；
- `evidence_units[]`：每个 synthesis target 的目标定义、覆盖完整性、结构化单研究效应、Meta 合并结果、
  subgroup 结果和 four-domain GRADE 判断。

GRADE 在该契约中明确标记 `scope=four_domain_partial_grade`，并固定
`overall_certainty=null`。当前没有 publication bias 判断，因此不得伪造完整五域 certainty。

`EvidencePackage` 不包含原文/XML/sections/tables、被排除文章详情、prompt、LLM 原始输出、Meta candidate、
supporting materials、candidate resolution trace、source spans 或 workflow stage debug output。这些信息仍保留在
内部审计结果或模块 debug artifact 中。

`status` 语义：

- `execution_status`：workflow 实际执行状态；
- `evidence_status`：`complete | partial | no_eligible_studies | insufficient_for_synthesis | failed`；
- `ready_for_downstream`：只有不存在未解决/技术性证据缺口时才为 true；没有合格研究或有据可判定无法合并，
  是可消费的结论，不等同于技术失败；
- `reason_codes`：机器可读原因。比如某篇 study result 抽取技术失败时，即使 workflow 顶层执行完成，仍输出
  `execution_status=succeeded`、`evidence_status=partial`、`ready_for_downstream=false`。

当前没有基于篇数或 rank 的 downstream top-N。API 的 500 篇上限限制的是本次全文处理工作量，不是 Review
纳入或 Meta 选择规则；已保留但未处理的引文通过 `remaining_full_text_count` 和 `truncated` 明确呈现。

## 失败与部分结果

- Q2PICO、检索、synthesis planning 或筛选失败时停止后续执行，保留此前已成功产物，并将后续 stage 标记为
  `not_run_due_to_upstream_failure`。
- Study PIO、RoB 和 Meta-analysis 任一分支失败时，等待其他已启动分支结束，保留成功分支产物，GRADE 不运行。
- GRADE 失败时，完整保留其全部上游证据链。
- Workflow 业务执行失败仍返回结构化结果和 HTTP 200；只有 composition/configuration 无法构造流程时返回
  HTTP 503 与 `workflow_configuration_unavailable`。

`execution_status = failed` 不代表响应为空。产品下游读取 `EvidencePackage.status`；审计调用方可进一步读取
`GET /workflow/runs/{run_id}` 的 stage records。

## 本地持久化与查询

产品 API 为每次完整 workflow 创建文件级运行记录，并在每个已完成 stage 后保存 checkpoint；最终保存完整
`OnlineEBMWorkflowResult`。持久化写入失败不改变医学 workflow 的成功或失败状态，而通过独立的
`persistence_status` 暴露。`GET /workflow/runs/{run_id}` 返回完整结果；
`GET /workflow/runs/{run_id}/evidence-package` 从同一持久化结果确定性投影产品结构。如果进程在最终结果写入前
退出，审计接口返回已经保存的 stage 快照和 `status=running` 的部分结果，EvidencePackage 接口也会明确标记
其 execution/evidence 状态，不会伪装成完整结果。

第一版不自动从 checkpoint 恢复执行，也不把同步 API 改成后台任务。Meta-analysis 内部 substages 只在完整
Meta stage 返回后一起保存；若进程在 Meta 内被强制终止，只保证保留 Meta 之前已经保存的 workflow stages。

`CleanedArticle` 和全文不复制进 workflow run 结果；它们由独立的 provider cache 保存，workflow 结果继续只
暴露轻量检索摘要。

查询错误码：

- `workflow_run_not_found` (404)
- `workflow_run_invalid_id` (400)
- `workflow_run_corrupt` (500)
- `workflow_persistence_unavailable` (503)
