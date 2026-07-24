# Repository Guidelines

## Project Structure & Module Organization

This branch contains the Online EBM workflow benchmark and a module-level Python backend. Backend source lives under `backend/src/ebm_backend/online_pipeline/` and follows a DDD-style split: `domain/` for stable workflow entities and serialization contracts, `application/` for business ports and use-case orchestration, `infrastructure/` for concrete method adapters, business factories, provider clients, prompt assets, and technical integrations, and `interfaces/api/` for FastAPI routes, schemas, and dependency composition. Benchmark code and datasets live in `benchmark/online_pipeline/`, organized by module such as `q2pico/`, `study_screening/`, `study_pio/`, `risk_of_bias/`, `meta_analysis/`, and `grade/`. Shared benchmark utilities are in `benchmark/online_pipeline/shared/`. Unit tests are under `tests/unit/`; maintained workflow docs are in `docs/`.

## Build, Test, and Development Commands

Create a local environment from the repository root:

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Run the API locally:

```bash
PYTHONPATH=backend/src:. uvicorn ebm_backend.online_pipeline.interfaces.api.main:app --reload
```

Run tests:

```bash
PYTHONPATH=backend/src:. pytest -q tests/unit tests/integration
PYTHONPATH=backend/src:. pytest tests/unit/infrastructure/test_llm_config.py -q
```

Build and run a smoke benchmark:

```bash
PYTHONPATH=backend/src:. python benchmark/online_pipeline/benchmark.py build --module q2pico --source builtin_smoke --dataset-name smoke_q2pico
PYTHONPATH=backend/src:. python benchmark/online_pipeline/benchmark.py run --module q2pico --dataset-name smoke_q2pico --split smoke --method gold --run-id smoke_q2pico_gold --judge-mode normalized
```

## Coding Style & Naming Conventions

Use Python 3.11, four-space indentation, type hints for public interfaces, and clear dataclass/domain object boundaries. Keep dependencies flowing through the documented layers, and inject concrete infrastructure adapters at the interface composition root. Name tests `test_*.py`, benchmark run IDs descriptively, and method packages by module/domain, for example `method_onestep_llm` or `subtask3_analysis_methods`.

## Backend Service Architecture

The backend is the primary implementation surface for the online EBM workflow. Keep architectural responsibilities explicit:

- `domain/` defines stable workflow entities, value objects, serialization-facing dataclasses, and business contracts.
- `application/` defines use cases, business orchestration, parameter passing, and ports; it coordinates workflow steps but does not implement concrete LLM, provider, retrieval, or heuristic methods.
- `infrastructure/` implements concrete method adapters, provider-specific query compilers and clients, business factories, LLM integrations, prompt assets, and other technical capabilities.
- `interfaces/api/` exposes backend capabilities over HTTP, remains a thin translation layer over application use cases, and acts as the composition root that injects concrete infrastructure adapters.

Dependency direction must remain explicit:

- `domain` must not depend on `application`, `infrastructure`, `interfaces`, `benchmark`, or `tests`;
- `application` may depend on `domain` and its own ports, but must not depend on `infrastructure`, `interfaces`, `benchmark`, or `tests`;
- `infrastructure` may depend on `domain` and external technical libraries, but must not import application use cases, interfaces, benchmark code, or tests;
- concrete infrastructure adapters should satisfy application ports structurally and do not need to inherit or import application `Protocol` types solely for conformance;
- `interfaces/api/dependencies.py` may import both application use cases and infrastructure factories because it is the backend composition root.

Do not make backend runtime behavior depend on benchmark code or test code. Do not reintroduce a cross-business method registry, resolver, module facade, or service-locator abstraction. Each application use case must receive already-constructed business port adapters.

## Backend Orchestration And Technical Pipelines

Place orchestration according to the meaning of the workflow, not merely according to the number of calls:

- `application` owns EBM business steps, coordination of multiple replaceable capabilities or sources, cross-step parameter passing, concurrency and failure policy, deterministic output ordering, and domain-rule invocation;
- `infrastructure` may coordinate the provider-specific technical operations required for one concrete adapter to fulfill its port, such as query compilation, HTTP requests, retries, rate limiting, identifier conversion, response parsing, XML cleaning, or a provider-local enrichment sequence;
- infrastructure code must not call back into an application use case to coordinate a business workflow;
- if a flow expresses an EBM stage or coordinates multiple replaceable business capabilities, put it in `application`; if it only fulfills one concrete provider adapter's technical contract, keep it in `infrastructure`.

Examples: Study Screening criteria planning plus article screening is application orchestration. PubMed-specific MeSH enrichment, PubMed query compilation, NCBI calls, PMID-to-PMCID conversion, and PMC XML cleaning may remain inside the PubMed infrastructure adapter.

## Backend Method Packaging And Factories

Organize concrete methods by business capability and isolate each implementation:

```text
infrastructure/methods/<business>/
  factory.py
  <concrete_method>/
    method.py
    prompts/
    provider-specific helpers
```

- each concrete method must have its own directory;
- prompts must live under the method that owns them, normally in a local `prompts/` directory;
- method-local helpers, schemas, and provider code must not be scattered across the business root;
- the business root may contain its factory and genuinely shared technical components used by multiple concrete methods;
- do not add an infrastructure-root coordinator that calls an application use case;
- each business uses its own factory; do not add methods to a cross-business registry;
- factories resolve only the adapters currently supported by that business;
- method names, source names, or other adapter-selection strings are handled by the interface composition root or a module-specific benchmark adapter, not by application use cases;
- product-facing APIs should prefer business concepts such as source names over internal implementation names;
- do not create empty provider packages, placeholder methods, speculative ports, or unused abstractions for capabilities that have not been requested.

New and refactored backend code must follow these rules. Existing Meta-analysis or GRADE infrastructure coordinators that have not yet been migrated are known technical debt, not precedents for new code. Align with the user before changing their behavior.

## Backend And Benchmark Relationship

The backend and benchmark serve different purposes and should remain distinct:

- The backend defines service behavior, method contracts, and workflow outputs for real EBM usage.
- The benchmark is an evaluation harness for dataset construction, prediction runs, metrics, diagnostics, and regression analysis.
- Benchmark code may call backend methods, backend serializers, or backend adapters.
- Backend code must not depend on benchmark code, benchmark datasets, or benchmark artifacts at runtime.

Treat the benchmark as an evaluation layer, not as the product contract. When benchmark annotations and real EBM workflow needs diverge, prioritize real workflow semantics unless the task explicitly requires benchmark-specific behavior. If an evaluation mapping or normalization is needed for benchmark scoring, prefer implementing it in benchmark-side adapters, evaluators, or runners rather than changing backend contracts or prompt behavior for a narrow benchmark case.

## Testing And Live LLM Policy

Tests are part of backend engineering discipline and should be organized by module and dependency level:

- Put backend unit tests under `tests/unit/<module>/` where possible.
- Put integration or live-dependency tests under `tests/integration/<module>/`.
- Unit tests must not require network access, real LLM credentials, or external mutable state.
- Integration tests may use real dependencies, but only behind explicit opt-in switches.

For LLM-backed methods:

- cover normal behavior, validation failures, and key option switches with unit tests using fake callers;
- use live LLM tests only for controlled smoke validation of important paths;
- default live tests to skipped and guard them with an explicit environment variable such as `RUN_LIVE_LLM_TESTS=1`;
- do not let ordinary `pytest` runs unexpectedly call external models.

Benchmark smoke runs are useful verification steps for changed methods, but they do not replace unit tests or integration tests.

## Backend, Benchmark, And Test Orchestration

The orchestration relationship between backend, benchmark, and tests must remain clear:

- The backend is the implementation layer.
- The benchmark is the evaluation and run-orchestration layer.
- Tests are the verification layer.

Allowed dependency and call directions:

- `interfaces/api` may construct application use cases and inject concrete adapters from module-specific infrastructure factories.
- `benchmark` may call application use cases, backend business factories, public backend method adapters, module-specific benchmark adapters, evaluators, and reporting utilities.
- `tests` may call backend code directly, and may call benchmark-side public evaluation logic when testing benchmark behavior.

Disallowed or discouraged directions:

- `backend` must not depend on `benchmark` or `tests`;
- `benchmark` must not depend on `tests`;
- tests must not become the place where product logic is first implemented.
- benchmark code must not depend on a generic backend method registry or bypass required application orchestration with an incompatible concrete-method call.

Responsibility split:

- Backend owns business behavior, service contracts, method options, and runtime semantics.
- Benchmark owns datasets, run manifests, metrics, judge pipelines, and run artifacts.
- Tests own verification of correctness, regressions, boundary conditions, and controlled live smoke checks.

If a benchmark run requires output reshaping or interpretation that is specific to the benchmark, prefer benchmark-side adaptation. Do not blur the boundary by embedding benchmark-specific evaluation assumptions into backend runtime contracts unless explicitly approved.

## Scope Alignment And Documentation Synchronization

Discussion, investigation, and implementation authorization are distinct. A question about how a future database, cache, provider, agent, storage layer, or workflow might be added is not approval to create code, ports, schemas, placeholders, or maintained documentation for that capability.

Repository-wide modification authorization is explicit: debugging, analysis, code review, artifact inspection, and test execution do not authorize implementation changes. Before changing code, prompts, schemas, routing, filters, evaluation behavior, test expectations, or maintained documentation, first describe the concrete issue and proposed change to the user and obtain explicit approval for that class of change. A broad request to investigate, debug, integrate, or make a workflow run does not waive this requirement. If a newly discovered issue blocks the approved task, stop and align rather than modifying behavior first and reporting afterward.

- Do not implement or document speculative future requirements without explicit user alignment.
- When the user asks only for an explanation or design discussion, answer and stop; do not mutate the repository.
- Before adding a new provider, persistence layer, cache, routing mechanism, or agent pattern, align on the real use case, business semantics, failure policy, and required contract.
- Prefer the smallest implementation that satisfies the current approved requirement. Add a second provider or generalized mechanism when a real second implementation is requested, not merely because it may exist later.
- When debugging reveals a separate issue, follow the repository's alignment rules: report it first unless it blocks the already-approved change.

Keep maintained documentation synchronized with approved, implemented behavior:

- update `docs/contracts/<module>.md` when stable inputs, outputs, invariants, or failure semantics change;
- update `docs/implementation/<module>.md` when real directory structure, call flow, provider behavior, or method wiring changes;
- update `docs/workflow_v3.md` when cross-module workflow semantics or handoff contracts change;
- update `docs/implementation/backend-framework.md` and `backend/README.md` when global layering, composition, or development conventions change;
- update the relevant benchmark documentation when benchmark method loading, runner behavior, datasets, metrics, or artifacts change;
- documentation must distinguish current behavior, known limitations, and approved next steps; speculative ideas should not be written as maintained architecture.

## Backend Concurrency Policy

Add concurrency only when there are at least two real, semantically independent execution units and a concrete latency need. Do not introduce a thread pool merely to prepare for a hypothetical future provider.

- concurrency must have an explicit bound;
- outputs must preserve deterministic business ordering;
- partial-failure versus whole-run failure semantics must be explicit;
- provider-specific rate limits and retry limits remain in force under concurrency;
- application owns concurrency across business capabilities or retrieval sources;
- infrastructure may use bounded concurrency only inside one adapter for technically independent provider operations that do not alter business semantics.

## Meta-analysis Method Constraints

When developing meta-analysis extraction methods in this repository, follow these constraints unless a task explicitly requires an exception:

1. Table handling: do not apply deterministic table parsing, cleaning, row/column normalization, or value extraction for study-result extraction. Raw tables should be passed to the LLM as source material, and table reading/extraction should be performed by the LLM. Narrow deterministic utilities are allowed only for post-extraction validation or calculation on already extracted structured values, not for replacing table understanding.
2. Prompt changes: do not modify prompts in a case-by-case way to fit individual benchmark examples. Prompt design must target real workflow conditions, generalization, and robustness across studies rather than patching known cases.
3. Prompt design: write prompts from the overall task design, including the stage responsibility, inputs, outputs, and decision boundary. Do not update prompts by repeatedly appending patch-style rules. Do not add special prompt changes for a specific bad case. If a bad case exposes a real issue, abstract it into a general workflow problem before changing the prompt. Keep prompts concise and avoid repeating the same concept with several different phrasings. Fields that can be assembled by engineering code, such as ids, source handles, and trace metadata, should not be generated by the model; the model should generate only fields that require semantic judgement or evidence reading.
4. Prompt engineering references: when writing or rewriting prompts, it is acceptable and encouraged to consult leading model-provider guidance such as OpenAI, Anthropic, Google, or other high-quality technical references. Use those references to improve clarity, task decomposition, input/output contracts, uncertainty handling, and structured output design. Do not copy generic prompt templates blindly; adapt the guidance to this repository's EBM extraction stage, source type, and evaluation/debug needs.
5. Debug coordination: when a new issue is discovered during debugging, do not immediately fix it without user alignment. If the new issue does not block the current approved fix, record it and continue the current fix, then report the new issue afterward. If the new issue blocks or changes the current approved fix, stop and align with the user before modifying behavior.
6. Benchmark selection for Subtask 2 development: use a filtered benchmark by default. The primary development and debug dataset is `cochrane_meta_v2-key-filter`. Use stricter filtered variants such as `cochrane_meta_v2-pairwise-candidate-filter` only for targeted audits. Do not use the unfiltered `cochrane_meta_v2` as the primary dataset for method iteration, because it mixes true method failures with cases unsupported by the current article inputs. Reserve the unfiltered dataset for robustness audits only.
7. Agent design references: when designing or revising EBM extraction agents, it is acceptable and encouraged to consult leading technical blogs, technical reports, system design documents, and high-quality research papers. The purpose is not to copy techniques mechanically, but to extract useful design principles, workflow patterns, reasoning paradigms, context-management ideas, and evaluation practices that fit this repository's task.
8. EBM methodology references: meta-analysis extraction agents are part of an evidence-based medicine workflow. When designing task boundaries, data structures, extraction stages, uncertainty handling, verification, and downstream handoff, consult official or authoritative EBM methodology where relevant, such as Cochrane Handbook guidance, PRISMA reporting principles, GRADE guidance, and standard meta-analysis data extraction practice.
9. Technology adoption: when researching or introducing a new technique, do not adopt it blindly. First explain the practical value, what system problem it solves, what improvement it should bring, and why it fits the real EBM extraction scenario. Techniques should serve the workflow and business goal, not be added for novelty.
10. Agent complexity control: prefer the simplest workflow that solves the current EBM extraction problem. Add agentic planning, routing, reflection, multi-agent patterns, or dynamic tool use only when a concrete failure mode requires it. Every added agent mechanism must state what problem it solves, what metric or debug signal should improve, and what latency, cost, or debuggability tradeoff it introduces.
11. Context budget and context hygiene: do not use append-only context as the default design for extraction agents. Each LLM call should receive only the source material, candidate state, materials, and prior decisions required for that stage. Avoid prompts that combine all sources, all candidates, all materials, and all prior reasoning. If broad context is needed, use bounded source bundles, source-local caches, structured summaries, or need-scoped recovery instead of full-history prompts.
12. Context freshness and cache validity: cached source summaries, source briefs, material extractions, and candidate states must be keyed by enough information to detect stale context, such as task id, source id, source hash, prompt version, data type, and relevant method version. Do not reuse cached semantic decisions after the candidate setting, source text, prompt contract, or required fields change. When cache or source caps affect behavior, record this in debug artifacts.
13. Runtime and cost control: agent workflows must define explicit limits for LLM calls, source reads, recovery rounds, retry attempts, candidate batch size, and parallelism. Parallelism is allowed only for semantically independent units, such as sources or candidates, and should preserve deterministic output ordering. All LLM calls should pass through a clear concurrency limit. Do not introduce unbounded recovery loops or retry storms.
14. Tool and calculation boundaries: tools should have narrow, documented contracts. LLMs may read evidence, classify semantic meaning, choose compatible materials, and plan which deterministic tool to call. Deterministic tools should perform arithmetic, validation, assembly, caching, and trace construction. LLMs must not perform final arithmetic or silently override tool validation.
15. Traceability and observability: every non-trivial agent stage should produce inspectable debug artifacts containing stage input summaries, model outputs, tool calls, warnings, timing, retry counts, source ids, and final state transitions. Prediction rows should stay compact; full prompts, raw sources, and long traces belong in debug or run artifacts. A method change is not ready for benchmark iteration if its failures cannot be classified from artifacts.
16. Evaluation before optimization: do not optimize prompts, routing, batching, cache strategy, or agent structure based only on anecdotal bad cases. First define the expected improvement and inspect metrics or debug categories that can falsify the change, such as recall, field binding, denominator accuracy, context truncation, LLM error rate, runtime, and per-stage failure taxonomy. If a change improves speed but reduces auditability or source coverage, record the tradeoff explicitly before adopting it.
17. Communication of domain terminology: when discussing EBM concepts, psychiatric scales, statistical measures, table labels, or other domain-specific terms with the user, do not assume the term is self-explanatory. Add a short Chinese explanation, translation, or note inline when it materially helps understanding, especially during debugging, case analysis, and design discussion.
18. Study-evidence candidate objective: the workflow/review setting passed into a method can be broader than the article-local result setting. Ambiguous outputs are acceptable when an article contains multiple plausible source-local candidates. The primary recall goal is that candidates preserve the relevant article-local result and all directly reported or deterministically derivable numeric evidence supported by the article. Do not force a single final row merely to satisfy a benchmark target when the input setting is genuinely broad.
19. Alignment before behavior changes: during Subtask 2 method design, debugging, prompt review, and case analysis, do not change code, prompts, schemas, routing, filters, or evaluation behavior unless that exact class of change has already been aligned with the user. If a new issue is found while investigating an approved change, report the issue and proposed fix first. Only perform read-only analysis, artifact inspection, and already-approved commands until the user agrees to the behavior change.
20. Candidate and supporting-evidence boundary: an article-local result candidate must be discovered from one current raw table source, including its caption, headers, rows, and footnotes. Candidate discovery must not silently merge another table or article prose into that candidate. Separate, need-scoped calls may extract typed supporting materials from other selected tables or relevant article sections, such as arm sample sizes, participant flow, attrition, scale definitions, or explicitly reported uncertainty statistics. Cross-source materials must retain their own source and semantic scope and may contribute to a final result only through deterministic compatibility and provenance gates. Article prose must not be presented as if it came from the candidate table.
21. Intermediate evidence and calculations: follow Cochrane's maximal-use-of-data principle by retaining potentially useful typed numeric materials, including counts, percentages, sample sizes, means, SDs, SEs, confidence intervals, test statistics, P values, and effect estimates when reported. LLMs classify the material type, statistical scope, result frame, arm, outcome, timepoint, and source; they do not choose arbitrary formulas or perform final arithmetic. Only versioned deterministic calculators with documented assumptions may derive required fields. A randomized or baseline sample size is not an analyzed denominator unless separate evidence establishes compatible outcome coverage and no contradictory attrition or exclusion.

## Real-Workflow Priority

When benchmark datasets and real EBM workflow needs diverge, prioritize the real workflow design unless the task explicitly asks for benchmark fitting. Benchmarks are used for evaluation and debugging, but service behavior, prompt design, output contracts, and planning logic should be grounded first in official or authoritative EBM methodology and realistic downstream use in review production. Do not overfit prompts, heuristics, or outcome planning behavior to benchmark annotation quirks unless the user explicitly approves that tradeoff.

## Testing Guidelines

Use `pytest`. Add focused unit tests for configuration, schemas, domain serialization, application use-case delegation, business factories, provider clients, and method or benchmark adapters. Unit tests must use fakes for external providers. Keep live provider and live LLM tests explicitly opt-in. For new or changed benchmark methods, also run the relevant benchmark smoke split and confirm a run directory plus metrics are written. Keep backend unit tests separate from benchmark evaluation code.

## Commit & Pull Request Guidelines

Recent history uses short, descriptive commits such as `Refactor backend and benchmark structure` and `experiment: analysis setting and meta-extract`. Prefer imperative, scoped messages (`backend: add factory test`, `benchmark: update q2pico metrics`). PRs should describe the touched module, list test or benchmark commands run, note dataset or config changes, and link related issues or workflow docs when relevant.

## Security & Configuration Tips

LLM credentials belong in `llm.local.json`, copied from `llm.local.example.json`; this file is git-ignored. Do not put secrets in `.env`, benchmark artifacts, or committed run outputs. Use `.env` only for non-secret runtime switches.
