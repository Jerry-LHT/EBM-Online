# Article Qualification 任务契约

Article Qualification 是完整 workflow 中位于全文获取之后、review-specific Study Screening 之前的可缓存
文章类型判断。它只回答当前 report 是否为 primary randomized trial results report，不判断该文章是否符合某个
review PICO，也不判断最终能否进入 Meta-analysis。

## 输入

- 一个已有 PMC full-text XML 的 `CleanedArticle`；
- title、原始正文 sections 和 canonical raw table XML；
- model context window 与本阶段 input budget。

PubMed Publication Type、MeSH、trial registration indexing 和 RCT 标签不进入 LLM evidence。provider metadata
缺失或错误不能替代文章内容判断。

证据按统一 context budget 选择：优先完整 abstract 和相关 XML paragraph；只有单个来源超限时才产生带字符
坐标、明确标记 partial 的 `section_excerpt`。小表传完整 raw XML；大表只传 exact `table_slice`，不清洗、
解析或重排表格。Partial coverage 不能用于证明某项内容不存在。

## 输出

每篇文章输出 `ArticleQualificationAssessment`：

- `decision`: `pass | exclude | advance_uncertain | technical_failure`；
- `report_role`: primary results、protocol、secondary report、review/meta-analysis、other 或 unclear；
- `randomization_status`、`trial_design`、`results_report_status`；
- `has_quantitative_results`；
- reason、可追溯 source spans、实际 evidence coverage 和可选 failure code。

只有文章内容正面建立 protocol/review/非随机等不合格类型时才 `exclude`。不确定判断和技术失败都进入后续
Review Screening，不得伪造成医学排除。

## 执行与缓存

- 每篇文章首次调用失败后 retry 一次；没有隐藏 SDK retry；
- 多篇文章最多 8 个并发，输出恢复输入顺序；
- 成功判断可跨 workflow 缓存；key 包含 study ID、evidence hash、evidence/prompt/schema/method version、model、
  API mode 和 context budget；
- cache 读写失败按 cache miss/非阻断写失败处理；`technical_failure` 不写入成功结果缓存。

