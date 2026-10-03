# Evaluation cases and runner

This directory holds the E01–E24 evaluation cases from
[`Docs/PROJECT_PLAN.md §13.3`](../Docs/PROJECT_PLAN.md#133-agent-评估任务清单)
and the runner that executes every case whose `status` is `ready`.

## Status of the cases

| Status     | Meaning                                                    | Count |
|------------|------------------------------------------------------------|------:|
| `ready`    | Executed by the runner against the deterministic pipeline. | 16    |
| `deferred` | Requires a real model to demonstrate (M3). Listed but skipped. |  8    |

The 8 deferred cases are E11, E12, E16, E17, E20, E21, E23, E24. Each carries
a `deferred_reason` so the limitation is explicit in the output table.

## Running the evaluation

```powershell
.\.venv\Scripts\python.exe -m evaluation.runner
```

The runner exits with `1` if any `ready` case fails, `0` otherwise. The
output is a Markdown summary table written to stdout, suitable for
pasting into a PR description.

## Files

| File              | Purpose                                                  |
|-------------------|----------------------------------------------------------|
| `cases.jsonl`     | One JSON object per case: `case_id`, `mode`, `expected`. |
| `fixtures.py`     | Small CSV fixtures for cases that need bad inputs.       |
| `runner.py`       | Loads `cases.jsonl`, dispatches by `mode`, asserts results. |
| `__init__.py`     | Package marker.                                           |

## Case `mode` values

- `demo` — invokes `DemoController.run_*` (E01, E02, E06).
- `custom` — constructs CSVs and runs the same tool pipeline with
  user-provided dates and metrics (E03, E04, E10, E13, E15).
- `import_only` — calls `DatasetService.import_csv` on a bad fixture
  and asserts the quality-report error code (E05, E07, E08, E09, E14).
- `registry_unit` — drives `ToolRegistry` directly to exercise protocol
  errors (E18, E19, E22).
- `deferred` — skipped; listed in the output for transparency.

## Why demo ≠ real model

A run that the demo passes does not prove that any real model will
choose the right tools. The runner's `passed` column reflects only
deterministic behaviour: the tool pipeline produces the documented
output for each fixture and parameter set.

Once a real model provider is wired up (M3), each `deferred` case
becomes executable and the same runner can be reused: only the
`mode` field changes.
