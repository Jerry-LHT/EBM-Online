# Backend 文档

> 维护说明：当前后端分层与已迁移模块的权威实现说明见
> [`../docs/implementation/backend-framework.md`](../docs/implementation/backend-framework.md)。
> 当前七个 module-level API 均通过专用 use case 和业务 factory 装配，不再使用通用 resolver、registry
> 或 module facade。

本文档说明当前分支的后端框架、DDD 分层、模块调用关系、API 边界、method 接入方式、LLM 配置和开发运行方式。

业务 workflow 契约见 [`../docs/workflow_v3.md`](../docs/workflow_v3.md)。benchmark 构建和评估见 [`../benchmark/online_pipeline/README.md`](../benchmark/online_pipeline/README.md)。

## 1. 后端定位

当前后端维护 Online EBM workflow 的模块化执行框架和完整证据链编排入口。

当前分支不包含：

- legacy index construction
- frontend
- backend external legacy code
- shared legacy infrastructure

后端当前提供七个模块级 API，以及 `POST /workflow`、`GET /workflow/runs/{run_id}`、
`GET /workflow/runs/{run_id}/evidence-package` 和 application 层的 `RunOnlineEBMWorkflow` 编排入口。
完整 workflow 先运行 Q2PICO、检索和筛选，再以最多三个 worker 并发执行 Study PIO、Risk of Bias 和
Meta-analysis；三个分支全部成功后执行 GRADE。`POST /workflow` 最终响应是紧凑、版本化的完整证据链
`EvidencePackage`，而不是只返回 GRADE 或透传所有内部调试对象。

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
- 职责：提供具体 method implementations、业务 factory、LLM config/client 等外部技术细节。
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
  -> application use case
  -> application capability ports
  -> infrastructure adapters
  -> domain result
  -> domain.to_jsonable(...)
  -> HTTP response
```

所有 module-level API 都由 `interfaces/api/dependencies.py` 选择 concrete method，并注入对应的
application use case。Application 不接收 module name 或 method name，也不依赖通用 resolver。

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

- 主要对象：`MetaAnalysisSynthesisPlan`、`SynthesisTarget`、`StudyResultRow`、
  `CandidateResolutionRecord`、`SynthesisAnalysisDataset`、`AnalysisSetting`、`OverallEstimate`、
  `SubgroupEstimate`、`MetaAnalysisResultPackage`
- 说明：Meta Analysis 的 frozen plan、候选抽取、候选消解、统计数据集、method 与 estimates。

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

当前 application 层按 use case 和 port 组织：

```text
application/
  use_cases/
    run_q2pico.py
    run_search_retrieval.py
    run_study_screening.py
    run_study_pio.py
    run_risk_of_bias.py
    run_meta_analysis.py
    run_grade.py
    run_online_ebm_workflow.py
    get_workflow_run.py
  ports/
    q2pico.py
    search_retrieval.py
    evidence_review.py
    synthesis.py
    workflow_persistence.py
```

### 5.1 Ports

`ports/` 定义 application 所需的能力 contract。

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
      <td><code>SearchSourceResult</code></td>
    </tr>
    <tr>
      <td><code>ScreeningCriteriaPlannerPort</code></td>
      <td>Study Screening criteria planning</td>
      <td><code>ScreeningCriteria</code></td>
    </tr>
    <tr>
      <td><code>StudyArticleScreenerPort</code></td>
      <td>Study Screening article judgment</td>
      <td><code>ArticleScreeningResult</code></td>
    </tr>
    <tr>
      <td><code>StudyPIOExtractionPort</code></td>
      <td>Study-level PIO Extraction</td>
      <td><code>list[StudyPIOCharacteristics]</code></td>
    </tr>
    <tr>
      <td><code>RiskOfBiasPort</code></td>
      <td>Risk of Bias</td>
      <td><code>RiskOfBiasAssessment</code></td>
    </tr>
    <tr>
      <td><code>SynthesisPlanningPort</code>, <code>StudyEvidencePort</code>, <code>AnalysisMethodsPort</code>, <code>SubgroupAnalysisPort</code>, <code>OverallEstimatesPort</code></td>
      <td>Meta Analysis subtasks</td>
      <td>Subtask-specific structured payloads</td>
    </tr>
    <tr>
      <td><code>WorkflowRunStorePort</code></td>
      <td>Complete workflow persistence</td>
      <td>Persisted workflow run JSON</td>
    </tr>
    <tr>
      <td><code>GRADERiskOfBiasPort</code>, <code>GRADEInconsistencyPort</code>, <code>GRADEIndirectnessPort</code>, <code>GRADEImprecisionPort</code></td>
      <td>Four parallel GRADE domains</td>
      <td>Domain judgement payloads</td>
    </tr>
  </tbody>
</table>

每个 use case 直接依赖对应业务能力 port，由 interface composition root 注入 concrete
infrastructure adapter。Application 层不提供跨业务的通用 facade 或 method resolver。

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
  persistence/
```

产品 API 默认使用 `.runtime/online_pipeline/` 保存 workflow stage checkpoints、最终证据链、PubMed/PMC
positive-result cache 和 article-level RoB 1 domain cache；可通过 `EBM_RUNTIME_DIR` 指定其他本地目录。
Benchmark 不会默认注入这些产品缓存。持久化和缓存均使用原子文件替换，不需要数据库；第一版不提供多节点
共享、自动恢复或自动淘汰。

### 6.1 Business Factories

每个业务在自己的 `infrastructure/methods/<module>/factory.py` 暴露语义化的
`build_production_*()`，返回当前正式业务批准的 concrete adapter。Method 的基本目录规则是：

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
infrastructure/methods/study_pio/extraction_study_pico_slotwise_llm/method.py
infrastructure/methods/risk_of_bias/method_onestep_llm/method.py
```

正式 composition root 使用：

```python
build_production_study_pio()
build_production_risk_of_bias()
```

七个模块均由 `interfaces/api/dependencies.py` 通过各自 production factory 装配 application
ports，该文件中不出现内部 method-name 字符串。Benchmark 如需比较其他 method，通过
module-specific adapter 调用业务 factory 保留的显式选择入口，不经过通用 backend registry。

### 6.2 Method 结构

已迁移业务目录只保留 factory、必要的共享技术组件和相互隔离的 concrete method 目录。Method-local
Python、prompt 和 helper 不放在业务根目录，也不由 infrastructure coordinator 调用 application use case。

### 6.3 已接入 Method

当前已接入的 concrete methods 与 application orchestration：

**`study_pio`**

- 正式路径：`methods/study_pio/extraction_study_pico_slotwise_llm/`
- 说明：单-study、slotwise LLM PICO extraction；由 application 对多个 studies 做有界并发。
- 历史 `method_rule` 不属于维护源码；本地快照仅可放在被 Git 忽略的 `archive/` 中。

**`risk_of_bias`**

- 路径：`methods/risk_of_bias/method_onestep_llm/`、`method_calibrated_slots/`、`method_hybrid_slots/`
- 说明：三个相互独立的 RoB 1 concrete methods。每个目录分别拥有自己的 article evidence、domain
  assessor、prompt builder 和 prompt/spec 内容，不跨 method 复用内部实现。
- application 的 `RunRiskOfBias` 负责按 `included_studies` 关联文章并保持确定性输出顺序；concrete
  method 通过 `assess(study_id, article)` 只评估一个 study。
- 正式 HTTP API 通过 `build_production_risk_of_bias()` 装配，当前该 factory 选择
  `method_onestep_llm`；请求体不接受内部 method name。

**`meta_analysis`**

- 路径：`methods/meta_analysis/`
- 说明：result-blind synthesis planning、article-level Study Evidence 与 Subtask 3–5 的独立
  infrastructure adapters；模块级业务编排位于 application `RunMetaAnalysis`。
- 正式 HTTP API 显式装配五项能力；各实现名称不进入请求契约。
- `RunMetaAnalysis` 从 question PICO 与 frozen screening criteria 生成最多十二个 targets；Study PIO 与
  RoB 是平行分支，不是 Meta 输入。

**`grade`**

- 路径：`methods/grade/<domain>/<concrete_method>/`
- 说明：四个 domain adapter 完全隔离；domain 根层和 GRADE 根层不放共享 helper。
- application 的 `RunGrade` 对同一个 SoF row 的四域进行 `max_workers=4` 的有界并发，并按固定字段组装结果。

### 6.4 Meta Analysis Method 组织方式

Meta Analysis 有多个子任务，因此由 application 的 `RunMetaAnalysis` 负责业务编排，不在 infrastructure
根层设置 module coordinator 或动态 loader。

业务能力目录：

```text
meta_analysis/synthesis_planning/
meta_analysis/study_evidence/
meta_analysis/analysis_method_selection/
meta_analysis/subgroup_analysis/
meta_analysis/overall_estimation/
```

`infrastructure/methods/meta_analysis/factory.py` 显式构造当前正式组合：

```text
synthesis_planning/synthesis_plan_llm/
study_evidence/source_workspace_agent/
analysis_method_selection/contextual/
subgroup_analysis/statistical/
overall_estimation/statistical/
```

五个 adapters 分别注入对应 application ports。每个 method 继续定义 `build_method()`；不使用公共
method name 动态解析能力。Study Evidence adapter 内部返回候选、resolution 和正式 data rows，只有
`SynthesisAnalysisDataset` 中已唯一消解的结果可进入 Subtask 3–5。

### 6.5 GRADE Method 组织方式

GRADE 有四个独立 domain，由 application 编排，不在 infrastructure 设置 module coordinator 或动态 loader。

domain 目录：

```text
grade/risk_of_bias/
grade/inconsistency/
grade/indirectness/
grade/imprecision/
```

当前正式组合由 `infrastructure/methods/grade/factory.py` 显式构造：

```text
risk_of_bias/method_llm/
inconsistency/method_local_llm_profile/
indirectness/method_llm/
imprecision/method_expert_threshold_ci/
```

每个 concrete method 通过方法签名结构化满足对应 application port，不继承 infrastructure base：

```python
def run(self, *, grade_input: DomainSpecificGRADEInput) -> dict:
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

**`routes_workflow.py`**

- 定义完整证据链的 `POST /workflow`。
- `POST /workflow` 和 `/evidence-package` 查询返回紧凑 `EvidencePackage`；普通 run 查询返回完整审计结果。
- 检索文章全文只供内部模块消费，不进入 workflow 响应。

**`request_schemas.py`**

- 定义 API request schemas。
- 当前只做接口层输入形状约束。
- 内部业务对象仍以 domain dataclass 为准。

**`dependencies.py`**

- 为每个模块组装专用 application use case 和 concrete port adapters。

### 7.1 当前 API

所有模块级 endpoint 都在 `/modules` 下；完整流程 endpoint 是 `POST /workflow`。

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
      <td>通过专用 use case 把临床问题转换成 <code>QuestionPICO</code>。</td>
    </tr>
    <tr>
      <td><code>POST /modules/search-retrieval</code></td>
      <td><code>run_search_retrieval</code></td>
      <td>通过专用 use case 编排检索策略并获取文章。</td>
    </tr>
    <tr>
      <td><code>POST /modules/study-screening</code></td>
      <td><code>run_study_screening</code></td>
      <td>通过专用 use case 编排 criteria planning 和 article screening。</td>
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
      <td>通过 <code>RunMetaAnalysis</code> 编排四个独立 subtask capabilities。</td>
    </tr>
    <tr>
      <td><code>POST /modules/grade-assessment</code></td>
      <td><code>run_grade_assessment</code></td>
      <td>通过 <code>RunGrade</code> 并发编排四个独立 domain capabilities。</td>
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
- 暴露完整 evidence-chain workflow API。
- 不暴露 Meta Analysis subtask 级 HTTP API。
- 不暴露 GRADE domain 级 HTTP API。
- benchmark 可以直接按 subtask/domain 调用内部 runner，但这不是 HTTP API 契约。

Workflow 运行中，`CleanedArticle[]` 只作为 Screening、Study PIO、RoB 和 Meta-analysis 的内部证据。
产品响应不返回全文、文章 metadata、Meta candidates 或 stage debug output，只保留 protocol、检索数量、
纳入 study 的紧凑 PIO/RoB，以及 evidence-unit 级 study effects、Meta estimates 和 four-domain GRADE。
完整审计结果仍可按 run ID 查询；产品响应使用独立 execution/evidence/readiness 状态表达部分证据。

## 8. LLM 配置

LLM 配置使用仓库根目录的 JSON 文件。

统一 client 使用 OpenAI 官方 Python SDK，并向业务方法保留一个 `call_llm_json()` 入口。默认
`api_mode=responses`；`chat` 只用于尚未完整支持 Responses API 的兼容网关。`auto` 和历史单数
`response` 只在配置解析时归一化为 `responses`，运行时不会在两个 endpoint 之间自动降级，以免重复
计费或产生不同语义的第二次结果。

Responses 与 Chat 分别使用各自的结构化输出参数（`text.format` 与 `response_format`），有 schema 时
使用 strict JSON Schema，否则使用 JSON object mode。两种模式都显式设置 `store=false`。官方 SDK
负责连接、限流和服务端错误的有界技术重试；普通 4xx 不重试。Chat 兼容层仅对已验证的“缺少 JSON
marker”400 错误用完全相同的请求再试一次，Responses 对同一兼容网关错误采用相同的窄重试；其他 400
直接返回类型化 `LLMAPIError`。两种模式都把 JSON marker 放在 provider 实际检查的主要输入中。
Responses 请求不发送 `temperature`，以兼容不支持该参数的推理模型和网关；Chat 仅在配置或调用方
显式提供时发送该参数。

Meta-analysis composition root 在每次构造 use case 时只读取一次 `llm.local.json`，并把同一不可变
`LLMConfig` 注入 planning 和 article Evidence Agent。运行中修改配置文件只影响
下一次 workflow，不会让当前 workflow 在 Chat 与 Responses 之间切换。

统一 LLM client 在单个后端进程内最多允许 32 个同时在途请求。各 application 或 method 可以设置更小的
worker 数，但嵌套 worker pool 不能突破这一总外呼上限；多进程部署时该上限按进程分别生效。

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
      <td><code>responses</code>、<code>chat</code> 或 <code>auto</code>；默认 <code>responses</code>，<code>auto</code> 当前作为 <code>responses</code> 的兼容别名。</td>
    </tr>
    <tr>
      <td><code>timeout_seconds</code></td>
      <td>no</td>
      <td>默认 <code>180</code>。</td>
    </tr>
    <tr>
      <td><code>temperature</code></td>
      <td>no</td>
      <td>Responses 模式忽略并不发送；Chat 模式只有配置或调用方显式提供时才发送。</td>
    </tr>
  </tbody>
</table>

可以通过环境变量覆盖配置路径：

```bash
export LLM_CONFIG_PATH=llm.local.json
```

`.env.example` 只保留非 secret 的 runtime options。LLM credential 不放 `.env.example`，放在本地 `llm.local.json`。

## 9. 开发环境

后端与 benchmark 统一使用 Python 3.11；当前正式验证版本为 Python 3.11.14。不要使用共享的
Anaconda/base 环境，也不要使用 Python 3.13+ 运行当前分支。

从仓库根目录创建虚拟环境：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python --version
# Python 3.11.x
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

运行完整 backend 验证：

```bash
PYTHONPATH=backend/src:. pytest -q tests/unit tests/integration
```

Python 3.11.14 当前基线为 `427 passed, 39 skipped`；需要网络或真实 LLM 的测试默认跳过。

运行当前配置测试：

```bash
PYTHONPATH=backend/src:. pytest -q tests/unit/infrastructure/test_llm_config.py
```

如果新增真实 method，建议至少补两类验证：

1. backend 层单测：验证配置、schema、use case、factory 或 method adapter。
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

Concrete method 建议放在：

```text
backend/src/ebm_backend/online_pipeline/infrastructure/methods/<module>/<method_name>/method.py
```

并提供：

```python
def build_method():
    return Method()
```

`Method` 对象需要实现 application `ports.py` 中对应 port 的 `run(...)` 方法。

使用 prompt 的 method 应把模板放在同一 method 目录的 `prompts/`。业务根目录只保留 factory 和必要的
共享技术组件。所有模块都由各自 factory 装配，不加入通用 registry。

新增后要检查：

- method 是否由对应业务 factory 显式构造。
- 输入输出是否使用 domain 对象。
- 是否需要 LLM config。
- 是否有最小 backend 单测。
- 是否能跑对应 benchmark smoke。

### 13.2 Meta Analysis Business Capabilities

Meta Analysis method 放在：

```text
backend/src/ebm_backend/online_pipeline/infrastructure/methods/meta_analysis/<capability>/<method_name>/
```

其中 `<capability>` 是：

```text
synthesis_planning
study_result_extraction
candidate_resolution
analysis_method_selection
subgroup_analysis
overall_estimation
```

文件需要定义：

```python
def build_method():
    return Method()
```

并通过方法签名结构化满足 application 中对应的 Meta-analysis subtask port；concrete adapter 不需要
继承 infrastructure base class。

### 13.3 GRADE Domain

GRADE domain method 放在：

```text
backend/src/ebm_backend/online_pipeline/infrastructure/methods/grade/<domain>/<method_name>/method.py
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

- API 层同时提供模块级入口和完整 workflow 入口。
- 七个 module-level API 均使用专用 use case + factory 装配，不存在通用 backend registry。
- Meta Analysis 和 GRADE 的业务编排均位于 application；infrastructure 只提供独立 adapters。
- Meta Analysis 正式 API 已显式装配六项独立能力，不要求它们共用一个 method name。
- 历史 `method_test` 只用于 smoke 和框架验证，不是当前 production wiring。
- `gold` 是 benchmark-only baseline，不是 backend 真实业务 method。
- LLM 配置统一走 `llm.local.json`，不要把 API key 写入代码或 README。
