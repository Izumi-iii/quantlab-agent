"""Integration tests for the three demo scenarios."""

from __future__ import annotations

from pathlib import Path

from quantlab_agent.agent.demo import default_demo_controller


def _run_dir(runs_dir: Path, session_id: str) -> Path:
    return runs_dir / session_id / "runs"


SESSION = "00000000-0000-4000-8000-000000000099"


def test_two_asset_scenario_succeeds(tmp_path: Path) -> None:
    demo = default_demo_controller(tmp_path)
    run = demo.run_two_asset(session_id=SESSION)

    assert run.status.value == "succeeded"
    assert run.analysis_id is not None
    assert run.metrics_id is not None
    assert run.report_id is not None
    assert len(run.chart_ids) == 2

    run_dir = _run_dir(tmp_path, SESSION) / run.run_id
    assert (run_dir / "manifest.json").exists()
    assert (run_dir / "tool_calls.jsonl").exists()
    reports_dir = run_dir / "reports" / run.report_id
    assert (reports_dir / "report.md").exists()


def test_single_asset_scenario_succeeds(tmp_path: Path) -> None:
    demo = default_demo_controller(tmp_path)
    run = demo.run_single_asset(session_id=SESSION)

    assert run.status.value == "succeeded"
    assert run.analysis_id is not None
    assert run.metrics_id is not None
    assert run.report_id is not None
    assert len(run.chart_ids) == 2


def test_duplicate_date_scenario_fails(tmp_path: Path) -> None:
    demo = default_demo_controller(tmp_path)
    run = demo.run_duplicate_date_failure(session_id=SESSION)

    assert run.status.value == "failed"
    assert run.failure is not None
    assert run.failure["code"] == "DUPLICATE_DATE"

    # Confirm no report was generated.
    run_dir = _run_dir(tmp_path, SESSION) / run.run_id
    for child in run_dir.rglob("report.md"):
        raise AssertionError(f"Unexpected report file: {child}")


def test_run_all_produces_three_runs(tmp_path: Path) -> None:
    demo = default_demo_controller(tmp_path)
    runs = demo.run_all(session_id=SESSION)
    assert len(runs) == 3
    statuses = sorted(r.status.value for r in runs)
    assert statuses == ["failed", "succeeded", "succeeded"]
