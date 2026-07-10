# Backend 文档

本文档说明当前分支的后端框架、DDD 分层、模块调用关系、API 边界、method 接入方式、LLM 配置和开发运行方式。

业务 workflow 契约见 [`../docs/workflow_v3.md`](../docs/workflow_v3.md)。benchmark 构建和评估见 [`../benchmark/online_pipeline/README.md`](../benchmark/online_pipeline/README.md)。

## 1. 后端定位

当前后端只维护 Online EBM workflow 的模块化执行框架。

当前分支不再包含：

- legacy index construction
- frontend
- backend external legacy code
- shared legacy infrastructure
- workflow-level HTTP orchestration

后端当前提供的是模块级 API 和内部 Python method 调用框架。完整 workflow 如何串联，是业务契约和后续 orchestration 的问题；当前 API 层不直接暴露一个“跑完整 workflow”的 endpoint。

## 2. 总体目录

```text
backend/
  README.md
  src/
    ebm_backend/
      online_pipeline/
        domain/
        application/
        infrastructure/
        interfaces/
```

核心代码都在：

```text
backend/src/ebm_backend/online_pipeline/
```

## 3. DDD 分层

当前后端按 DDD / Clean Architecture 的方向组织。

**Domain 层**

- 目录：`online_pipeline/domain/`
- 职责：定义 workflow 的领域对象、值对象、模块输入输出结构和 JSON serialization。
- 边界：不依赖 FastAPI，不读写外部文件，不调用 LLM，不解析 HTTP request。

**Application 层**

- 目录：`online_pipeline/application/`
- 职责：定义应用层 port 和模块级 use case runner；负责把模块调用转给具体 method。
- 边界：不直接 import 某个具体 method，不处理 HTTP，不包含具体 LLM 调用细节。

**Infrastructure 层**

- 目录：`online_pipeline/infrastructure/`
- 职责：提供具体实现，包括 method registry、method implementations、LLM config/client 等外部技术细节。
- 边界：不定义业务契约本身，不把 FastAPI request schema 作为内部接口。

**Interfaces 层**

- 目录：`online_pipeline/interfaces/`
- 职责：对外接口层；当前是 FastAPI module-level routes 和 request schemas。
- 边界：不直接调用具体 method，不绕过 application runner。

依赖方向：

```text
interfaces -> application -> domain
infrastructure -> application/domain
application -> ports -> infrastructure adapter
```

当前具体调用链：

```text
FastAPI route
  -> request schema
  -> domain.from_jsonable(...)
  -> ModuleRunner
  -> ModuleMethodResolverPort
  -> RegistryModuleMethodResolver
  -> infrastructure method
  -> domain result
  -> domain.to_jsonable(...)
  -> HTTP response
```

## 4. Domain 层

目录：

```text
backend/src/ebm_backend/online_pipeline/domain/
```

Domain 层定义当前 workflow 的核心对象。

**`question.py`**

- 主要对象：`QuestionPICO`
- 说明：Module 1 的 question-level PICO 输出；字段为 `P/I/C/O`。

**`article.py`**

- 主要对象：`CleanedArticle`、`SearchRetrievalResult`
- 说明：在线检索和后续模块消费的清洗文章对象。

**`screening.py`**

- 主要对象：`ScreeningCriteria`、`StudyScreeningResult`
- 说明：Study Screening 的纳入排除标准、筛选决策和 included studies。

**`study_characteristics.py`**

- 主要对象：`StudyPIOCharacteristics`
- 说明：Study-level PIO characteristics，包括 population、interventions、comparators、outcomes。

**`risk_of_bias.py`**

- 主要对象：`RiskOfBiasAssessment`、`RoB1DomainJudgement`
- 说明：RoB 1 七域的 study-level risk-of-bias 判断。

**`meta_analysis.py`**

- 主要对象：`AnalysisSetting`、`StudyResultRow`、`OverallEstimate`、`SubgroupEstimate`、`MetaAnalysisResultPackage`
- 说明：Meta Analysis 的 setting、study result、method、overall/subgroup estimates 和 result package。

**`grade.py`**

- 主要对象：`GradeResult`、`SoFRowGRADEAssessment`、`GRADEDomainJudgement`
- 说明：GRADE 四个 downgrade domains 的最终输出对象。

**`common.py`**

- 主要对象：`WorkflowConstraints`、`DataType`、`GradeDomainName`
- 说明：跨模块共享的枚举和值对象。

**`serialization.py`**

- 主要对象：`to_jsonable`、`from_jsonable`
- 说明：在 dataclass domain object 和 JSON-safe dict/list 之间转换。

Domain 层是内部契约的核心。新增模块字段时，优先在 domain 对象里补齐，再让 application/API/benchmark 对齐。

## 5. Application 层

目录：

```text
backend/src/ebm_backend/online_pipeline/application/
```

当前 application 层包含两个核心文件：

```text
application/
  ports.py
  module_runner.py
```

### 5.1 Ports

`ports.py` 定义 application 需要的 method contract。

<table>
  <thead>
    <tr>
      <th>Port</th>
      <th>对应模块</th>
      <th>返回对象</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>Q2PICOPort</code></td>
      <td>Q2PICO</td>
      <td><code>QuestionPICO</code></td>
    </tr>
    <tr>
      <td><code>SearchRetrievalPort</code></td>
      <td>Search &amp; Article Retrieval</td>
      <td><code>SearchRetrievalResult</code></td>
    </tr>
    <tr>
      <td><code>StudyScreeningPort</code></td>
      <td>Study Screening</td>
      <td><code>StudyScreeningResult</code></td>
    </tr>
    <tr>
      <td><code>StudyPIOExtractionPort</code></td>
      <td>Study-level PIO Extraction</td>
      <td><code>list[StudyPIOCharacteristics]</code></td>
    </tr>
    <tr>
      <td><code>RiskOfBiasPort</code></td>
      <td>Risk of Bias</td>
      <td><code>list[RiskOfBiasAssessment]</code></td>
    </tr>
    <tr>
      <td><code>MetaAnalysisPort</code></td>
      <td>Meta Analysis</td>
      <td><code>MetaAnalysisResultPackage</code></td>
    </tr>
    <tr>
      <td><code>GradeAssessmentPort</code></td>
      <td>Four-domain GRADE Assessment</td>
      <td><code>GradeResult</code></td>
    </tr>
  </tbody>
</table>

`ModuleMethodResolverPort` 是 application 到 infrastructure 的边界。application 不知道具体 method 在哪个文件，只要求 resolver 能按 `module_name + method_name` 返回一个满足 port 的对象。

### 5.2 ModuleRunner

`module_runner.py` 是 application 层的模块级入口。

它做三件事：

1. 根据 module name 和 method name 解析 method。
2. 把调用参数传给 method。
3. 返回 domain result。

它不做：

- HTTP request 解析
- LLM 调用
- benchmark 评分
- 完整 workflow orchestration

当前 runner 方法：

```text
run_q2pico(...)
run_search_retrieval(...)
run_study_screening(...)
run_study_pio_extraction(...)
run_risk_of_bias(...)
run_meta_analysis(...)
run_grade_assessment(...)
```

## 6. Infrastructure 层

目录：

```text
backend/src/ebm_backend/online_pipeline/infrastructure/
```

当前 infrastructure 主要包含：

```text
infrastructure/
  llm/
  methods/
```

### 6.1 Method Registry

method registry 位于：

```text
infrastructure/methods/registry.py
infrastructure/methods/resolver.py
```

API 和 application 不直接 import 具体 method，而是通过：

```text
RegistryModuleMethodResolver.resolve(module_name, method_name)
  -> get_module_method(module_name, method_name)
```

普通模块的 method 加载规则：

```text
infrastructure/methods/<module>/<method_name>/method.py
```

该文件必须定义：

```python
def build_method():
    ...
```

例如：

```text
infrastructure/methods/study_pio/method_rule/method.py
infrastructure/methods/risk_of_bias/method_onestep_llm/method.py
```

调用时使用：

```text
method_name = "method_rule"
method_name = "method_onestep_llm"
```

### 6.2 Placeholder Modules

当前 registry 中这些模块是 API placeholder：

**`q2pico`**

- 状态：placeholder
- 说明：API contract 存在，但当前没有注册真实后端 method。

**`search_retrieval`**

- 状态：placeholder
- 说明：API contract 存在，但当前没有正式检索 method。

**`study_screening`**

- 状态：placeholder
- 说明：API contract 存在，但当前没有注册真实后端 method。

调用这些 placeholder 会返回 `501 Not Implemented`。

### 6.3 已接入 Method

当前已有 method / coordinator：

**`study_pio`**

- 路径：`methods/study_pio/method_rule/`
- 说明：规则型 Study PIO method。

**`risk_of_bias`**

- 路径：`methods/risk_of_bias/method_onestep_llm/`
- 说明：基于 LLM prompt 的 RoB 1 method。

**`meta_analysis`**

- 路径：`methods/meta_analysis/`
- 说明：模块级 coordinator，内部调用四个 subtask method。

**`grade`**

- 路径：`methods/grade/`
- 说明：模块级 coordinator，内部调用四个 domain method。

### 6.4 Meta Analysis Method 组织方式

Meta Analysis 有多个子任务，因此不是简单的一个 method 文件。

模块级入口：

```text
infrastructure/methods/meta_analysis/method.py
```

subtask method 加载器：

```text
infrastructure/methods/meta_analysis/loader.py
```

subtask 目录：

```text
meta_analysis/subtask2_study_results/
meta_analysis/subtask3_analysis_methods/
meta_analysis/subtask4_subgroup_analysis/
meta_analysis/subtask5_overall_estimates/
```

当前 coordinator 会用同一个 `method_name` 去加载四个 subtask method。例如 `method_name="method_test"` 时，会加载：

```text
subtask2_study_results/method_test.py
subtask3_analysis_methods/method_test.py
subtask4_subgroup_analysis/method_test.py
subtask5_overall_estimates/method_test.py
```

每个 subtask method 需要定义 `build_method()`，并实现 `meta_analysis/base.py` 中对应的 abstract interface。

### 6.5 GRADE Method 组织方式

GRADE 有四个独立 domain，因此也采用 coordinator + domain methods。

模块级入口：

```text
infrastructure/methods/grade/method.py
```

domain method 加载器：

```text
infrastructure/methods/grade/loader.py
```

domain 目录：

```text
grade/risk_of_bias/
grade/inconsistency/
grade/indirectness/
grade/imprecision/
```

当前 coordinator 会用同一个 `method_name` 去加载四个 domain method。例如 `method_name="method_test"` 时，会加载：

```text
risk_of_bias/method_test.py
inconsistency/method_test.py
indirectness/method_test.py
imprecision/method_test.py
```

每个 domain method 需要定义 `build_method()`，并实现 `grade/base.py` 中的 `GradeDomainMethod`：

```python
def run(self, *, domain_evidence: dict, evidence_body: dict) -> dict:
    ...
```

## 7. Interfaces 层

目录：

```text
backend/src/ebm_backend/online_pipeline/interfaces/api/
```

当前使用 FastAPI。

**`main.py`**

- 创建 FastAPI app。
- 注册 module routes。
- 提供 `/health`。

**`routes_modules.py`**

- 定义模块级 API routes。
- 把 request payload 转成 domain object。
- 调用 application `ModuleRunner`。
- 把 domain result 转成 JSON response。

**`request_schemas.py`**

- 定义 API request schemas。
- 当前只做接口层输入形状约束。
- 内部业务对象仍以 domain dataclass 为准。

**`dependencies.py`**

- 组装 application runner。
- 注入 infrastructure resolver。
- 当前使用 `RegistryModuleMethodResolver`。

### 7.1 当前 API

所有模块级 endpoint 都在 `/modules` 下。

<table>
  <thead>
    <tr>
      <th>Endpoint</th>
      <th>Application 调用</th>
      <th>说明</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>POST /modules/q2pico</code></td>
      <td><code>run_q2pico</code></td>
      <td>把临床问题转换成 <code>QuestionPICO</code>。当前 registry 中为 placeholder。</td>
    </tr>
    <tr>
      <td><code>POST /modules/search-retrieval</code></td>
      <td><code>run_search_retrieval</code></td>
      <td>根据 question PICO 进行检索。当前 registry 中为 placeholder。</td>
    </tr>
    <tr>
      <td><code>POST /modules/study-screening</code></td>
      <td><code>run_study_screening</code></td>
      <td>执行 study screening。当前 registry 中为 placeholder。</td>
    </tr>
    <tr>
      <td><code>POST /modules/study-pio-extraction</code></td>
      <td><code>run_study_pio_extraction</code></td>
      <td>抽取 included studies 的 study-level PIO characteristics。</td>
    </tr>
    <tr>
      <td><code>POST /modules/risk-of-bias</code></td>
      <td><code>run_risk_of_bias</code></td>
      <td>执行 study-level RoB 1 assessment。</td>
    </tr>
    <tr>
      <td><code>POST /modules/meta-analysis</code></td>
      <td><code>run_meta_analysis</code></td>
      <td>执行 Meta Analysis 模块级 coordinator。</td>
    </tr>
    <tr>
      <td><code>POST /modules/grade-assessment</code></td>
      <td><code>run_grade_assessment</code></td>
      <td>执行 GRADE 四域 assessment coordinator。</td>
    </tr>
  </tbody>
</table>

健康检查：

```text
GET /health
```

### 7.2 API 边界

当前 API 的设计边界：

- 暴露模块级 API。
- 不暴露完整 workflow orchestration API。
- 不暴露 Meta Analysis subtask 级 HTTP API。
- 不暴露 GRADE domain 级 HTTP API。
- benchmark 可以直接按 subtask/domain 调用内部 runner，但这不是 HTTP API 契约。

这样做的原因是：当前分支先稳定模块边界和 method 接入方式，完整 workflow orchestration 后续再单独设计。

## 8. LLM 配置

LLM 配置使用仓库根目录的 JSON 文件。

默认路径：

```text
llm.local.json
```

示例文件：

```text
llm.local.example.json
```

配置字段：

<table>
  <thead>
    <tr>
      <th>字段</th>
      <th>是否必需</th>
      <th>说明</th>
    </tr>
  </thead>
  <tbody>
    <tr>
      <td><code>api_key</code></td>
      <td>yes</td>
      <td>LLM provider API key。</td>
    </tr>
    <tr>
      <td><code>model</code> / <code>model_id</code></td>
      <td>yes</td>
      <td>模型名称。</td>
    </tr>
    <tr>
      <td><code>base_url</code></td>
      <td>no</td>
      <td>默认 <code>https://api.openai.com/v1</code>。</td>
    </tr>
    <tr>
      <td><code>api_mode</code></td>
      <td>no</td>
      <td><code>responses</code>、<code>chat</code> 或 <code>auto</code>；默认 <code>responses</code>。</td>
    </tr>
    <tr>
      <td><code>timeout_seconds</code></td>
      <td>no</td>
      <td>默认 <code>180</code>。</td>
    </tr>
    <tr>
      <td><code>temperature</code></td>
      <td>no</td>
      <td>默认 <code>0</code>。</td>
    </tr>
  </tbody>
</table>

可以通过环境变量覆盖配置路径：

```bash
export LLM_CONFIG_PATH=llm.local.json
```

`.env.example` 只保留非 secret 的 runtime options。LLM credential 不放 `.env.example`，放在本地 `llm.local.json`。

## 9. 开发环境

从仓库根目录创建虚拟环境：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

复制 LLM 配置：

```bash
cp llm.local.example.json llm.local.json
```

运行命令时设置 Python path：

```bash
export PYTHONPATH=backend/src:.
```

## 10. 启动 API

从仓库根目录运行：

```bash
PYTHONPATH=backend/src:. uvicorn ebm_backend.online_pipeline.interfaces.api.main:app --reload
```

默认访问：

```text
http://127.0.0.1:8000/health
```

OpenAPI 文档：

```text
http://127.0.0.1:8000/docs
```

## 11. 测试

当前后端测试保留为轻量单测。

运行当前配置测试：

```bash
PYTHONPATH=backend/src:. pytest -q tests/unit/infrastructure/test_llm_config.py
```

如果新增真实 method，建议至少补两类验证：

1. backend 层单测：验证配置、schema、resolver 或 method adapter。
2. benchmark smoke：验证 method 能在对应 benchmark split 上跑通，并产出 metrics。

benchmark 不是 backend unit test，它是模块评估体系。两者要分开维护。

## 12. 与 Benchmark 的关系

benchmark 直接调用内部 Python method，不通过 FastAPI routes。

原因：

- benchmark 需要按模块、subtask 或 domain 细粒度评估。
- benchmark 需要直接读 dataset、gold、runner 和 metrics。
- HTTP API 的目标是服务接口，不应该成为 benchmark 的唯一执行路径。

文档边界：

**`docs/workflow_v3.md`**

- 职责：业务 workflow 契约。
- 内容：模块边界、输入输出、领域对象流向。
- 不写：backend 代码组织、benchmark 数据和评估指标。

**`backend/README.md`**

- 职责：后端代码框架文档。
- 内容：DDD 分层、API 边界、method 接入、LLM 配置和运行方式。
- 不写：benchmark 数据分布和评估细节。

**`benchmark/online_pipeline/README.md`**

- 职责：benchmark 总入口。
- 内容：benchmark 构建、数据、评估、metrics 和 runs。
- 不写：backend 内部框架设计决策。

## 13. 新增 Method 的建议流程

### 13.1 普通模块

普通模块 method 建议放在：

```text
backend/src/ebm_backend/online_pipeline/infrastructure/methods/<module>/<method_name>/method.py
```

并提供：

```python
def build_method():
    return Method()
```

`Method` 对象需要实现 application `ports.py` 中对应 port 的 `run(...)` 方法。

新增后要检查：

- method name 是否能被 registry 解析。
- 输入输出是否使用 domain 对象。
- 是否需要 LLM config。
- 是否有最小 backend 单测。
- 是否能跑对应 benchmark smoke。

### 13.2 Meta Analysis Subtask

Meta Analysis subtask method 放在：

```text
backend/src/ebm_backend/online_pipeline/infrastructure/methods/meta_analysis/<subtask>/<method_name>.py
```

其中 `<subtask>` 是：

```text
subtask2_study_results
subtask3_analysis_methods
subtask4_subgroup_analysis
subtask5_overall_estimates
```

文件需要定义：

```python
def build_method():
    return Method()
```

并实现 `meta_analysis/base.py` 中对应 subtask interface。

### 13.3 GRADE Domain

GRADE domain method 放在：

```text
backend/src/ebm_backend/online_pipeline/infrastructure/methods/grade/<domain>/<method_name>.py
```

其中 `<domain>` 是：

```text
risk_of_bias
inconsistency
indirectness
imprecision
```

文件需要定义：

```python
def build_method():
    return Method()
```

并实现：

```python
run(domain_evidence: dict, evidence_body: dict) -> dict
```

返回 dict 至少应包含：

```text
downgraded
severity
levels
level_evaluable
rationale
```

## 14. 当前需要注意的边界

- API 层目前是模块级，不是完整 workflow 入口。
- `q2pico`、`search_retrieval`、`study_screening` 当前在 backend registry 中仍是 placeholder。
- Meta Analysis 和 GRADE 在 backend 中有 coordinator，但 benchmark 仍可以单独评估 subtask/domain。
- `method_test` 主要用于 smoke 和框架验证，不代表最终医学方法质量。
- `gold` 是 benchmark-only baseline，不是 backend 真实业务 method。
- LLM 配置统一走 `llm.local.json`，不要把 API key 写入代码或 README。
