"""Tests for the evaluation runner.

These run the actual ``cases.jsonl`` definitions through the runner
and assert the aggregated pass/fail counts. They also cover the
markdown rendering.
"""

from __future__ import annotations

import subprocess
import sys

from evaluation.runner import (
    CASES_PATH,
    CaseResult,
    load_cases,
    render_markdown,
    run_all,
    run_case,
)


def test_load_cases_returns_28_entries() -> None:
    cases = load_cases()
    assert len(cases) == 28
    assert {c["case_id"] for c in cases} == {f"E{i:02d}" for i in range(1, 29)}


def test_load_cases_status_split() -> None:
    cases = load_cases()
    ready = [c for c in cases if c["status"] == "ready"]
    deferred = [c for c in cases if c["status"] == "deferred"]
    # 24 cases from PROJECT_PLAN §13.3 + 4 planner cases added in M6;
    # 8 require a real model.
    assert len(ready) == 20
    assert len(deferred) == 8


def test_run_all_only_executes_ready_cases() -> None:
    results = run_all()
    by_status = {r.status for r in results}
    # We must have both passed and skipped (deferred). No case should be
    # unexpectedly failed at the test level — failures during
    # development should be caught and fixed, not silently accepted.
    assert "skipped" in by_status
    assert "passed" in by_status
    failed = [r for r in results if r.status == "failed"]
    assert failed == [], (
        f"Evaluation regressions: {[r.case_id + ': ' + (r.failure_reason or '') for r in failed]}"
    )


def test_run_case_handles_unknown_mode() -> None:
    case = {"case_id": "X", "title": "?", "mode": "nope", "status": "ready", "expected": None}
    result = run_case(case)
    assert result.status == "failed"
    assert "Unknown mode" in (result.failure_reason or "")


def test_run_case_skips_deferred() -> None:
    case = {
        "case_id": "X",
        "title": "?",
        "mode": "demo",
        "status": "deferred",
        "deferred_reason": "needs model",
        "expected": None,
    }
    result = run_case(case)
    assert result.status == "skipped"


def test_render_markdown_includes_totals() -> None:
    results = [
        CaseResult(case_id="E01", title="t", mode="demo", status="passed", expected=None),
        CaseResult(case_id="E02", title="t", mode="demo", status="skipped", expected=None),
        CaseResult(
            case_id="E03",
            title="t",
            mode="demo",
            status="failed",
            expected=None,
            failure_reason="boom",
        ),
    ]
    md = render_markdown(results)
    assert "**Totals**" in md
    assert "1 passed" in md
    assert "1 failed" in md
    assert "1 skipped" in md


def test_runner_cli_exit_code_zero_when_all_pass() -> None:
    """Run the runner as a subprocess; it should exit 0 with no failures.

    The runner subprocess invokes real CSVs and the demo controller, so
    we run it only when ``evaluation.runner`` is importable.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "evaluation.runner"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"Runner exited with {proc.returncode}\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
    )
    assert "20 passed" in proc.stdout
    assert "8 skipped" in proc.stdout


def test_cases_file_exists() -> None:
    """Guard against the JSONL file being moved or deleted."""
    assert CASES_PATH.exists()
