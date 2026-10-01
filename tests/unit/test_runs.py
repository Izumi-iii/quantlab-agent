"""Unit tests for RunService."""

from __future__ import annotations

from pathlib import Path

import pytest

from quantlab_agent.adapters.local_stores import LocalRunStore
from quantlab_agent.application.runs import RunService
from quantlab_agent.domain.errors import ErrorCode, QuantLabError
from quantlab_agent.domain.models import (
    RunBudget,
    RunMode,
    RunStatus,
)
from quantlab_agent.domain.policies import RunBudgetPolicy

SESSION = "00000000-0000-4000-8000-000000000001"


def _tiny_budget() -> RunBudget:
    p = RunBudgetPolicy(max_tool_executions=2)
    return RunBudget(
        max_model_interactions=p.max_model_interactions,
        max_tool_executions=p.max_tool_executions,
        max_same_validation_retry=p.max_same_validation_retry,
        max_retryable_network_errors=p.max_retryable_network_errors,
        per_request_timeout_seconds=p.per_request_timeout_seconds,
        total_deadline_seconds=p.total_deadline_seconds,
    )


def _service(tmp_path: Path) -> RunService:
    return RunService(LocalRunStore(tmp_path), default_budget=_tiny_budget())


def test_create_run_starts_in_running(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    run = svc.create_run(
        session_id=SESSION,
        mode=RunMode.DEMO,
        user_request="hi",
    )
    assert run.status is RunStatus.RUNNING
    assert run.session_id == SESSION


def test_assert_can_accept_tool_call_ok(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    run = svc.create_run(session_id=SESSION, mode=RunMode.DEMO, user_request="hi")
    svc.assert_can_accept_tool_call(run.run_id, SESSION)  # no raise


def test_assert_can_accept_after_terminal_raises_stale(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    run = svc.create_run(session_id=SESSION, mode=RunMode.DEMO, user_request="hi")
    svc.mark_succeeded(run.run_id, SESSION)

    with pytest.raises(QuantLabError) as error:
        svc.assert_can_accept_tool_call(run.run_id, SESSION)
    assert error.value.code is ErrorCode.STALE_RUN


def test_budget_exceeded_after_two_tool_calls(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    run = svc.create_run(session_id=SESSION, mode=RunMode.DEMO, user_request="hi")
    svc.record_tool_execution(run.run_id, SESSION)
    svc.record_tool_execution(run.run_id, SESSION)

    with pytest.raises(QuantLabError) as error:
        svc.assert_can_accept_tool_call(run.run_id, SESSION)
    assert error.value.code is ErrorCode.BUDGET_EXCEEDED


def test_mark_failed_preserves_failure_metadata(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    run = svc.create_run(session_id=SESSION, mode=RunMode.DEMO, user_request="hi")

    failed = svc.mark_failed(
        run.run_id,
        SESSION,
        code="TOOL_FAILURE",
        message="boom",
        retryable=False,
        details={"step": "inspect"},
    )
    assert failed.status is RunStatus.FAILED
    assert failed.failure == {
        "code": "TOOL_FAILURE",
        "message": "boom",
        "retryable": False,
        "details": {"step": "inspect"},
    }
    assert failed.completed_at is not None


def test_cancel_from_running_ok(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    run = svc.create_run(session_id=SESSION, mode=RunMode.DEMO, user_request="hi")
    cancelled = svc.cancel(run.run_id, SESSION)
    assert cancelled.status is RunStatus.CANCELLED


def test_cancel_from_succeeded_raises(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    run = svc.create_run(session_id=SESSION, mode=RunMode.DEMO, user_request="hi")
    svc.mark_succeeded(run.run_id, SESSION)

    with pytest.raises(QuantLabError) as error:
        svc.cancel(run.run_id, SESSION)
    assert error.value.code is ErrorCode.STALE_RUN


def test_assert_dataset_owned_rejects_unknown(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    run = svc.create_run(session_id=SESSION, mode=RunMode.DEMO, user_request="hi")

    with pytest.raises(QuantLabError) as error:
        svc.assert_dataset_owned(run.run_id, SESSION, "not-bound")
    assert error.value.code is ErrorCode.UNKNOWN_REFERENCE


def test_reference_ownership_bindings(tmp_path: Path) -> None:
    svc = _service(tmp_path)
    run = svc.create_run(session_id=SESSION, mode=RunMode.DEMO, user_request="hi")
    run = svc.bind_analysis(run.run_id, SESSION, "analysis-1")
    assert run.analysis_id == "analysis-1"
    svc.assert_analysis_owned(run.run_id, SESSION, "analysis-1")  # no raise

    run = svc.bind_metrics(run.run_id, SESSION, "metrics-1")
    svc.assert_metrics_owned(run.run_id, SESSION, "metrics-1")

    run = svc.bind_chart(run.run_id, SESSION, "chart-1")
    svc.assert_chart_owned(run.run_id, SESSION, "chart-1")

    run = svc.bind_report(run.run_id, SESSION, "report-1")
    svc.assert_report_owned(run.run_id, SESSION, "report-1")
