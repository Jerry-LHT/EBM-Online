# Study PICO Extraction 任务契约

本文定义从纳入研究文章提取 study-level PICO characteristics 的稳定业务契约。当前正式实现见
[`Study PICO 实现说明`](../implementation/study-pio.md)。

## 任务目标与粒度

任务单位是一个 included study。当前业务约定一个 study 对应一篇 primary RCT article。Concrete method
每次接收一个 `study_id` 和一篇对应的 `CleanedArticle`，返回一个 `StudyPIOCharacteristics`。Application
负责批量关联、输入校验、受控并发和稳定排序。

## 输入契约

- `question_pico`：review-level PICO，只用于限定相关性，不是 study evidence；
- `included_studies`：最多 500 个唯一、非空 study IDs；
- `articles`：最多 500 篇清洗文章，其 study ID 集合必须与 `included_studies` 完全对应；
- 每个 study 只接受一篇 `CleanedArticle`，且 `article.study_id == study_id`；
- 每篇 article 必须至少包含一个非空 `xml_content.sections[].text`。

只有 title、metadata 或 tables 不构成本模块可用的全文输入。任一 included study 缺少可用全文时，整个请求
失败且不调用 LLM；本模块不会静默删除已经由 Study Screening 纳入的 study。

## 输出契约

每个 study 返回一个 `StudyPIOCharacteristics`：

- `study_id`：输入 study ID；
- `population`：实际纳入人群、eligibility、setting、样本量和基线特征；
- `interventions`：study 实际实施的相关干预 arms；
- `comparators`：study 实际使用的 control、placebo、usual care 或其他 comparison arms；
- `outcomes`：study 实际测量或报告的相关 outcome domain、measurement 和 timepoints；
- `notes`：方法标识及有限的 extraction warnings。

输出只能来自 article evidence。`question_pico` 不得用于补齐文章没有支持的人群、arm、outcome、instrument
或 timepoint。本任务不提取 treatment-effect 数值，也不改变当前 Outcome 相关性规则。

当前 `source_spans` 字段为兼容 domain 契约保留，但正式方法尚未实现 evidence span 提取，返回空列表。

## 执行与失败语义

`RunStudyPIO` 对不同 studies 使用最多 4 个 workers，并按 `included_studies` 恢复确定性输出顺序。单个 study
内顺序执行 `population`、`intervention_comparator` 和 `outcome` 三个 stages。

每个 stage 使用 strict JSON Schema 和本地结构校验；首次失败后只 retry 一次。三个 stages 各自拥有独立
retry budget，任一 stage 两次均失败或任一 study extraction 失败时，整个请求失败，不返回 partial success
或伪造 fallback。

API 稳定错误：

- HTTP 400 `study_pio_invalid_input`：数量、ID 关联或其他输入错误；
- HTTP 400 `study_pio_article_content_missing`：一个或多个 included studies 缺少可用全文；
- HTTP 503 `study_pio_configuration_unavailable`：LLM 配置不可用；
- HTTP 502 `study_pio_stage_retry_exhausted`：指定 study 的指定 stage 两次均失败。

Stage failure 响应携带 `stage`、`study_id` 和 `attempts=2`。Provider、JSON、schema 或本地结构解析失败均
计入同一 stage retry budget。共享 LLM Client 的 transport retry 不计入这里的业务 stage attempts。

## 下游边界

Study PIO 不读取 Meta-analysis setting，也不生成 GRADE target。GRADE application 使用 review PICO 作为
宽泛 scope、使用当前 `AnalysisSetting` 作为 row-specific synthesis target，并结合 `StudyResultRow` 将本模块
输出投影为当前 evidence body 的 P/I/C/O/timepoint。

## 当前正式方法

当前只接入 `extraction_study_pico_slotwise_llm`。历史 `method_rule` 不属于维护源码；本地快照仅可放在被
Git 忽略的 `archive/` 中，正式 API 和 benchmark method loader 均不依赖它。
