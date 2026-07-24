# 后端框架实现设计

本文档定义 Online EBM 独立后端的实现框架边界。

当前目标不是重写全部后端，而是明确后续开发应该落在哪一层，避免业务编排、method 实现、API 入参和 benchmark 适配互相污染。

本文档描述的是当前后端的目标分层和已完成收口的主路径。七个 module-level API 均已完成专用
use case + interface 装配，通用 facade、resolver 和 backend method registry 已移除。

## 运行时基线

当前 backend、benchmark 和测试统一使用 Python 3.11，已验证的本地版本为 Python 3.11.14。项目依赖安装在
仓库根目录 `.venv`，不复用系统或 Anaconda/base 环境。创建与验证命令为：

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
PYTHONPATH=backend/src:. pytest -q tests/unit tests/integration
```

Live LLM/provider tests 继续由各自显式环境变量控制，普通
回归不会访问外部服务。Python 3.13+ 不属于当前维护的运行时范围。

## 1. 基本判断

后端是独立业务系统，不以 benchmark method registry 为核心架构。

Benchmark 可以作为外部评测入口，也可以通过 adapter 调用后端能力，但不能反向决定后端的领域模型、应用层 use case、API 形态或 method 组织方式。

后端主线应按 DDD / Clean Architecture 的依赖方向推进：

```text
interfaces -> application -> domain
infrastructure -> application/domain
```

其中：

- `interfaces` 负责入口适配。
- `application` 负责业务 use case 和流程编排。
- `domain` 负责稳定业务语言和数据契约。
- `infrastructure` 负责 methods、LLM、检索、存储、缓存等外部技术实现。

## 2. Domain 层

当前 `domain/` 按 EBM workflow 阶段划分，暂时不重构。

现有结构可以继续保留：

```text
domain/
  question.py
  article.py
  screening.py
  study_characteristics.py
  risk_of_bias.py
  meta_analysis.py
  grade.py
  common.py
  serialization.py
```

这个划分符合当前业务语言，因为 EBM workflow 的阶段本身就是业务边界的一部分。

### 2.1 职责

`domain` 负责：

- 定义稳定的 EBM 业务对象和值对象。
- 定义模块之间传递的内部数据契约。
- 定义枚举、状态、判断结果、证据来源等共享语义。
- 提供与领域对象相关的纯序列化和纯校验能力。

`domain` 不负责：

- 调用 LLM。
- 管理 prompt。
- 编排 LLM method 内部 steps。
- 读写数据库、文件或网络。
- 暴露 FastAPI request schema。
- 兼容 benchmark 数据格式。

### 2.2 调整原则

当前阶段不主动重拆 `domain/`。

只有当某个阶段文件明显过大、概念边界已经稳定、且拆分能降低维护成本时，才考虑从单文件演进为子包。例如：

```text
domain/meta_analysis/
  setting.py
  study_result.py
  estimate.py
```

在此之前，不为了形式上的 DDD 包结构做迁移。

## 3. Application 层

`application` 是后端接下来最需要增强的层。

它是独立后端的 use case 编排层。每个模块的 application use case 直接依赖业务 port，不依赖通用
method resolver，也不根据 module name 或 method name 分发业务。

### 3.1 职责

`application` 负责：

- 定义用户动作或系统任务对应的 use case。
- 编排 EBM workflow 的业务步骤。
- 组织模块间输入输出。
- 管理任务状态、失败处理、重试边界和恢复策略。
- 定义需要 infrastructure 实现的 ports。
- 调用 domain 对象和 domain 规则完成业务决策。

`application` 不负责：

- 写 prompt。
- 直接调用 OpenAI、数据库、外部检索服务。
- 处理 HTTP request schema。
- 读取 benchmark gold label。
- 根据 benchmark method name 做业务分支。

### 3.2 建议结构

当前按 use case 和 ports 组织：

```text
application/
  use_cases/
    build_evidence_package.py
    get_workflow_run.py
    run_q2pico.py
    run_search_retrieval.py
    run_study_screening.py
    run_study_pio.py
    run_risk_of_bias.py
    run_meta_analysis.py
    run_grade.py
    run_online_ebm_workflow.py
  ports/
    q2pico.py
    search_retrieval.py
    evidence_review.py
    synthesis.py
    workflow_persistence.py
```

其中 ports 按业务职责拆分，`use_cases/run_*.py` 表达具体用户动作或系统任务。不存在跨业务的
`ModuleUseCaseFacade` 或通用 `MethodResolverPort`。

当前也提供完整业务流程的 application 编排：

```text
application/
  use_cases/
    run_online_ebm_workflow.py
```

旧的 `application/module_runner.py` 和 `application/screening_criteria.py` 兼容导入入口已经移除。新代码应直接从 `application/use_cases/` 导入 use case。

### 3.3 业务编排位置

完整 workflow 编排放在 `application`。当前调用关系为：

```text
run_online_ebm_workflow
  -> run_q2pico
  -> run_search_retrieval
  -> run_study_screening
  -> [run_study_pio, run_risk_of_bias, run_meta_analysis] (bounded concurrency, max_workers=3)
  -> run_grade
```

三个并行分支语义独立，输出按固定业务顺序记录。单个并行分支失败不会抹去其他成功分支及其中间结果；
顺序阶段失败则停止后续执行。三个分支全部成功后，GRADE 使用它们与前序产物构造完整证据链。
`run_online_ebm_workflow` 产出并持久化完整 `OnlineEBMWorkflowResult`；无外部依赖的
`build_evidence_package` 只做确定性字段投影，按 study 和 synthesis target 装配紧凑产品结构，不重新调用
LLM 或执行统计计算。

当前同时提供 Python application 入口、`POST /workflow`、`GET /workflow/runs/{run_id}` 和
`GET /workflow/runs/{run_id}/evidence-package`。`POST` 返回紧凑 EvidencePackage，前一个 GET 返回完整审计
结果，后一个 GET 从持久化审计结果重新生成同一版本化产品结构。完整 workflow
通过注入的 `WorkflowRunStorePort` 在 stage 完成后保存 checkpoint；文件系统实现位于
`infrastructure/persistence/workflow_runs/`。持久化失败通过独立状态暴露，不覆盖业务执行结果。

检索得到的 `CleanedArticle[]` 是流程内部证据输入。EvidencePackage 只保留检索数量、warning codes、紧凑
Study PIO/RoB，以及 resolved DataRow、Meta estimate 和 GRADE judgement；文章全文、详细 metadata、Meta
candidates、source spans 和 stage debug output 不进入产品响应。中途失败时，完整审计结果仍保留成功阶段，
EvidencePackage 则分别标记执行状态、证据完整性和 downstream readiness。

单模块内部如果有稳定业务流程，也应优先放在 application service。

例如 meta-analysis 的稳定业务边界可以是：

```text
define analysis settings
-> extract study results
-> choose analysis method
-> calculate estimates
-> package synthesis result
```

具体某一步由 LLM method 如何读取材料、如何 retry、如何写 debug artifacts，属于 infrastructure。

## 4. Infrastructure 层

`infrastructure` 放所有技术实现。

当前轻量运行存储位于 `.runtime/online_pipeline/`，可通过非敏感配置 `EBM_RUNTIME_DIR` 修改。其内容包括
workflow runs、PubMed/PMC positive-result cache 和 article-level RoB 1 domain cache。文件写入使用同目录
临时文件加原子 replace；第一版不提供数据库、多节点共享或自动断点恢复。

### 4.1 Method 位置

Method 应作为 application port 的实现，而不是业务边界本身。目录命名优先表达业务能力或提供方，不强制加 `method_` 前缀。

新 method 默认放在：

```text
infrastructure/
  methods/
    q2pico/
      factory.py
      split_slot_llm/
        method.py
        extractor.py
        prompts/
    search_retrieval/
      factory.py
      official_mesh.py
      pubmed_pmc/
      mesh_mapping_official/
      textword_expansion_official/
    study_screening/
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
    study_pio/
      factory.py
      extraction_study_pico_slotwise_llm/
        method.py
        pipeline.py
        materials.py
        parsing.py
        prompts/
    risk_of_bias/
      factory.py
      method_onestep_llm/
        method.py
        article_evidence.py
        domain_assessor.py
        prompt_builder.py
        prompts/
      method_calibrated_slots/
      method_hybrid_slots/
    meta_analysis/
      factory.py
      synthesis_planning/
      study_evidence/source_workspace_agent/  # current production adapter
      analysis_method_selection/
      subgroup_analysis/
      overall_estimation/
    grade/
      factory.py
      risk_of_bias/
        method_llm/
        method_deterministic/
      inconsistency/
        method_local_llm_profile/
        method_deterministic/
      indirectness/
        method_staged_applicability/
      imprecision/
        method_llm_web/
        method_deterministic/
```

Method 内部可以包含：

- prompt templates
- LLM client 调用
- tool calling
- source packing
- cache
- debug artifacts
- retry/recovery implementation
- provider-specific parsing

Method 对外应实现 `application` 定义的 port，不直接暴露 prompt、model 或 benchmark 细节。

业务目录只保留 factory 和确有必要的共享技术组件。每个 concrete method 使用独立目录，相关 Python
实现、prompt、schema 和 method-local helper 都放在该目录内；使用 prompt 的 method 统一使用本地
`prompts/`。不得在业务根目录放一个反向调用 application use case 的 coordinator `method.py`。

`study_screening` 不再使用覆盖完整模块的 `StudyScreeningPort`。它由 application 的
`RunStudyScreening` 编排 `ScreeningCriteriaPlannerPort` 和 `StudyArticleScreenerPort`；并发筛选、
输入顺序恢复以及最终排纳聚合属于 application 业务流程。Benchmark 若只评估 article screening 子任务，
由 benchmark-side adapter 调用 `StudyArticleScreenerPort` implementation，不在 backend infrastructure
增加 workflow coordinator。

### 4.2 与现有 methods 的关系

当前 `infrastructure/methods/` 只承载正式 method 实现、业务 factory 和必要的共享技术组件：

- 每个业务 factory 暴露无 method-name 参数的 `build_production_*()`，作为正式业务装配入口。
- 如需为 benchmark 保留多实现选择，只能在本业务 factory/module-specific adapter 内显式映射。
- method 不是业务边界本身，正式业务编排仍在 application。
- module-level API 的 method/source 选择参数只由 interface composition root 处理。
- benchmark 通过 module-specific adapter 调用正式 factory 或 port implementation。
- 不把 benchmark-specific 输入输出格式扩散到 domain 和 application。

后续如果某个实验 method 成为正式能力，应让它实现 application port，再由 benchmark adapter 调用该正式能力。

## 5. Interfaces 层

`interfaces` 是入口适配层，当前主要是 FastAPI。

### 5.1 职责

`interfaces` 负责：

- 定义 HTTP request/response schema。
- 做输入格式校验。
- 做鉴权和权限检查。
- 在依赖装配点选择 concrete adapter，并调用 application use case。
- 将 domain/application result 转成 response。

`interfaces` 不负责：

- 编排业务 workflow。
- 在 route handler 里写 method 业务逻辑。
- 让业务入口到处散落 infrastructure 装配代码。
- 保存业务状态。
- 根据 benchmark 逻辑改变业务行为。

当前的实践是：`interfaces/api/dependencies.py` 作为装配点，为七个模块构造各自的 use case + concrete
infrastructure adapter；route handler 只做参数解析和结果转换。

### 5.2 API 形态

开发期可以继续保留 module-level API。

正式业务 API 应围绕业务资源和任务，而不是 method implementation：

```text
POST /reviews
POST /reviews/{review_id}/workflow-runs
POST /reviews/{review_id}/screening-runs
POST /reviews/{review_id}/meta-analysis-runs
GET  /jobs/{job_id}
GET  /reviews/{review_id}/results
```

正式 API 不应要求调用方传 `method_name`。Concrete adapter 由业务 production factory 在代码中显式决定；
模型、prompt version、timeout、retry 和并发上限等运行参数由后端配置决定。统一 LLM client 使用
进程内有界信号量，所有业务与 method 合计最多同时发出 8 个 LLM 请求；method 自己的 worker pool
仍须遵守更小的业务或 provider 上限。

### 5.3 Curated evidence-chain integration case

`tests/integration/workflow/test_live_curated_evidence_chain.py` 是显式 opt-in 的受控证据链测试。它使用人工确认
PICO、人工排纳的两篇真实 RCT、完整 PMC sections 和原始目标表格，真实执行 Study PIO、RoB、Meta 和 GRADE。
该测试不被 backend import，也不注入 benchmark gold candidate、effect estimate、weight 或 GRADE label。
它用于验证“给定合格文章后的完整证据链”，不能替代自动在线检索召回率验证；默认 pytest 必须保持 skip，
仅在 `RUN_LIVE_CURATED_WORKFLOW=1` 时调用真实模型。

LLM transport 由 `infrastructure/llm/client.py` 通过 OpenAI 官方 Python SDK 实现。业务方法统一调用
`call_llm_json()`，不直接选择 SDK endpoint。默认模式为 Responses，Chat 是显式配置的兼容模式；历史
`auto` 只解析为 Responses，不做运行时 endpoint fallback。Client 分别映射两种 API 的结构化输出、输出
token 与 reasoning 参数，复用 SDK HTTP client，显式关闭 response storage，并将最终 provider 异常转换成
包含 status、request id、retry-after 与 retryable 标志的 `LLMAPIError`。技术重试由 SDK 有界执行；业务
method 的 retry 只应面向 schema、语义校验或 stage-level recovery，不应重新实现 HTTP retry policy。
需要多个 LLM adapters 的长流程必须由 composition root 读取一次配置并注入同一 snapshot；不得让后续
stage 在运行中重新读取已变化的本地配置并切换 endpoint。当前 Meta-analysis 已遵守这一约束。

当前 module-level API 也遵守这一约束：Q2PICO、Study Screening、Study PIO、Risk of Bias、Meta-analysis
和 GRADE 均由 interface composition root 调用各自 `build_production_*()` 装配。Search Retrieval 的
`source_names` 是检索来源这一业务选择，不是 implementation name，因此仍属于正式请求契约。

## 6. Benchmark 边界

Benchmark 是外部评测系统，不是后端核心层。

推荐边界：

```text
benchmark adapter
  -> application use case / port
  -> domain result
  -> benchmark metric format
```

Benchmark 可以做：

- 构造评测输入。
- 调用后端 application 能力。
- 将输出转换成评测格式。
- 计算指标。

Benchmark 不应该做：

- 影响正式 API 的入参设计。
- 要求 application 按 benchmark method name 分支。
- 把 gold label 或评测字段写入 domain。
- 决定 method 的业务边界。

## 7. 开发落点规则

新增功能时按以下规则决定代码位置：

1. 如果是 EBM 稳定概念、状态、结果对象，放 `domain`。
2. 如果是一次用户动作或系统任务的流程，放 `application/use_cases`。
3. 如果是跨多个步骤的业务编排，放 `application/services`。
4. 如果是 LLM、prompt、method、检索、数据库、缓存、文件系统，放 `infrastructure`。
5. 如果是 HTTP 输入输出，放 `interfaces/api`。
6. 如果是评测数据转换或指标计算，放 `benchmark`。

## 8. 当前迁移策略

短期不重构 `domain`。

短期重点是：

- 建立 `application/use_cases` 和 `application/ports`。
- 把正式业务编排从 API route 和 infrastructure coordinator 中逐步上移。
- 新 method 放到 `infrastructure/methods`，通过 application port 暴露能力。
- 保留各业务的 `infrastructure/methods/<module>/factory.py`，不再引入跨业务 facade 或 registry。

迁移应按业务功能逐步完成，不做一次性大改。
