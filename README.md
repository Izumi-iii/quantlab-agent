# quantlab-agent
A tool-calling agent for reproducible financial data analysis.

## Current status

The local deterministic pipeline is now runnable:

- CSV validation, date alignment, period return, annualized volatility, and maximum drawdown.
- Local run storage with session/run isolation and JSONL tool-call records.
- A controlled Tool Registry with schema validation, reference checks, and budget checks.
- Static chart generation, Markdown report generation, and deterministic demo scenarios.

The real model-driven Agent loop and UI are not implemented yet. Demo mode is deterministic and does not call a model API.

## Development setup

Requires Python 3.12 or newer. The current development environment is Python 3.14.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

## Run a local demo

```powershell
.\.venv\Scripts\python.exe -m quantlab_agent.cli demo --scenario all --runs-dir runs
```

The command writes run manifests, tool-call logs, charts, and reports under `runs/`.

## Documentation

- [Project plan](Docs/PROJECT_PLAN.md)
- [Architecture](Docs/architecture.md)
- [Learning guide](Docs/learning-guide.md)
