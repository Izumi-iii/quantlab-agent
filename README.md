# quantlab-agent
A tool-calling agent for reproducible financial data analysis.

## Current status

Milestone M1 is complete: the repository contains the deterministic core for CSV validation, date alignment, period return, annualized volatility, and maximum drawdown. The Agent, persistence, charts, reports, and UI are not implemented yet.

## Development setup

Requires Python 3.12 or newer. The current development environment is Python 3.14.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
```

## Documentation

- [Project plan](Docs/PROJECT_PLAN.md)
- [Architecture](Docs/architecture.md)
- [Learning guide](Docs/learning-guide.md)
