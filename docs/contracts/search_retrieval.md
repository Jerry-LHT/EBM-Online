# Search Retrieval 任务契约

本文定义 Search Retrieval 的稳定业务契约。完整 workflow 顺序见
[`workflow_v3.md`](../workflow_v3.md)；当前 provider、query assembly 和全文清洗实现见
[`docs/implementation/search-retrieval.md`](../implementation/search-retrieval.md)。

## 任务目标与粒度

Search Retrieval 根据一个 `QuestionPICO` 形成可执行检索，并返回可供后续 EBM 模块阅读的文章级证据对象。
调用单位是一个 question-level retrieval run（问题级检索运行）。

检索结果的业务粒度是 article/report，不是真正完成多报告合并后的 study。

## 输入契约

任务至少需要：

- `question_pico`：上游 Q2PICO 产生的结构化问题。
- ordered retrieval sources：至少一个按执行顺序装配的检索来源 adapter。
- `max_candidates_per_source`：可选的引文清单上限；默认 `null`，表示分页保留 provider 可返回的清单，当前
  服务安全上限为每来源 `10,000` 条。
- `max_results_per_source`：每个来源最多获取、清洗并交给内容筛选的全文数；默认和上限均为 `500`。
- workflow constraints：可选的检索约束，例如 study design 和 `YYYY-YYYY` 发表年份范围。
- retrieval options：可选的受控概念映射或 free-text expansion 能力开关。

显式提供 `max_candidates_per_source` 时，它必须是正整数且大于或等于 `max_results_per_source`。

输入必须至少包含一个可用于检索的 population、intervention 或 fallback comparator 概念。Outcome 不保证进入
主检索式，`O_expanded` 也不得被默认视为检索词。

同一 PICO slot 内的多个概念是同义或替代表达，使用 `OR` 组合；不同检索概念组使用 `AND` 组合。当前默认
选择 P 和 I：P 组内 `OR`、I 组内 `OR`，两组之间 `AND`。只有 I 缺失时才用 C 组作为 fallback，O 不进入
主检索式。

HTTP API 默认启用 PubMed RCT filter，并允许通过 `rct_filter_enabled=false` 关闭。这里的职责仅是通过
PubMed 检索 RCT reports（随机对照试验报告）；不在检索阶段判断文章是否为 primary report、是否一定含有
可提取原始数据，也不排除二次报告。这类 eligibility 判断属于 Study Screening。

## 输出契约

任务返回 `SearchRetrievalResult`：

- `source_results`：按配置顺序排列的 `SearchSourceResult`。
- `returned_count`：所有来源成功形成并展平到顶层的 `CleanedArticle` 数量。
- `articles`：先按来源配置顺序、再按来源内 retrieval rank 排列的文章列表。
- `citations`：分页保留的轻量 PubMed 引文清单，不包含全文；每条记录保留 retrieval rank 和全文处理状态。
- `retrieved_record_count`、`full_text_available_count`、`remaining_full_text_count`、`truncated`：分别表示
  已保留引文数、已形成全文文章数、已有 PMCID 但因本次全文上限尚未处理的数量，以及 provider 命中或全文
  队列是否仍有未处理内容。

每个 `SearchSourceResult` 表达一个来源的执行结果：

- `source_name`：数据来源的稳定标识，例如 `pubmed`。
- `search_query`：该来源 adapter 编译并提交的来源专用检索式。
- `query_used`：数据源实际采用或 translation 后的检索式。
- `total_hits`：该来源报告的总命中数。
- `returned_count`：该来源成功形成的文章数。
- `retrieved_record_count`、`full_text_available_count`、`remaining_full_text_count`、`truncated`。
- `citations`：每条含 `pmid`、rank、title、abstract、PMCID、year、DOI 和
  `available | unavailable | not_processed | technical_failure` 全文状态。
- `articles`：该来源返回的文章列表。
- `warnings`：可恢复的候选级或概念级问题，例如 MeSH enrichment 失败、缺少 PMCID 或全文清洗失败。

产品 API 可以复用 provider-local positive-result cache。缓存命中只跳过 PubMed metadata、PMID-to-PMCID、
PMC XML 获取和相同 cleaner version 的文章清洗；PubMed search、query translation、retrieval rank 和本次
warning 语义仍属于当前 retrieval run，不从历史运行复用。缓存读写失败不得使 retrieval 失败：读取失败按
cache miss 处理，写入失败保留正常结果并写入 `article_cache_*_failed` warning。

顶层和每个来源的 `returned_count` 都必须等于对应 `articles` 的长度，但不保证等于
`max_results_per_source`。adapter 先分页保留引文清单并解析 metadata/PMCID，再按 PubMed rank 获取全文，
直到形成 `max_results_per_source` 篇文章或有 PMCID 的候选耗尽。达到全文上限后不丢弃引文：尚未获取的候选
标记为 `not_processed`，可由后续运行继续处理。记录可能因缺少可访问全文、metadata、标识映射或有效正文而
无法形成 `CleanedArticle`；被跳过的可恢复问题应记录在 `warnings` 中。

当前顶层聚合不执行跨来源去重。同一 article 被多个来源检出时可能出现多次；真正的 citation deduplication
（文献去重）和多 report 到 study 的归并需要单独的 application 规则和 provenance contract。

## CleanedArticle 边界

每个 `CleanedArticle` 至少表达：

- 当前 article/report 的稳定 workflow id；
- title 和可获得的 PMID、PMCID、DOI、publication year 等 metadata；
- 清洗后的正文 sections；
- 原始证据形态的 tables；
- 数据源和 retrieval rank 等 provenance。

当前 `study_id` 可以是 article-level proxy。Search Retrieval 不负责判断多篇文章是否属于同一研究。

表格应保留为后续 evidence-reading method 可读取的原始来源。此模块不把确定性表格解析作为 study-result
extraction 的替代品。

## 上下游责任

- Q2PICO 负责表达完整问题语义；Search Retrieval 负责选择适合高召回检索的概念。
- Search Retrieval 负责检索、标识解析、全文获取和文章清洗，不负责研究纳排。
- Application 负责选择和编排检索来源；每个 source adapter 负责把 source-neutral concept plan 编译成
  自己的数据源语法。
- Study Screening 必须基于返回的文章证据执行 eligibility judgment，不能把 retrieval rank 当作纳入结论。
- Benchmark 特有的候选过滤、gold 对齐或评分不得改变该任务的返回语义。

## 失败与非目标

没有任何可检索概念、没有装配任何来源，或来源无法编译非空 query，都是无效任务输入。当前任一外部
来源失败会使整个 retrieval run 失败，不应伪造成该来源的空证据。

PubMed、PMC 和 MeSH 的外部请求默认只重试一次，即首次尝试加一次 retry。超时、网络错误、429、5xx 和
无法解析的 JSON/XML 可以重试；网络错误包括远端主动断开、响应截断和连接重置。普通非 429 的 4xx 不重试。PubMed/PMC 必需阶段在重试预算耗尽后使任务
失败；MeSH enrichment 在对应 concept 的重试预算耗尽后只降级该 concept，继续保留其 Title/Abstract
自由词并写入 warning。其他 concept 的 MeSH 结果不受影响。

API 错误语义：

- 已进入 route 的无效业务输入返回 HTTP `400`，错误码 `search_retrieval_invalid_input`；请求字段类型、范围等
  schema 校验失败仍使用 FastAPI 标准 HTTP `422`；
- 必需 provider 阶段重试耗尽返回 HTTP `502`，错误码
  `search_retrieval_stage_retry_exhausted`，并携带 `stage` 和 `attempts`。

本任务不负责：

- 真正的 study-level report collation；
- 研究纳排和风险偏倚判断；
- study-result 数值抽取；
- 根据 benchmark gold 改写检索式或补齐文章。
