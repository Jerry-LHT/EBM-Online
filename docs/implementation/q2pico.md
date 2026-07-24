# Q2PICO 实现说明

本文档记录 Question -> PICO 功能从实验代码合入后端的实现边界。

稳定业务语义见 [`Q2PICO 任务契约`](../contracts/q2pico.md)。

## 来源

实验来源：

```text
/Users/jerry/Documents/code/medical/EBM-Online/experiments/q2pico-exp
```

后端没有原样合入实验工程。以下内容没有进入正式后端：

- dataset prepare CLI
- benchmark evaluation CLI
- run artifact 写盘逻辑
- 并发 runner
- judge/evaluation 代码

正式后端只提炼了实验中稳定的 Q2PICO 任务实现：

- definition-guided split-slot prompt design
- keyed JSON output contract
- slot payload validation and normalization
- bounded parallel slot extraction
- optional outcome expansion for protocol-style planning
- P/I/C/O/O_expanded aggregation into `QuestionPICO`

## 后端位置

当前实现：

```text
backend/src/ebm_backend/online_pipeline/infrastructure/methods/q2pico/
  factory.py
  split_slot_llm/
    method.py
    extractor.py
    prompts/
      question_slot_outcome_planning_v1.txt
      question_slot_split_v1_p_only.txt
      question_slot_split_v1_i_only.txt
      question_slot_split_v1_c_only.txt
      question_slot_split_v1_o_only.txt
```

当前主调用链：

```text
POST /modules/q2pico
-> interfaces/api/routes_modules.py
-> interfaces/api/dependencies.py
-> application/use_cases/run_q2pico.py
-> application/ports/q2pico.py
-> infrastructure/methods/q2pico/
```

## 业务边界

Application 只看到：

```python
RunQ2PICO.execute(question_text=..., expand_outcomes=...) -> QuestionPICO
```

Q2PICO 当前定义为一个业务任务：把原始临床问题转换为结构化 PICO，并可选补充 protocol-oriented
outcome candidates。application 通过字段 `q2pico: Q2PICOPort` 依赖这项完整业务能力，不使用含糊的
`method` 命名，也不因为 infrastructure 内部有多次 LLM 调用就拆成多个 use case 或 port。

Infrastructure method 内部负责：

- 对 P/I/C/O 四个 slot 分别构造 prompt。
- 并发调用 LLM，默认最多 4 个并发 slot 请求。
- 每个 P/I/C/O slot 失败时只重试该 slot 一次；成功的 slot 不会因其他 slot 失败而重跑。
- 默认只抽取问题中显式表达的 `O` outcome domain 或 endpoint。
- 在 `expand_outcomes=True` 时追加一次 outcome planning prompt，生成 `O_expanded`；该 stage 也只重试一次。
- 对每个 slot 请求 provider 的 strict JSON Schema，并在本地再次校验 keyed JSON。
- 去除空字符串和重复项。
- 组装为 domain `QuestionPICO`。

任一必需 stage 在第二次尝试后仍失败时，整个任务失败；不返回部分 PICO。基础 slot 的空列表仍是有效
业务输出，表示问题未表达该维度。

split-slot 是 method 内部实现细节，不暴露给 API 或 application use case。

`split_slot_llm/method.py` 只负责构造该 concrete method 并暴露 `run()`。API 侧通过
`interfaces/api/dependencies.py` 中的 factory 装配 adapter。它不调用 application use case，也不承担业务编排。
Q2PICO benchmark 通过 benchmark-side adapter 调用同一个 factory，不经过通用 backend registry。调用方向应保持为：

```text
interfaces/api -> application/use_cases -> application/ports -> infrastructure/methods
```

## Prompt 设计

生产 prompt 不携带实验字段：

- 不传 `question_id`
- 不使用 few-shot examples
- 不要求模型生成任何 trace 或 id

P/I/C/O scope 参考 Cochrane Handbook 中对 review PICO 的定义，但 prompt 只保留简洁工程定义：

- `P`: population, participants, patients, health problem, condition, disease, setting, or subgroup
- `I`: intervention, treatment, exposure, prevention, diagnostic approach, management strategy, or active option
- `C`: comparison intervention, control, placebo, usual care, no treatment, reference option, or alternative option
- `O`: only explicitly stated outcome endpoints, effects, benefits, harms, events, measurement targets, or results

每个 slot 只允许使用 clinical question 中明确出现或可直接推断的信息，不补全未出现的研究细节。

当前单一 Q2PICO 任务的输出采用两层 outcome 语义：

- `O`: question text 中显式写出的 outcome domain 或 endpoint
- `O_expanded`: 可选的 protocol-style patient-important core outcomes，由单独的 LLM prompt 规划生成

显式 O 抽取和可选 outcome planning 是这个 use case 内部的两个处理阶段，不是两个独立业务任务。
这是为了区分输入原文支持的信息与方法生成的候选规划信息。Cochrane Handbook 要求在 protocol 阶段
预先定义 critical 和 important outcomes，但没有规定软件必须采用“先抽取、再生成”的两任务流水线。

`O_expanded` 的当前设计目标不是拟合 benchmark 的任意标注细节，而是更接近真实 guideline / protocol / GRADE 场景中的 core outcomes 风格：

- 优先 broad patient-important outcomes
- 优先 benefit 与 harm 的平衡覆盖
- 控制数量，避免无界发散
- 避免药物机制级、过细、过专门的 adverse-event 列表，除非问题本身就在问该具体风险

`O_expanded` 仍只是候选 outcome domains，不是完整的 protocol outcome specification。完整规范还需要
重要性、获益/伤害属性、测量工具或选择规则、metric、aggregation method 和 time point 等信息。

## 与检索的关系

Q2PICO 输出完整 P/I/C/O 结构，但它不是检索式生成器。循证医学检索通常追求高敏感性，后续 Search Retrieval method 应基于检索目标选择少数 searchable concepts，例如优先使用 population/problem 与 intervention，再视场景决定是否加入 comparator 或 outcome。

因此：

- Q2PICO 负责结构化理解问题。
- Search Retrieval 负责选择哪些 PICO 概念进入查询。
- 不应把 P/I/C/O 四项机械拼接为检索式。

## 调用方式

当前模块级 API 只接收业务输入，不暴露 concrete adapter 名称：

```json
{
  "question_text": "Should adults with depression receive SSRIs versus placebo for remission?",
  "expand_outcomes": true
}
```

`expand_outcomes` 默认是 `true`；调用方只有在明确只需要 source-faithful `O` 时才传 `false`。

Q2PICO 当前只有一套正式后端实现。`interfaces/api/dependencies.py` 直接调用
`build_production_q2pico()`，composition root 不传递 `default` 或任何内部 method name。
infrastructure 仍可自由演进具体 prompt、并发和 provider 实现。

## LLM 配置

默认从仓库根目录读取：

```text
llm.local.json
```

配置由现有 `infrastructure/llm/config.py` 加载。不要把 API key 写入代码、文档或 benchmark artifact。

## API 错误语义

- 请求字段校验失败由 FastAPI 返回 `422`；业务输入（例如只包含空白的 `question_text`）返回 `400`。
- 本地 LLM 配置不可用时返回 `503`，detail code 为 `q2pico_configuration_unavailable`。
- 任一 Q2PICO stage 用尽一次重试后返回 `502`，detail code 为 `q2pico_stage_retry_exhausted`，并包含
  `stage` 与 `attempts: 2`。

## 测试

单元测试不调用真实 LLM，而是向 method extractor 注入 fake `llm_caller`：

```text
tests/unit/q2pico/test_extractor.py
tests/unit/q2pico/test_api_errors.py
tests/unit/q2pico/test_factory.py
tests/unit/q2pico/test_run_q2pico.py
tests/unit/q2pico/test_benchmark_adapter.py
```

推荐验证命令：

```bash
PYTHONPATH=backend/src:. pytest tests/unit/q2pico/test_extractor.py -q
PYTHONPATH=backend/src:. pytest tests/unit/q2pico/test_factory.py -q
PYTHONPATH=backend/src:. pytest tests/unit/q2pico/test_run_q2pico.py -q
PYTHONPATH=backend/src:. pytest tests/unit/q2pico/test_benchmark_adapter.py -q
PYTHONPATH=backend/src:. pytest tests/unit -q
```

真实 LLM 冒烟验证使用单独开关，默认不在常规测试里触发：

```bash
RUN_LIVE_LLM_TESTS=1 PYTHONPATH=backend/src:. pytest tests/integration/q2pico/test_live_llm.py -q
```

该 live test 使用 benchmark 中固定的 Q2CRBench3 case，并通过 `LLM_CONFIG_PATH` 指向仓库根目录的 `llm.local.json`。默认关闭这个测试，是为了避免日常开发、CI 或离线环境意外发起外部 LLM 请求。测试同时覆盖：

- 默认 `expand_outcomes=True` 时额外返回 `O_expanded`
- 显式 `expand_outcomes=False` 时只返回显式 `O`
