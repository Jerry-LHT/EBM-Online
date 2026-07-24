# Search Retrieval 实现说明

本文档记录 `search_retrieval` 模块当前的真实后端实现边界。

稳定业务语义见 [`Search Retrieval 任务契约`](../contracts/search_retrieval.md)。

当前实现目标不是 benchmark 评测，而是独立后端里可复用的真实 EBM 检索与全文清洗能力。

## 1. 模块职责

`search_retrieval` 负责完成这条业务链路：

```text
QuestionPICO
-> search strategy orchestration
-> ordered retrieval source adapters
-> source-specific query compilation
-> paged citation inventory / bounded full-text acquisition / cleaning
-> SearchRetrievalResult
```

它是一个 workflow module，不再往外拆成新的业务模块。

## 2. 分层边界

Application 负责编排检索策略和执行链：

```text
RunSearchRetrieval.execute(question_pico, config)
```

当前分层里，Application 负责：

- 从 `QuestionPICO` 选择 searchable concepts
- 组装 source-neutral query plan
- 按配置顺序调用一个或多个 retrieval source method
- 聚合每个来源的 `SearchSourceResult` 和文章

Infrastructure 负责具体能力实现：

- retrieval method
- source-specific query compiler
- mesh mapping method
- textword expansion method
- PubMed / PMC HTTP clients
- XML cleaner

PubMed-specific MeSH enrichment 和 entry-term expansion 是这个 concrete source adapter 为完成 PubMed
检索所需的 provider-local technical pipeline，因此由 `pubmed_pmc` method 编排，不由 Application 编排。

调用方向保持为：

```text
interfaces/api -> application/use_cases -> application/ports -> infrastructure/methods
```

当前主调用链是：

```text
POST /modules/search-retrieval
-> interfaces/api/routes_modules.py
-> interfaces/api/dependencies.py
-> application/use_cases/run_search_retrieval.py
-> application/ports/search_retrieval.py
-> infrastructure/methods/search_retrieval/
```

## 3. 当前实现结构

当前已经实现的 retrieval source method 是：

```text
pubmed_pmc
```

命名原则：

- workflow-level provider 使用语义名，例如 `pubmed_pmc`。
- capability adapter 使用独立 method 目录，例如 `mesh_mapping_official` 和 `textword_expansion_official`。

当前目录结构：

```text
search_retrieval/
  factory.py
  official_mesh.py
  pubmed_pmc/
    method.py
    service.py
    query_builder.py
    pubmed_client.py
    pmc_client.py
    cache.py
    models.py
    xml_cleaner.py
  mesh_mapping_official/
    method.py
  textword_expansion_official/
    method.py
```

`official_mesh.py` 是两个 official capability methods 共用的 NLM client，不是 workflow method。

`pubmed_pmc` 负责：

- 对每个 concept 执行 official MeSH mapping 和 entry-term expansion
- 把 source-neutral concept plan 编译为 PubMed 字段语法
- 用编译后的 query 调 PubMed
- 解析 PMID / PMCID
- 获取 PMC full-text XML
- 清洗 XML
- 组装一个 `SearchSourceResult`

当前可选 capability methods：

```text
mesh_mapping:
  official

textword_expansion:
  official
```

它们不是 workflow module，而是 `pubmed_pmc` 内部装配的 provider-specific capabilities。API 侧通过
`interfaces/api/dependencies.py` 把完成装配的 retrieval source method 注入 `RunSearchRetrieval`。

## 4. 检索式原则

当前 application 侧的 concept selection 是 deterministic。

默认策略：

- 优先使用 `P + I`
- 同一 slot 的多个值用 `OR` 组合
- P 组与 I 组之间用 `AND` 组合
- `O` 不进入主检索式
- 只有 `I` 缺失时，`C` 才作为 fallback
- `WorkflowConstraints.study_design == "RCT"` 时，由 PubMed query builder 自动追加 trial filter
- `WorkflowConstraints.publication_year_range` 非空时，校验 `YYYY-YYYY` 并追加 PubMed
  `Date - Publication` 范围；Screening 仍基于返回 metadata 再做确定性年份校验

这样做是为了贴近真实循证医学检索习惯：主问题概念通常由 population/problem 和 intervention 驱动，outcome 过早进入主检索式会明显损害召回。

PubMed source pipeline 固定使用 official MeSH mapping：

- 每个 concept 先保留轻量 normalize 后的原始 P/I 表达，作为 `[Title/Abstract]` 自由词
- exact descriptor mapping 优先；exact 无结果时才做保守 contains mapping
- contains 候选必须与原表达 token 兼容，否则不接受
- PubMed method 对成功匹配的 concept 调官方 MeSH lookup/details 接口
- 为 concept 增加显式 `[MeSH Terms]`

随后使用 official MeSH entry terms 扩展自由词：

- PubMed method 保留 concept 的 base free-text term
- 再用 preferred heading 对应的官方 MeSH entry terms 生成最多 5 个额外 `Title/Abstract` 词
- 不依赖本地词表，也不依赖 LLM

这里的 base free text 指从 Q2PICO 的 P/I 原始表达轻量清理得到的自由词，例如
`Adults with depression` 变为 `depression`，然后作为 `"depression"[Title/Abstract]` 检索。它不依赖
MeSH，因此 MeSH 服务失败时仍然可用。

默认 RCT filter 使用 PubMed publication type 与常用 Title/Abstract trial terms，并排除 animals-only
记录。它只限制 PubMed 检索范围，不在此模块判断文章是否可提取数据；secondary report 等文章由后续
Study Screening 判断。

因此这个模块当前模拟的是：

```text
QuestionPICO
-> selected concepts
-> source-neutral query plan
-> official MeSH mapping
-> official entry-term free-text expansion
-> PubMed-specific query assembly
-> PubMed Search
```

## 5. 官方接口

当前官方 MeSH 实现使用：

```text
https://id.nlm.nih.gov/mesh/lookup/descriptor
https://id.nlm.nih.gov/mesh/lookup/details
```

MeSH capability 首版仍不做 cache。PubMed/PMC 文章获取链路使用独立的 positive-result 文件缓存，不缓存
MeSH 映射或 PubMed search 结果。

`mesh_mapping_official` 会：

1. 先做 exact descriptor lookup
2. exact 无结果时做保守 contains lookup
3. 再查 details
4. 读取 preferred heading 和 entry terms
5. 把 preferred heading 作为显式 MeSH term

`textword_expansion_official` 会：

1. 保留 concept 的 base text term
2. 复用 mapping 阶段已经取得的 official entry terms，不再重复请求 MeSH
3. 做轻量 normalize
4. 取最多 5 个去重 entry terms 作为 expanded `Title/Abstract` 候选词

每个 MeSH concept 独立执行。MeSH 网络或响应解析失败时，当前 concept 在首次尝试后 retry 一次；仍失败
则只对该 concept 降级为 base free text，并把 `mesh_enrichment_failed` 写入 warnings，不阻断 PubMed 检索。

## 6. 数据流

运行流程：

1. Application 根据 `QuestionPICO` 选 searchable concepts
2. Application 组装 source-neutral `SearchQueryPlan`
3. PubMed source method 内部调用：
   - mesh mapping method
   - textword expansion method
4. `pubmed_pmc/query_builder.py` 把 concepts、MeSH 和 constraints 编译成 PubMed query
5. retrieval method 用 PubMed ESearch 分页获取：
   - `total_hits`
   - 默认最多 10,000 条 PMID，或显式 `max_candidates_per_source`
   - `QueryTranslation`
6. 按每批最多 100 条候选，用 PubMed EFetch 拉回 title / abstract / year / doi / MeSH 等 metadata，并保留
   轻量 `SearchCitation` inventory
7. 同批用 PMC ID Converter 把 PMID 解析为 PMCID；没有 PMCID 的记录标记 `unavailable`
8. 按 rank 每批最多 5 篇调用 PMC EFetch；继续尝试后续 PMCID，直到形成最多
   `max_results_per_source` 篇有效 `CleanedArticle`
9. XML 成功清洗标记 `available`；XML 缺失标记 `unavailable`；清洗异常标记 `technical_failure`
10. 达到全文上限后仍保留剩余 citations，并将已有 PMCID 但本次未处理者标记 `not_processed`
11. Application 按来源顺序聚合 citations、计数和文章

产品 API composition root 会向 `SearchRetrievalService` 注入 `PubMedPmcFileCache`。每个 batch 先从缓存读取
未过期的 metadata、PMCID 和 XML，只把 misses 交给既有 clients；清洗后的文章使用
`raw_xml_sha256 + metadata + XML_CLEANER_VERSION` 的内容指纹缓存。当前 cleaner version 是
`pmc_xml_cleaner_v1`。缓存中的历史 `retrieval_rank` 不复用，命中后会附加本次 PubMed rank。

Provider artifacts 默认 30 天后重新获取；CleanedArticle 是内容寻址且由 cleaner version 失效。缓存读写异常
只生成 warning，不绕过原有 provider retry/failure policy。Benchmark 直接构造 backend method 时默认不注入
产品 cache。

`PMC only` 的当前语义是：

- 默认分页保留 PubMed 可返回的前 10,000 条引文，或使用显式 citation 上限
- 前部候选缺少 PMC 全文时会继续向后扫描
- 最终最多处理并返回 500 篇清洗成功的文章
- 达到全文上限不丢弃 citation inventory；剩余可继续处理的 PMCID 显式计数
- 因此 `returned_count` 可以小于 `max_results_per_source`

## 7. XML 清洗边界

XML cleaner 是 backend 内部重写实现，不依赖 benchmark helper 或旧实验代码。

当前保留内容：

- `front` 中的 abstract
- `body`
- 可识别的 `back` 部分
- section 内任意嵌套层级的 `table-wrap`
- `floats-group` 中的 tables

当前丢弃内容：

- `fig`
- `ref-list`
- `supplementary-material`
- 其他明显噪声节点

表格处理遵循仓库当前约束：

- 不做 deterministic table parsing
- raw table XML 原样保留给后续 LLM method
- 已进入 `tables` 的内容不重复拼入 section text

因此 `ArticleTable.rows` 的当前写法是：

```json
[
  {
    "_raw_xml": "...",
    "_section_path": "Results"
  }
]
```

## 8. 结果契约

`SearchSourceResult` 当前语义：

- `search_query`：PubMed query builder 编译并提交的最终 query
- `query_used`：PubMed 最终 translation 后的 query
- `source_name`：当前为 `pubmed`
- `total_hits`：PubMed 总命中数
- `returned_count`：真正清洗成功的文章数
- `retrieved_record_count`：分页保留的引文数
- `full_text_available_count`：成功形成 `CleanedArticle` 的数量
- `remaining_full_text_count`：有 PMCID 但受本次全文上限影响未处理的数量
- `truncated`：provider 命中或全文队列仍有未处理内容
- `citations`：按 rank 排列的轻量引文和全文处理状态
- `warnings`：可恢复的 concept/candidate 问题及其 stage、attempts 和可用标识

顶层 `SearchRetrievalResult` 包含：

- `source_results`：每个来源的独立执行结果
- `articles`：按来源配置顺序展平的文章
- `returned_count`：展平文章数量
- 聚合后的 citation inventory 与上述漏斗计数

当前不做跨来源去重，因此该计数不是 unique article count。

`CleanedArticle.study_id` 当前直接使用：

```text
pmc::{PMCID}
```

这表示当前结果还是 article-level 全文对象，不在这个模块里做真正 study-level 绑定。

## 9. 当前 API 参数语义

当前模块级开发 API 参数：

- `source_names`: retrieval sources 的有序列表，当前只支持并默认使用 `['pubmed']`
- `max_candidates_per_source`: 默认 `null`；显式范围 `1..10000`，表示 citation inventory 上限
- `max_results_per_source`: 默认 `500`，范围 `1..500`；表示每个来源最多处理并返回的全文文章数
- `rct_filter_enabled`: 默认 `true`；设为 `false` 时不追加 PubMed RCT filter

显式提供 `max_candidates_per_source` 时必须大于或等于 `max_results_per_source`。

`source_names` 只用于 interface 装配层选择 source adapter，不代表 application use case 通过字符串分发 method。

需要区分 Python use case 与当前 module-level HTTP API：

- `RunSearchRetrieval` 接收完整 `ModuleRunConfig`，因此 Python 调用可以通过
  `ModuleRunConfig.constraints.study_design="RCT"` 启用 trial filter。
- 当前 `SearchRetrievalRequest` 尚未完整暴露 `WorkflowConstraints`；HTTP route 只通过
  `rct_filter_enabled` 设置 `study_design`。当前 HTTP 调用不能设置 `publication_year_range` 或
  `evidence_scope`。

外部 provider 请求的默认总尝试次数为 2（首次加一次 retry）。普通非 429 的 4xx 不重试；429、5xx、
网络/超时、远端主动断开、响应截断、连接重置以及无法解析的 JSON/XML retry 一次。PubMed search、metadata、PMCID resolution 或 PMC
full-text 阶段重试耗尽时抛出 `SearchRetrievalStageError`，API 映射为 HTTP `502` 和稳定错误码
`search_retrieval_stage_retry_exhausted`。无效输入映射为 HTTP `400` 和
`search_retrieval_invalid_input`。字段类型、数值范围等 request schema 校验错误仍由 FastAPI 返回标准
HTTP `422`。

## 10. 测试

单元测试按模块放在：

```text
tests/unit/search_retrieval/
```

覆盖：

- application-side search strategy
- official mesh mapping method
- official textword expansion method
- PubMed client
- PMC client
- XML cleaner
- retrieval method/service
- application orchestration
- factory
- API limit、RCT toggle 和错误码
- provider retry、无效 JSON/XML 与 MeSH fallback

真实外部冒烟测试放在：

```text
tests/integration/search_retrieval/test_live_ncbi.py
```

默认关闭，需显式打开：

```bash
RUN_LIVE_NCBI_TESTS=1 PYTHONPATH=backend/src:. pytest tests/integration/search_retrieval/test_live_ncbi.py -q
```

## 11. 非目标

首版明确不做：

- LLM mesh mapping
- LLM free-text expansion
- 本地 synonym 词表
- cache
- cross-source citation deduplication
- benchmark 检索评测
- article -> 真正 study_id 的绑定
- deterministic 表格结构化抽取

这个模块当前的首要目标是：

- 保留独立后端的 retrieval execution 闭环
- 把 search strategy orchestration 上移到 application
- 给 mesh mapping 和 free-text expansion 预留可替换的方法边界
