# Risk of Bias 任务契约

本文定义对已纳入 primary RCT article 进行 article-only Cochrane RoB 1 评估的稳定业务契约。当前实现见
[`Risk of Bias 实现说明`](../implementation/risk-of-bias.md)。

## 任务定义与边界

任务单位是一项 included RCT study，当前一个 study 严格对应一篇 `CleanedArticle`。本模块只使用文章
sections 和 tables，不接收 protocol、registry、Study PIO 或 Meta-analysis result，也不生成 GRADE
risk-of-bias downgrade judgement。

RoB 1 中盲法和不完整结局数据可随 outcome/timepoint 变化；当前产品不增加 outcome-level 输入，而采用
已经对齐的 article-level 保守聚合规则。现有 domain 医学判断标准和 prompt 保持不变。

## 输入

- `included_studies: list[str]`：需要评估的 study IDs，其顺序定义输出顺序。
- `articles: list[CleanedArticle]`：与 study IDs 严格一一对应的文章。
- `domain_config.assessed_domains: list[str]`：本次实际评估的 RoB 1 domains。
- `domain_config.overall_key_domains: list[str]`：参与 overall summary 的预先指定 key domains，必须是
  `assessed_domains` 的非空子集。

未传 `domain_config` 时，两组 domain 均默认：

1. `random_sequence_generation`
2. `allocation_concealment`
3. `blinding_participants_personnel`
4. `blinding_outcome_assessment`
5. `incomplete_outcome_data`
6. `selective_reporting`
7. `other_bias`

调用方仍可通过 `domain_config` 选择 RoB 1 domain 子集，并单独指定参与 overall summary 的 key domains。

### 输入不变量

- 每次最多接收 500 个 studies 和 500 篇 articles。
- study ID 不得为空或重复。
- article 不得缺失、重复或属于未纳入 study。
- 每篇 included article 必须至少有一个非空全文 section；tables-only 不满足全文要求。
- domain 列表不得为空、重复或包含非 RoB 1 domain。

任一输入不变量不满足时，整个任务失败；不静默跳过或返回部分结果。

## Domain 输出与失败语义

每个配置 domain 输出 `RoB1DomainJudgement`：

- `domain`
- `judgement`: `low_risk | high_risk | unclear_risk`
- `rationale`: 非空文章证据或明确的未报告说明
- `source_spans`: 当前固定为空，精确 evidence span 尚未实现

每个 domain 独立拥有最多两次业务尝试：首次调用加一次 retry。技术或结构失败不得转换成
`unclear_risk`；两次都失败使整个批次失败。`unclear_risk` 只表示文章证据不足或风险确实不确定。

产品 API 可按 article evidence、domain、method/prompt/schema version 和非敏感模型配置复用已经成功且通过
结构校验的 domain judgement。`low_risk`、`high_risk`、`unclear_risk` 都是可缓存的业务结果；超时、网络
错误、解析失败和 retry exhausted 不缓存。缓存只复用 domain，overall 始终按本次
`overall_key_domains` 重新确定性生成。

## Overall summary

Overall 不调用 LLM，按照 Cochrane RoB 1 key-domain summary 规则确定性生成：

- 任一 key domain 为 `high_risk` -> overall `high_risk`；
- 否则任一 key domain 为 `unclear_risk` -> overall `unclear_risk`；
- 否则所有 key domains 均为 `low_risk` -> overall `low_risk`。

输出为结构化 `RoB1OverallJudgement`，包含 `judgement`、`rationale`、`driving_domains` 和固定
`basis=\"configured_key_domains\"`。这是 article-level RoB 1 summary，而非 outcome-specific assessment：默认
配置以完整七域为 key domains；自定义配置时，overall 仅代表所配置的 key domains。

每个 `RiskOfBiasAssessment` 同时返回 `assessed_domains`、`overall_key_domains` 和
`unassessed_domains`，使下游能够审计 assessment coverage。

## 批量并发与顺序

- application 最多并发处理 4 个 studies；
- production method 最多并发处理一个 study 的 7 个默认 domains；
- shared LLM Client 继续施加全局并发上限；
- domain 输出遵循固定 RoB 1 顺序，study 输出遵循 `included_studies` 顺序；
- 任一 study/domain 失败使整个批次失败，不返回部分成功。

## API 错误码

- `risk_of_bias_invalid_input` (400)
- `risk_of_bias_article_content_missing` (400)
- `risk_of_bias_configuration_unavailable` (503)
- `risk_of_bias_domain_retry_exhausted` (502)
