# Article Qualification 实现说明

当前目录：

```text
backend/src/ebm_backend/online_pipeline/
  domain/article_qualification.py
  application/ports/article_qualification.py
  application/use_cases/run_article_qualification.py
  infrastructure/methods/article_qualification/
    factory.py
    errors.py
    content_llm/
      method.py
      evidence.py
      cache.py
      prompts/
```

`RunArticleQualification` 在 application 层按文章并发调用已注入的 qualifier，捕获文章级技术失败并输出
`technical_failure`，使该文章继续进入 Study Screening。具体 content LLM adapter 在 infrastructure 内完成
evidence packing、严格 JSON Schema、一次 retry 和 versioned cache。

Production composition 位于 `interfaces/api/dependencies.py`，缓存目录为
`runtime/cache/article_qualification_content_v1`，可审计调试产物位于
`runtime/debug/article_qualification_content_v1`。调试产物保存 evidence coverage、精确来源文本及 hash、模型输出、
attempt 状态、耗时和最终状态；不保存 API key。缓存命中不会覆盖首次真实调用的调试记录。本阶段不调用其他
use case，不读取 benchmark，也不保存 review-specific eligibility。

证据包使用 dependency-free conservative token estimate，并从配置的 `context_window_tokens` 中为 prompt、schema、
输出和 provider headroom 预留空间。正文和表格共享预算；存在表格时预留部分预算，避免正文先耗尽上下文。
表格只以完整 `raw_xml` 或原字符串 exact slice 进入 prompt。
