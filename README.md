# Online Pipeline Benchmark v1

This branch is scoped to the Online EBM workflow benchmark. It focuses on the online modules defined in `docs/workflow_v3.md`:

1. Q2PICO
2. Search & Article Retrieval
3. Study Screening
4. Study-level PIO Characteristics Extraction
5. Risk of Bias Assessment
6. Meta Analysis
7. Four-domain GRADE Assessment

Offline index construction, frontend demos, historical Phase 5/6 docs, and large runtime logs are not part of this branch's maintained path.

## Setup

Use a project-local virtual environment. Do not run this branch from a shared
Anaconda/base environment, because benchmark builders depend on binary packages
such as `numpy`, `pandas`, and `pyarrow` that must be installed together.

Python 3.11 is the repository runtime baseline. The current environment and full
backend test suite are verified with Python 3.11.14. Do not use Python 3.13+ for
this branch; it is outside the maintained runtime contract.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Quick environment check:

```bash
python - <<'PY'
import datasets, fastapi, numpy, pandas, pyarrow, pydantic
print("ok", numpy.__version__, pandas.__version__, pyarrow.__version__)
PY
```

## LLM Config

LLM credentials are configured with local JSON, not `.env`.

```bash
cp llm.local.example.json llm.local.json
```

Edit `llm.local.json`:

```json
{
  "api_key": "sk-...",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-5.4-mini",
  "api_mode": "responses",
  "timeout_seconds": 180,
  "temperature": 0
}
```

`llm.local.json` is ignored by git. Keep `.env` for non-secret runtime switches only, such as:

```bash
cp .env.example .env
```

The default config path is `llm.local.json`; override it with `LLM_CONFIG_PATH` or CLI flags such as `--llm-config`.

## Benchmark CLI

Build a smoke dataset:

```bash
PYTHONPATH=backend/src:. python -m benchmark.online_pipeline.benchmark build \
  --module q2pico \
  --source builtin_smoke \
  --dataset-name smoke_q2pico
```

Run a benchmark:

```bash
PYTHONPATH=backend/src:. python -m benchmark.online_pipeline.benchmark run \
  --module q2pico \
  --dataset-name smoke_q2pico \
  --split smoke \
  --method gold \
  --run-id smoke_q2pico_gold \
  --judge-mode normalized
```

LLM judge runs use `llm.local.json` by default:

```bash
PYTHONPATH=backend/src:. python -m benchmark.online_pipeline.benchmark run \
  --module q2pico \
  --dataset-name smoke_q2pico \
  --split smoke \
  --method gold \
  --run-id smoke_q2pico_llm_judge \
  --judge-mode llm \
  --llm-config llm.local.json
```

## Tests

Run the complete backend verification suite:

```bash
PYTHONPATH=backend/src:. pytest -q tests/unit tests/integration
```

The maintained test baseline targets Python 3.11. Opt-in live dependency tests
remain skipped unless their explicit switches are enabled.

Focused config checks:

```bash
PYTHONPATH=backend/src:. pytest tests/unit/infrastructure/test_llm_config.py -q
```

Module and benchmark tests can be run selectively depending on the area being changed.

## API Boundary

This branch exposes both module-level HTTP APIs and `POST /workflow` for one
complete evidence-chain run. Subtask-level HTTP endpoints are not exposed.

The workflow response retains every completed business artifact when a later
stage fails. Retrieved `CleanedArticle` objects and full text remain internal
evidence inputs; the response contains only a retrieval summary and study IDs,
not raw article content or article metadata.

Current module API status:

- `q2pico` has a concrete backend implementation with a dedicated application use
  case and interface-side adapter wiring.
- `search-retrieval` has a concrete backend implementation with dedicated
  application orchestration for query planning plus infrastructure methods for
  retrieval, MeSH mapping, and free-text expansion.
- `study-screening` has a concrete backend implementation with criteria planning,
  criterion-wise article judgment, and binary include/exclude aggregation.
- `study-pio-extraction`, `risk-of-bias`, `meta-analysis`, and `grade-assessment`
  have concrete method implementations in this branch.

Benchmarks do not call these HTTP routes. They load module/subtask/domain methods
directly from Python.

Shared runtime parameters such as `max_results` and module constraints are carried
through `ebm_backend.online_pipeline.domain.module_config.ModuleRunConfig`.

For the current backend layering and the implementation status of `q2pico`,
`search-retrieval`, and `study-screening`, see:

- `docs/implementation/backend-framework.md`
- `docs/implementation/q2pico.md`
- `docs/implementation/search-retrieval.md`
- `docs/implementation/study-screening.md`

## Maintained Docs

- `docs/workflow_v3.md` is the workflow specification.
- `docs/README.md` is the docs entrypoint.

## Branch Scope

This branch intentionally does not keep the legacy frontend, offline index construction,
shared infrastructure package, historical docs, runtime logs, or mock module adapters.
LLM configuration is owned by `ebm_backend.online_pipeline.infrastructure.llm`.
