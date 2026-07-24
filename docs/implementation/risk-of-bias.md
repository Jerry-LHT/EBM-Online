# Risk of Bias 实现说明

## 当前调用链

```text
POST /modules/risk-of-bias
  -> parse RiskOfBiasDomainConfig
  -> RunRiskOfBias.execute(...)
  -> bounded concurrent studies (max 4)
  -> RiskOfBiasPort.assess(study_id, article, domain_config)
  -> method_onestep_llm bounded concurrent configured domains (default max 7)
  -> successful domain judgement file cache
  -> deterministic summarize_rob1_overall(...)
  -> RiskOfBiasAssessment[] in input study order
```

`RunRiskOfBias` 拥有批量业务编排、100 项上限、严格 article 关联、全文前置校验、study 并发、whole-run
failure policy 和确定性输出顺序。Infrastructure adapter 每次只评估一个 study，并负责一个 concrete method
内部相互独立 domain calls 的有界并发。

## 产品方法

产品 factory 固定构造 `method_onestep_llm`；API 不暴露 implementation name。仓库保留
`method_calibrated_slots` 和 `method_hybrid_slots` 供 benchmark 显式选择，它们不是产品 composition
decision。

`method_onestep_llm` 的 domain criteria、prompt 文件和 `article_evidence.py` 选择规则未在本次优化中修改。
每个配置 domain 使用自己的既有 system prompt，读取同一份 article-only evidence。

产品 API composition root 向 `method_onestep_llm` 显式注入
`FileRoBDomainJudgementCache`；benchmark 默认不注入该产品 cache。

## Domain 调用

`domain_assessor.py` 为每个 domain：

1. 加载既有 domain prompt；
2. 调用 shared LLM Client，并传入 domain-specific strict JSON Schema；
3. 严格要求 `domain`、`judgement`、`support_text` 三个字段且不允许额外字段；
4. 校验 domain label、固定 judgement enum 和非空 support text；
5. 最多两次业务尝试，即首次调用加一次 retry；
6. 两次失败抛出 `RiskOfBiasDomainInvocationError`，不伪装成 `unclear_risk`。

Production adapter 默认 `domain_workers=7`。`ThreadPoolExecutor.map` 保持传入 domain 的确定性顺序；方法
在调用前把自定义 domain 配置规范为 `ROB1_DOMAINS` 的官方顺序。

每个 domain 调用前，以实际 article evidence hash、domain、`rob1_article_onestep_v1` method version、
`rob1_article_evidence_v1` evidence-builder version、prompt/schema fingerprint 以及不含 API key 的模型配置构造
cache key。命中时直接返回已经校验的 `RoB1DomainJudgement`；未命中时沿用既有首次加一次 retry，成功后才
原子写入。缓存读取损坏或写入失败只记录日志并继续正常调用，不转换 judgement。

缓存粒度是 domain，因此 5-domain 结果可以被后续 7-domain 运行复用，后者只调用缺失的两个 domains。
Overall 不写入 cache，始终按本次 key-domain 配置重新计算。当前 namespace 明确是
`rob1_article_level_v1`；未来 outcome-specific RoB 不得复用它。

## Overall 与 coverage

所有配置 domains 成功后，domain 层不再发起 LLM 调用。Domain helper
`summarize_rob1_overall()` 只读取预先配置的 key-domain judgements：high 优先于 unclear，全部 low 才输出
low。它同时生成可审计 rationale、driving domains 和 `configured_key_domains` basis。

`RiskOfBiasAssessment` 返回结构化 overall 以及 assessed/key/unassessed domain lists。GRADE 的 Risk of Bias
adapter 同时兼容新的 structured overall 和历史 string overall，并保留 domain rationale 作为 support text。

## API 映射

`routes_modules.py` 将业务错误稳定映射为：

- invalid input -> 400 `risk_of_bias_invalid_input`
- missing full text -> 400 `risk_of_bias_article_content_missing`
- missing/invalid LLM configuration -> 503 `risk_of_bias_configuration_unavailable`
- exhausted domain retry -> 502 `risk_of_bias_domain_retry_exhausted`

Domain retry 错误包含 `study_id`、`domain` 和 `attempts=2`。

## 测试

`tests/unit/risk_of_bias/` 覆盖默认七域、自定义 assessed/key domains、严格 schema、一次 retry、技术失败、
official key-domain overall mapping、输入上限和全文约束、study/domain 顺序、API 错误码、factory wiring 与
concrete-method package isolation，以及 5-to-7 domain cache reuse、失败不缓存、模型/证据变更失效。所有普通
测试使用 fake caller，不访问网络。
