# quantlab-agent

A tool-calling agent for reproducible financial data analysis — local-first,
deterministic core, controlled tools, and a deterministic demo mode that runs
without any model API.

## Current status

The local pipeline is runnable end-to-end without a model API:

- **M1 — Deterministic core**: CSV validation, date alignment, period return,
  annualized volatility, maximum drawdown. Pure functions, hand-checkable
  formulas, immutable snapshots.
- **M2 — Controlled tools and run records**: session / run / analysis
  reference isolation, Tool Registry with schema and reference checks, JSONL
  tool-call records, atomic file writes, run state machine, static chart
  generation (matplotlib), Markdown report generation, and a deterministic
  demo controller that exercises the same Tool Registry as the future
  real-model path.

Not implemented yet: real model adapter (M3), Streamlit UI (M4), E01–E24
agent evaluation (M5). Demo mode is deterministic and never calls a model
API; it proves the tool chain works but does not prove that any real model
will choose the right tools.

## Quick start

Requires Python 3.12 or newer. Verified on Python 3.14.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

## Try the demo

### CLI

```powershell
.\.venv\Scripts\python.exe -m quantlab_agent.cli demo --scenario all --runs-dir runs
```

This runs three preset scenarios (two-asset comparison, single-asset
inspection, duplicate-date failure) through the same `ToolRegistry` a real
model would use, and writes under `runs/`:

```text
runs/<session_id>/
├── datasets/<dataset_id>/{manifest.json, normalized.csv}
└── runs/<run_id>/
    ├── manifest.json
    ├── tool_calls.jsonl
    ├── reports/<report_id>/report.md
    └── charts/<chart_id>/{normalized_prices.png, normalized_prices.json, ...}
```

Scenarios:

| Flag                | What happens                                                      |
|---------------------|-------------------------------------------------------------------|
| `all`               | Runs all three scenarios.                                         |
| `two-asset`         | DEMO_A + DEMO_B, end-to-end → succeeded.                          |
| `single-asset`      | DEMO_A only → succeeded.                                          |
| `duplicate-date`   | INVALID_DUPLICATE.csv → run ends in FAILED, no report written.    |

### Local web UI

```powershell
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Opens a browser at `http://localhost:8501`. The UI is the same deterministic
pipeline as the CLI demo, but lets you upload your own CSV files, pick a
date range, choose metrics, and download the generated `report.md`. It uses
the same `ToolRegistry` and run state machine; the only difference is the
input source.

**Note**: cancelling in the UI ("Reset UI" button) does not stop an
already-running background analysis. The cooperative cancellation rule
(from `PROJECT_PLAN §3.2`) means a click only resets your view; the run
keeps writing to its own `runs/<session>/runs/<run_id>/` directory.

## What this project deliberately does NOT do

- Auto trading, stock recommendations, future-return prediction.
- Arbitrary Python execution from a model.
- Multi-agent debate, full RAG, online data ingestion, factor mining.
- Logins, payments, multi-user persistence.

See `Docs/PROJECT_PLAN.md §3.4` for the full non-goals list.

## Repository layout

```text
quantlab-agent/
├── pyproject.toml              # build + dev deps + CLI entry point
├── README.md
├── app.py                      # Streamlit UI entry point
├── Docs/
│   ├── PROJECT_PLAN.md         # milestones, status, decisions
│   ├── architecture.md         # design document
│   ├── architecture-walkthrough.md   # teaching walk-through
│   └── learning-guide.md       # reader-oriented tour of the code
├── data/examples/              # synthetic CSVs used by tests and demo
├── src/quantlab_agent/
│   ├── domain/                 # immutable Pydantic contracts, errors, pure math
│   ├── ports/                  # Protocol interfaces (stores, tool handler)
│   ├── adapters/               # concrete implementations (local files, matplotlib)
│   ├── application/            # services (Dataset, Analysis, Run, Chart, Report)
│   ├── agent/                  # ToolRegistry, 5 tool handlers, demo controller
│   ├── config.py               # env-driven configuration
│   └── cli.py                  # `quantlab-agent demo` entry point
└── tests/
    ├── unit/                   # domain + application + adapter + agent unit tests
    └── integration/            # demo flow + tool pipeline + UI smoke tests
```

## Run the tests

```powershell
# All tests
.\.venv\Scripts\python.exe -m pytest

# Just unit tests
.\.venv\Scripts\python.exe -m pytest tests/unit

# Just integration tests
.\.venv\Scripts\python.exe -m pytest tests/integration

# Lint and format
.\.venv\Scripts\ruff.exe check src tests
.\.venv\Scripts\ruff.exe format --check src tests
```

## Documentation map

| Document | Purpose |
|---|---|
| `Docs/PROJECT_PLAN.md` | Milestones, status, decisions, hand-off log. The single source of truth for what is and isn't done. |
| `Docs/architecture.md` | Design document — target architecture, ADRs, component responsibilities. |
| `Docs/architecture-walkthrough.md` | Teaching walk-through — follow one demo command from CLI to report on disk. |
| `Docs/learning-guide.md` | Reader-oriented tour: what each module does, why it exists, and how to verify it. |

## What is intentionally out of scope

- **No model API key is required to run the project.** Adding one becomes
  possible only when you decide which provider, model, and cost ceiling to
  use; see `PROJECT_PLAN.md §17.2`.
- **The demo never claims to be a real Agent.** It exercises the same Tool
  Registry but cannot prove that any real model will choose the right tools.
- **Synthetic data only.** `data/examples/` files are explicitly labelled
  synthetic and are not investment advice.

## License

Personal learning project. See commit history for authorship.
