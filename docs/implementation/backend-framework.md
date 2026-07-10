# 后端框架实现设计

本文档定义 Online EBM 独立后端的实现框架边界。

当前目标不是重写全部后端，而是明确后续开发应该落在哪一层，避免业务编排、method 实现、API 入参和 benchmark 适配互相污染。

本文档描述的是当前后端的目标分层和已完成收口的主路径。到目前为止，`q2pico`、`search_retrieval` 和 `study_screening` 已经按这里的方式完成专用 use case + interface 装配；其他模块仍允许暂时保留 facade / resolver 兼容层。

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

它应该从当前偏薄的 module dispatcher，演进为独立后端的 use case 编排层。对于已经整理过的模块，例如 `q2pico`、`search_retrieval` 和 `study_screening`，application 已经直接依赖业务 port，不再依赖通用 method resolver。

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

后续按 use case 和 ports 组织。当前已经建立第一阶段结构：

```text
application/
  use_cases/
    module_use_case_facade.py
    run_q2pico.py
    run_search_retrieval.py
    run_study_screening.py
  ports/
    resolver.py
    q2pico.py
    search_retrieval.py
    evidence_review.py
    synthesis.py
```

其中：

- `ports/resolver.py` 只给尚未完成专用 use case 装配的模块保留。
- `ports/q2pico.py`、`search_retrieval.py`、`evidence_review.py`、`synthesis.py` 按业务职责拆分 module ports。
- `use_cases/run_*.py` 只保留当前确实存在 application 编排的模块。
- `use_cases/module_use_case_facade.py` 只作为仍走 registry 装配模块的 facade，不再承担全部模块入口。

后续可以继续扩展为：

```text
application/
  use_cases/
    run_workflow.py
  ports/
    repositories.py
    retrieval.py
    jobs.py
```

旧的 `application/module_runner.py` 和 `application/screening_criteria.py` 兼容导入入口已经移除。新代码应直接从 `application/use_cases/` 导入 use case。

### 3.3 业务编排位置

完整 workflow 编排应放在 `application`，例如：

```text
run_workflow
  -> run_q2pico
  -> run_search_retrieval
  -> run_study_screening
  -> run_study_pio_extraction
  -> run_risk_of_bias
  -> run_meta_analysis
  -> run_grade_assessment
```

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

### 4.1 Method 位置

Method 应作为 application port 的实现，而不是业务边界本身。目录命名优先表达业务能力或提供方，不强制加 `method_` 前缀。

新 method 默认放在：

```text
infrastructure/
  methods/
    q2pico/
      method.py
      factory.py
    search_retrieval/
      pubmed_pmc/
      mesh_mapping/
      textword_expansion/
      factory.py
    study_screening/
      method.py
      factory.py
      criteria_planner.py
      article_screener.py
      section_selector.py
    study_pio/
      <method_name>/
    risk_of_bias/
      <method_name>/
    meta_analysis/
    grade/
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

### 4.2 与现有 methods 的关系

当前 `infrastructure/methods/` 同时承载正式 method 实现和 method registry 兼容适配。

它可以暂时保留，但定位应明确：

- 可以继续服务已有 benchmark 和实验方法。
- method 不是业务边界本身，正式业务编排仍在 application。
- 对于 `q2pico`、`search_retrieval` 和 `study_screening`，正式后端 API 虽然暂时保留 `method_name` 入参，但实际只是在 interface 装配层选择 concrete adapter，不再让 application 依赖 registry。
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

当前的实践是：`interfaces/api/dependencies.py` 作为装配点，为 `q2pico`、`search_retrieval` 和 `study_screening` 构造 use case + concrete infrastructure adapter；route handler 只做参数解析和结果转换。

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

正式 API 不应要求调用方传 `method_name`。模型、prompt version、运行策略等应由后端配置、任务策略或内部 routing 决定。

当前分支仍保留 module-level 开发 API，因此 `q2pico`、`search_retrieval` 和 `study_screening` 的请求体里暂时还保留 `method_name`。它当前只是开发期的 adapter 选择开关，不代表 application 层依赖 registry。

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
- 保留现有 `infrastructure/methods` 和 `application/use_cases/module_use_case_facade.py`，但不把 facade 继续扩展为正式后端主业务抽象。

迁移应按业务功能逐步完成，不做一次性大改。
