# Study PICO 实现说明

稳定业务语义见 [`Study PICO Extraction 任务契约`](../contracts/study_pio.md)。

## 1. 分层与调用链

```text
POST /modules/study-pio-extraction
-> interfaces/api/routes_modules.py
-> interfaces/api/dependencies.py
-> application/use_cases/run_study_pio.py
-> StudyPIOExtractionPort
-> extraction_study_pico_slotwise_llm
-> StudyPIOCharacteristics
```

正式 API 不暴露内部 method name。Composition root 通过 `build_production_study_pio()` 注入唯一批准的
`extraction_study_pico_slotwise_llm` adapter。

## 2. Application 编排

`RunStudyPIO`：

- 限制 `included_studies` 和 `articles` 各最多 500 项；
- 校验 study IDs 非空、唯一且两组 ID 完全对应；
- 拒绝缺失、额外或同一 study 的多篇 articles；
- 在线程池启动前检查每篇 included article 至少有一个非空全文 section；
- 使用最多 4 个 workers 并发不同 studies；
- 按输入 study 顺序恢复输出；
- 任一 future 失败则整个请求失败，不提供 partial success。

全文前置校验属于 application 业务编排；concrete LLM method 不负责静默跳过输入 study。

## 3. Concrete method

```text
infrastructure/methods/study_pio/
  errors.py
  factory.py
  extraction_study_pico_slotwise_llm/
    method.py
    pipeline.py
    materials.py
    parsing.py
    schemas.py
    prompts/
      population.txt
      intervention_comparator.txt
      outcome.txt
```

`pipeline.py` 对一篇 study article 顺序执行 Population、Intervention/Comparator 和 Outcome 三个 focused
stages，再组装一个 `StudyPIOCharacteristics`。现有 P/I/C/O 字段和 Outcome 提取语义保持不变。

## 4. Context 选择

`materials.py` 为每个 stage 独立选择文章材料：最多 18 个 section snippets、section 总计 36,000 字符、
最多 5 个 table snippets，并按 stage 关键词和 question PICO 相关性排序。Question PICO 只用于定位相关性，
不能作为 study evidence。表格只作为来源文本传给 LLM，不做确定性数值提取。

## 5. 严格结构与 retry

三个 stages 分别向共享 `call_llm_json()` 传入：

- `study_pio_population`；
- `study_pio_intervention_comparator`；
- `study_pio_outcome`。

每个 schema 要求 required fields、正确数组/item 类型和 `additionalProperties=false`。Provider strict schema
之外，`parsing.py` 再验证 required fields、额外字段、空 label/description 以及 `timepoints`/`warnings` 必须
为字符串数组。非法结构不再静默丢弃或转为空值。

每个 stage 最多尝试 2 次，即首次失败后 retry 一次。结构解析和 provider failure 使用同一 retry budget。
Retry 耗尽抛出带 `stage`、`study_id` 和 `attempts` 的 `StudyPIOInvocationError`。配置读取错误统一映射为
`StudyPIOConfigurationError`。

## 6. API errors

接口层将普通输入错误、全文缺失、配置不可用和 stage retry exhausted 分别映射为稳定的 400、400、503、
502 响应。Provider 原始敏感响应不直接暴露给 API。

## 7. GRADE indirectness 交接

Study PIO 本身不读取 Meta-analysis 产物。`RunGrade` 使用：

1. `question_pico` 构造宽泛 `review_scope_pico`；
2. 当前 `AnalysisSetting` 构造主要 `synthesis_target_pico`；
3. 当前 estimate 的 `included_data_row_ids` 对应 `MetaAnalysisDataRow` 确定每篇 study 实际贡献的 I/C/O/timepoint；
4. Study PIO 补充 population、干预实施、comparator context 和 outcome measurement 细节。

Application 生成 typed `GRADEIndirectnessStudyEvidence[]`。Label 只做大小写与空白归一化后的唯一精确匹配；
无法唯一匹配时保留 candidates 和明确 mapping status，不使用工程关键词猜测临床等价关系。Indirectness
result-blind classifier 消费其中的 target、Study PIO 与 row mapping；效应和权重只在分类冻结后的 evidence-body
阶段使用。

## 8. 验证

普通 unit tests 使用 fake caller，覆盖 strict schemas、parser failures、独立一次 retry、全文校验、数量上限、
并发顺序、API error mapping 和 GRADE handoff。真实 LLM smoke 仅在显式 opt-in 时运行：

```bash
RUN_LIVE_LLM_TESTS=1 PYTHONPATH=backend/src:. \
  pytest -q tests/integration/study_pio/test_live_slotwise_llm.py
```

Benchmark 继续通过 module-specific adapter 调用 `RunStudyPIO`；backend runtime 不依赖 benchmark code。
