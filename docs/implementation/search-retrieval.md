# Search Retrieval 实现说明

本文档记录 `search_retrieval` 模块当前的真实后端实现边界。

当前实现目标不是 benchmark 评测，而是独立后端里可复用的真实 EBM 检索与全文清洗能力。

## 1. 模块职责

`search_retrieval` 负责完成这条业务链路：

```text
QuestionPICO
-> search strategy orchestration
-> PubMed 检索
-> PMID -> PMCID 解析
-> PMC full-text XML 获取
-> XML 清洗
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
- 决定是否调用 mesh mapping method
- 决定是否调用 textword expansion method
- 组装最终 query plan
- 调 retrieval method 执行检索、下载和清洗

Infrastructure 负责具体能力实现：

- retrieval method
- mesh mapping method
- textword expansion method
- PubMed / PMC HTTP clients
- XML cleaner

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

当前 retrieval execution method 是：

```text
pubmed_pmc
```

命名原则：

- workflow-level provider 使用语义名，例如 `pubmed_pmc`。
- capability adapter 使用语义名，例如 `mesh_mapping/official` 和 `textword_expansion/official`。

它只负责：

- 用收到的 `search_query` 调 PubMed
- 解析 PMID / PMCID
- 获取 PMC full-text XML
- 清洗 XML
- 组装 `SearchRetrievalResult`

当前可选 capability methods：

```text
mesh_mapping:
  official

textword_expansion:
  official
```

它们不是 workflow module，而是 `search_retrieval` 在 application 编排时可调用的 infrastructure capabilities。API 侧通过 `interfaces/api/dependencies.py` 把这些 concrete method 装配进 `RunSearchRetrieval`。

## 4. 检索式原则

当前 application 侧的 concept selection 是 deterministic。

默认策略：

- 优先使用 `P + I`
- `O` 不进入主检索式
- 只有 `I` 缺失时，`C` 才作为 fallback
- `WorkflowConstraints.study_design == "RCT"` 时自动追加 trial filter

这样做是为了贴近真实循证医学检索习惯：主问题概念通常由 population/problem 和 intervention 驱动，outcome 过早进入主检索式会明显损害召回。

如果启用 `mesh_method_name="official"`：

- application 会对已选 concept 调官方 MeSH lookup/details 接口
- 为 concept 增加显式 `[MeSH Terms]`

如果启用 `textword_method_name="official"`：

- application 会对 concept 保留 base free-text term
- 再用官方 MeSH entry terms 生成额外 `Title/Abstract` 词
- 不依赖本地词表，也不依赖 LLM

因此这个模块当前模拟的是：

```text
QuestionPICO
-> selected concepts
-> optional official MeSH mapping
-> optional official entry-term free-text expansion
-> deterministic query assembly
-> PubMed Search
```

## 5. 官方接口

当前官方 MeSH 实现使用：

```text
https://id.nlm.nih.gov/mesh/lookup/descriptor
https://id.nlm.nih.gov/mesh/lookup/details
```

首版不做 cache。

`mesh_mapping/official` 会：

1. 先查 descriptor
2. 再查 details
3. 读取 preferred heading 和 entry terms
4. 把 preferred heading 作为显式 MeSH term

`textword_expansion/official` 会：

1. 保留 concept 的 base text term
2. 读取或复用 official entry terms
3. 做轻量 normalize
4. 把 entry terms 作为 expanded `Title/Abstract` 候选词

## 6. 数据流

运行流程：

1. Application 根据 `QuestionPICO` 选 searchable concepts
2. 可选调用：
   - mesh mapping method
   - textword expansion method
3. Application 组装 `search_query`
4. retrieval method 用 PubMed ESearch 获取：
   - `total_hits`
   - 前 `max_results` 条 PMID
   - `QueryTranslation`
5. 用 PubMed EFetch 拉回 title / year / doi / MeSH 等 metadata
6. 用 PMC ID Converter 把 PMID 批量解析为 PMCID
7. 仅保留有 PMCID 的文章
8. 用 PMC EFetch 拉回 full-text XML
9. 对每篇 XML 做清洗并映射为 `CleanedArticle`

`PMC only` 的当前语义是：

- 只处理 PubMed 前 `max_results` 条命中
- 不向后补齐
- 因此 `returned_count` 可以小于 `max_results`

## 7. XML 清洗边界

XML cleaner 是 backend 内部重写实现，不依赖 benchmark helper 或旧实验代码。

当前保留内容：

- `front` 中的 abstract
- `body`
- 可识别的 `back` 部分
- `floats-group` 中的 tables

当前丢弃内容：

- `fig`
- `ref-list`
- `supplementary-material`
- 其他明显噪声节点

表格处理遵循仓库当前约束：

- 不做 deterministic table parsing
- raw table XML 原样保留给后续 LLM method

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

`SearchRetrievalResult` 当前语义：

- `search_query`：application 组装的最终 query
- `query_used`：PubMed 最终 translation 后的 query
- `database`：固定为 `pubmed`
- `total_hits`：PubMed 总命中数
- `returned_count`：真正清洗成功的文章数

`CleanedArticle.study_id` 当前直接使用：

```text
pmc::{PMCID}
```

这表示当前结果还是 article-level 全文对象，不在这个模块里做真正 study-level 绑定。

## 9. 当前 API 参数语义

当前模块级开发 API 仍保留以下方法选择参数：

- `method_name`: retrieval execution method，当前固定正式实现为 `pubmed_pmc`
- `mesh_method_name`: 可选 MeSH mapping capability，当前官方实现名为 `official`
- `textword_method_name`: 可选 free-text expansion capability，当前官方实现名为 `official`

这些参数当前只用于 interface 装配层选择 concrete adapter，不代表 application use case 通过通用 resolver 按字符串分发业务。

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
- benchmark 检索评测
- article -> 真正 study_id 的绑定
- deterministic 表格结构化抽取

这个模块当前的首要目标是：

- 保留独立后端的 retrieval execution 闭环
- 把 search strategy orchestration 上移到 application
- 给 mesh mapping 和 free-text expansion 预留可替换的方法边界
