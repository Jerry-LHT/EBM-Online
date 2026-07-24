# Study Screening 实现说明

稳定业务语义见 [`Study Screening 任务契约`](../contracts/study_screening.md)。

## 1. 调用链与分层

```text
POST /modules/study-screening
-> interfaces/api/routes_modules.py
-> interfaces/api/dependencies.py
-> application/use_cases/run_study_screening.py
-> criteria planner + article screener ports
-> infrastructure/methods/study_screening/
```

Application 负责业务编排、系统 criteria、metadata deterministic rules、文章并发、失败传播、顺序恢复和最终
decision aggregation。Infrastructure methods 负责证据选择、prompt、严格 JSON Schema LLM 调用和响应解析。

完整 workflow 还装配独立业务能力 `article_qualification/content_llm`。它位于 Search 后、review-specific
Screening 前，使用内容证据判断 primary RCT results report，并把成功判断缓存到
`runtime/cache/article_qualification_content_v1`。

## 2. Concrete methods

```text
study_screening/
  errors.py
  llm_support.py
  factory.py
  abstract_screening_llm/
    criteria_planner.py
    article_screener.py
    abstract_selector.py
    prompts/
  full_text_screening_llm/
    criteria_planner.py
    article_screener.py
    section_selector.py
    prompts/
  staged_synthesis_screening_llm/
    evidence.py
    method.py
    prompts/

article_qualification/
  factory.py
  content_llm/
    method.py
    evidence.py
    cache.py
    prompts/
```

Factory 根据业务 `evidence_scope` 构造匹配的 planner/screener pair：

- `full_text`：production 默认；最多选择 8 个优先 section，总 LLM article evidence 上限 60,000 字符；
- `abstract`：只使用 title、metadata 和 abstract，不回退全文；abstract 上限 20,000 字符。

完整 workflow 不使用上述二选一 factory，而使用 `build_production_staged_study_screening`：同一个 provider
配置快照同时注入 criteria planner、coarse screener、synthesis-ready screener 和 Meta-analysis。独立模块 API
继续使用原 pair，保持既有输入行为。

## 3. Criteria planning

LLM planner 只规划 review-specific P/I/C eligibility。Outcome 默认不传入；study design、primary-report status、
publication year、language 和 retraction 由系统处理，不允许 planner 重复生成。

Application 根据 `ScreeningPolicy` 追加：

- RCT randomized-allocation inclusion criterion；
- 当前 pairwise workflow 的 individually randomized parallel-group inclusion criterion；cluster、crossover、
  cluster-crossover、其他非平行设计或无法确认设计的文章不满足该必要标准；
- primary-results-report inclusion criterion。

两个 planner 都使用 strict JSON Schema，要求且只允许：

```json
{
  "inclusion_criteria": ["..."],
  "exclusion_criteria": ["..."],
  "rationale": "..."
}
```

## 4. Metadata enrichment 与 deterministic screening

Search Retrieval 的 PubMed parser 读取并传递 publication types、languages、trial registry IDs、related article
types 和 retraction/correction flags。

Application 的确定性规则只执行：

1. publication year range；
2. allowed languages；
3. retraction/retraction notice。

PubMed Publication Type、MeSH 和 trial registry indexing 不参与确定性排除，也不会进入文章类型、粗筛或
精筛 prompt。它们仍可保留在内部 metadata，但不能替代原文证据。

确定性或 LLM 排除时，聚合结果的 `exclusion_reason` 使用对应 judgment 的实际 reason。Criterion 标题仍保留
在 `criterion_judgments`，不会再把“Publication year is within ...”这类 criterion 标题误报为具体原因。

## 5. 完整 workflow 的 staged screening

Workflow 在 Search 后先做硬规则 precheck，再运行 article qualification：

- 一篇文章一次内容判断调用，首次失败加一次 retry；
- 输入仅含 title、完整 abstract、原始正文 paragraph/明确 excerpt，以及必要 raw table XML/明确 slice；
- 不确定和技术失败都继续到 review screening；技术失败不伪造成医学 exclusion；
- cache key 包含 study ID、evidence hash、prompt/schema/method version、model 与 context budget。

之后 application 调用 `prepare_criteria`，再调用 Meta synthesis planner。
Planner 仍只读取 question/PICO/criteria；其 plan 冻结后同时传给 Screening 和后续 `RunMetaAnalysis.execute`，
Meta 不会再次 planning。

`CoarseSynthesisStudyArticleScreener`：

- 输入 title、完整 abstract（若存在）和最多 4 个内容相关原始正文 paragraph；不输入 PubMed type metadata，
  不输入 table；默认最多使用共享 context budget 中的 12,000 tokens；
- 不读取 table；缺少信息或未见目标数值必须 `advance`，仅明确不匹配才 `exclude`。

`SynthesisReadyStudyArticleScreener`：

- 只处理 coarse survivors；输入最多 10 个相关正文 blocks、5 个相关 raw-table blocks；总输入从 model
  context window 扣除 prompt/schema/output/safety reserve 后确定，默认上限 48,000 tokens；
- section/table 的标题或 caption 可以为空，排序同时检查 source content；
- 正文传完整 paragraph；仅超限时形成带字符坐标的 partial `section_excerpt`；表格传完整 raw XML，超限时
  形成带坐标的 exact `table_slice`，不做表格清洗或值解析；
- 对每个 frozen target 判断 current runtime supported、needs Meta investigation、methodologically eligible but
  unsupported，或 not eligible；支持 arm-level binary/continuous 和 direct effect + CI/SE 的 GIV 形态；不提取
  最终 Meta row、不做算术。

模型只返回按位置命名的 `target_N` 语义判断，代码将其绑定到 frozen target ID，避免让模型生成工程 ID。
模型给出的 quote 必须在本次 source bundle 中逐字或经 Unicode/空白归一化匹配，之后才形成 source span。

## 6. 单阶段 LLM article judgment

两个 screeners 都为本次 criteria 动态生成 strict JSON Schema。每个 `inc_N`、`exc_N` 必须完整返回：

```json
{
  "judgment": "yes | no",
  "reason": "...",
  "evidence_spans": ["..."]
}
```

额外字段、缺失 criterion、非二元 judgment 或非字符串 span 都会使本次尝试失败。`evidence_spans` 属于可选
provenance：工程保留可在当前输入中逐字或经空白/Unicode 格式归一化匹配的 spans，无法追溯的 spans 会被丢弃，
不会改变 criterion judgment。Abstract 缺失时不调用 LLM，所有必要 inclusion criteria 为 `no`，因此最终排除。

## 7. 并发、retry 与排序

Criteria planning 与 synthesis planning 顺序执行。文章类型判断默认最多 8 篇并发；粗筛文章之间并发，完成后
只有 survivors 进入并发精筛。筛选每层使用显式 `max_workers=4` 上限，最终按原文章顺序恢复。API 和
application 均限制每次最多 500 篇。
Staged method 把 SDK retry 设为 0，stage wrapper 负责首次加一次 retry；任一文章重试耗尽会使整个任务失败，
不会产生伪 exclusion。

## 8. API

HTTP API 默认：

```json
{
  "rct_only": true,
  "report_scope": "primary_results_report",
  "outcome_eligibility_enabled": false,
  "exclude_retracted": true,
  "evidence_scope": "full_text"
}
```

年份优先使用 `publication_year_start` / `publication_year_end`。旧 `publication_year_range` 只作为过渡兼容。
Schema 类型/范围错误使用 FastAPI 422；进入 route 后的业务输入错误使用模块稳定 HTTP 400 错误码。

## 9. 已知边界

- `study_id` 仍是 article-level proxy；
- `included_studies` 仅为下游兼容别名；
- 尚未实现 secondary/companion report collation；
- abstract final screening 可能因证据不足产生更多假阴性；
- metadata 规则依赖 Search Retrieval 能获得的 PubMed fields，但不会把缺少 indexing 当作明确排除证据。
- Review eligibility 与 Meta routing 分开；没有非空 canonical `ArticleTable.raw_xml` 时，代码确定性标记
  `meta_unavailable_no_readable_table`。该文章仍进入 Study PIO 和 RoB，只是不进入当前 table-local Meta agent。
- 当前 Meta runtime 不接收 time-to-event、rate/count 或未二分 ordinal data；staged screening 会显式保留
  方法学 eligibility，而不是把它写成无结果。
