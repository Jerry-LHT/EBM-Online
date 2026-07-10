# Repository Guidelines

## Project Structure & Module Organization

This branch contains the Online EBM workflow benchmark and a module-level Python backend. Backend source lives under `backend/src/ebm_backend/online_pipeline/` and follows a DDD-style split: `domain/` for dataclasses and serialization contracts, `application/` for ports and runners, `infrastructure/` for method implementations, registries, and LLM clients, and `interfaces/api/` for FastAPI routes and schemas. Benchmark code and datasets live in `benchmark/online_pipeline/`, organized by module such as `q2pico/`, `study_screening/`, `study_pio/`, `risk_of_bias/`, `meta_analysis/`, and `grade/`. Shared benchmark utilities are in `benchmark/online_pipeline/shared/`. Unit tests are under `tests/unit/`; maintained workflow docs are in `docs/`.

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
PYTHONPATH=backend/src:. pytest -q
PYTHONPATH=backend/src:. pytest tests/unit/infrastructure/test_llm_config.py -q
```

Build and run a smoke benchmark:

```bash
PYTHONPATH=backend/src:. python benchmark/online_pipeline/benchmark.py build --module q2pico --source builtin_smoke --dataset-name smoke_q2pico
PYTHONPATH=backend/src:. python benchmark/online_pipeline/benchmark.py run --module q2pico --dataset-name smoke_q2pico --split smoke --method gold --run-id smoke_q2pico_gold --judge-mode normalized
```

## Coding Style & Naming Conventions

Use Python 3.10-3.12, four-space indentation, type hints for public interfaces, and clear dataclass/domain object boundaries. Keep dependencies flowing through the documented layers: `interfaces -> application -> domain`, with concrete adapters in `infrastructure`. Name tests `test_*.py`, benchmark run IDs descriptively, and method packages by module/domain, for example `method_onestep_llm` or `subtask3_analysis_methods`.

## Backend Service Architecture

The backend is the primary implementation surface for the online EBM workflow. Keep architectural responsibilities explicit:

- `domain/` defines stable workflow entities, value objects, serialization-facing dataclasses, and business contracts.
- `application/` defines use cases, orchestration, parameter passing, and ports; it coordinates workflow steps but does not implement concrete LLM or heuristic methods.
- `infrastructure/` implements concrete methods, registries, resolvers, LLM clients, and adapters that satisfy application-layer ports.
- `interfaces/api/` exposes backend capabilities over HTTP and should remain a thin translation layer over application use cases.

Dependency direction must remain one-way: `interfaces -> application -> domain`, with concrete implementations injected from `infrastructure`. Do not make backend runtime behavior depend on benchmark code or test code.

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

- `interfaces/api` may call `application`, which resolves concrete implementations from `infrastructure`.
- `benchmark` may call backend methods, benchmark adapters, evaluators, and reporting utilities.
- `tests` may call backend code directly, and may call benchmark-side public evaluation logic when testing benchmark behavior.

Disallowed or discouraged directions:

- `backend` must not depend on `benchmark` or `tests`;
- `benchmark` must not depend on `tests`;
- tests must not become the place where product logic is first implemented.

Responsibility split:

- Backend owns business behavior, service contracts, method options, and runtime semantics.
- Benchmark owns datasets, run manifests, metrics, judge pipelines, and run artifacts.
- Tests own verification of correctness, regressions, boundary conditions, and controlled live smoke checks.

If a benchmark run requires output reshaping or interpretation that is specific to the benchmark, prefer benchmark-side adaptation. Do not blur the boundary by embedding benchmark-specific evaluation assumptions into backend runtime contracts unless explicitly approved.

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
18. Subtask 2 candidate objective: for meta-analysis Subtask 2, the workflow/review setting passed into a method can be broader than the article-local result setting. Ambiguous outputs are acceptable when the article contains multiple plausible source-local candidates under the broader setting. The primary candidate-recall goal is that the returned candidate/result items include the gold-relevant article-local result and its numeric values when those values are supported by the provided article evidence. Do not force a single final row merely to satisfy a benchmark target when the input setting is genuinely broad.
19. Alignment before behavior changes: during Subtask 2 method design, debugging, prompt review, and case analysis, do not change code, prompts, schemas, routing, filters, or evaluation behavior unless that exact class of change has already been aligned with the user. If a new issue is found while investigating an approved change, report the issue and proposed fix first. Only perform read-only analysis, artifact inspection, and already-approved commands until the user agrees to the behavior change.

## Real-Workflow Priority

When benchmark datasets and real EBM workflow needs diverge, prioritize the real workflow design unless the task explicitly asks for benchmark fitting. Benchmarks are used for evaluation and debugging, but service behavior, prompt design, output contracts, and planning logic should be grounded first in official or authoritative EBM methodology and realistic downstream use in review production. Do not overfit prompts, heuristics, or outcome planning behavior to benchmark annotation quirks unless the user explicitly approves that tradeoff.

## Testing Guidelines

Use `pytest`. Add focused unit tests for config, schema, resolver, serialization, and method adapter changes. For new or changed benchmark methods, also run the relevant benchmark smoke split and confirm a run directory plus metrics are written. Keep backend unit tests separate from benchmark evaluation code.

## Commit & Pull Request Guidelines

Recent history uses short, descriptive commits such as `Refactor backend and benchmark structure` and `experiment: analysis setting and meta-extract`. Prefer imperative, scoped messages (`backend: add resolver test`, `benchmark: update q2pico metrics`). PRs should describe the touched module, list test or benchmark commands run, note dataset or config changes, and link related issues or workflow docs when relevant.

## Security & Configuration Tips

LLM credentials belong in `llm.local.json`, copied from `llm.local.example.json`; this file is git-ignored. Do not put secrets in `.env`, benchmark artifacts, or committed run outputs. Use `.env` only for non-secret runtime switches.
