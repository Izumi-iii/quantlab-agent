"""RunService — owns the run state machine and budget enforcement.

Only RunService may call ``RunStore.transition``. ToolRegistry and the
agent controller ask RunService whether a tool call may proceed
(``assert_can_accept_tool_call``); they never mutate state directly.

Per architecture §8.1, the state machine is:

    IDLE → DATA_READY → RUNNING → SUCCEEDED | FAILED | CANCELLED
    RUNNING → NEEDS_CLARIFICATION → RUNNING | CANCELLED
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from quantlab_agent.adapters.local_stores import utcnow
from quantlab_agent.domain.errors import ErrorCode, QuantLabError
from quantlab_agent.domain.models import (
    Run,
    RunBudget,
    RunCounters,
    RunMode,
    RunStatus,
)
from quantlab_agent.domain.policies import DEFAULT_RUN_BUDGET
from quantlab_agent.ports.stores import RunStore


class RunService:
    def __init__(
        self,
        run_store: RunStore,
        *,
        default_budget: RunBudget | None = None,
    ) -> None:
        self._runs = run_store
        self._default_budget = default_budget or RunBudget(
            max_model_interactions=DEFAULT_RUN_BUDGET.max_model_interactions,
            max_tool_executions=DEFAULT_RUN_BUDGET.max_tool_executions,
            max_same_validation_retry=DEFAULT_RUN_BUDGET.max_same_validation_retry,
            max_retryable_network_errors=DEFAULT_RUN_BUDGET.max_retryable_network_errors,
            per_request_timeout_seconds=DEFAULT_RUN_BUDGET.per_request_timeout_seconds,
            total_deadline_seconds=DEFAULT_RUN_BUDGET.total_deadline_seconds,
        )

    # -- creation ----------------------------------------------------------

    def create_run(
        self,
        *,
        session_id: str,
        mode: RunMode,
        user_request: str,
        budgets: RunBudget | None = None,
        context_snapshot: dict[str, Any] | None = None,
    ) -> Run:
        run = Run(
            run_id=str(uuid4()),
            session_id=session_id,
            mode=mode,
            status=RunStatus.RUNNING,
            user_request=user_request,
            dataset_ids=(),
            budgets=budgets or self._default_budget,
            counters=RunCounters(),
            context_snapshot=dict(context_snapshot or {}),
            created_at=utcnow(),
            started_at=utcnow(),
        )
        self._runs.create(run)
        return self._runs.get(run.run_id, session_id)

    # -- state machine -----------------------------------------------------

    def get_run(self, run_id: str, session_id: str) -> Run:
        return self._runs.get(run_id, session_id)

    def assert_can_accept_tool_call(self, run_id: str, session_id: str) -> Run:
        run = self._runs.get(run_id, session_id)
        if run.status is not RunStatus.RUNNING:
            raise QuantLabError(
                ErrorCode.STALE_RUN,
                "Run is not accepting tool calls.",
                details={
                    "run_id": run_id,
                    "status": run.status.value,
                },
            )
        if run.counters.tool_executions_used >= run.budgets.max_tool_executions:
            raise QuantLabError(
                ErrorCode.BUDGET_EXCEEDED,
                "Tool-execution budget exhausted.",
                details={
                    "used": run.counters.tool_executions_used,
                    "limit": run.budgets.max_tool_executions,
                },
            )
        return run

    def mark_succeeded(
        self, run_id: str, session_id: str, completed_at: datetime | None = None
    ) -> Run:
        return self._runs.transition(
            run_id,
            session_id,
            expected_status=RunStatus.RUNNING,
            new_status=RunStatus.SUCCEEDED,
            completed_at=completed_at or utcnow(),
        )

    def mark_failed(
        self,
        run_id: str,
        session_id: str,
        *,
        code: str,
        message: str,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> Run:
        return self._runs.transition(
            run_id,
            session_id,
            expected_status=RunStatus.RUNNING,
            new_status=RunStatus.FAILED,
            failure={
                "code": code,
                "message": message,
                "retryable": retryable,
                "details": details or {},
            },
            completed_at=utcnow(),
        )

    def cancel(self, run_id: str, session_id: str) -> Run:
        current = self._runs.get(run_id, session_id)
        # Allow cancel from RUNNING or NEEDS_CLARIFICATION.
        if current.status not in {RunStatus.RUNNING, RunStatus.NEEDS_CLARIFICATION}:
            raise QuantLabError(
                ErrorCode.STALE_RUN,
                "Run is not in a cancellable state.",
                details={"status": current.status.value},
            )
        return self._runs.transition(
            run_id,
            session_id,
            expected_status=current.status,
            new_status=RunStatus.CANCELLED,
            completed_at=utcnow(),
        )

    # -- reference validation ---------------------------------------------

    def assert_dataset_owned(self, run_id: str, session_id: str, dataset_id: str) -> Run:
        run = self._runs.get(run_id, session_id)
        if run.session_id != session_id:
            raise QuantLabError(
                ErrorCode.UNKNOWN_REFERENCE,
                "Run does not belong to the current session.",
                details={"run_id": run_id},
            )
        if dataset_id not in run.dataset_ids:
            raise QuantLabError(
                ErrorCode.UNKNOWN_REFERENCE,
                "Dataset is not bound to this run.",
                details={"dataset_id": dataset_id, "run_id": run_id},
            )
        return run

    def assert_analysis_owned(self, run_id: str, session_id: str, analysis_id: str) -> Run:
        run = self._runs.get(run_id, session_id)
        if run.analysis_id != analysis_id:
            raise QuantLabError(
                ErrorCode.UNKNOWN_REFERENCE,
                "Analysis is not bound to this run.",
                details={"analysis_id": analysis_id, "run_id": run_id},
            )
        return run

    def assert_metrics_owned(self, run_id: str, session_id: str, metrics_id: str) -> Run:
        run = self._runs.get(run_id, session_id)
        if run.metrics_id != metrics_id:
            raise QuantLabError(
                ErrorCode.UNKNOWN_REFERENCE,
                "Metrics are not bound to this run.",
                details={"metrics_id": metrics_id, "run_id": run_id},
            )
        return run

    def assert_chart_owned(self, run_id: str, session_id: str, chart_id: str) -> Run:
        run = self._runs.get(run_id, session_id)
        if chart_id not in run.chart_ids:
            raise QuantLabError(
                ErrorCode.UNKNOWN_REFERENCE,
                "Chart is not bound to this run.",
                details={"chart_id": chart_id, "run_id": run_id},
            )
        return run

    def assert_report_owned(self, run_id: str, session_id: str, report_id: str) -> Run:
        run = self._runs.get(run_id, session_id)
        if run.report_id != report_id:
            raise QuantLabError(
                ErrorCode.UNKNOWN_REFERENCE,
                "Report is not bound to this run.",
                details={"report_id": report_id, "run_id": run_id},
            )
        return run

    # -- bindings (used by tool handlers) ----------------------------------

    def add_dataset(self, run_id: str, session_id: str, dataset_id: str) -> Run:
        return self._runs.add_dataset(run_id, session_id, dataset_id)

    def update_context_snapshot(
        self, run_id: str, session_id: str, context_snapshot: dict[str, Any]
    ) -> Run:
        return self._runs.update_context_snapshot(run_id, session_id, context_snapshot)

    def bind_analysis(self, run_id: str, session_id: str, analysis_id: str) -> Run:
        return self._runs.bind_analysis(run_id, session_id, analysis_id)

    def bind_metrics(self, run_id: str, session_id: str, metrics_id: str) -> Run:
        return self._runs.bind_metrics(run_id, session_id, metrics_id)

    def bind_chart(self, run_id: str, session_id: str, chart_id: str) -> Run:
        return self._runs.bind_chart(run_id, session_id, chart_id)

    def bind_report(self, run_id: str, session_id: str, report_id: str) -> Run:
        return self._runs.bind_report(run_id, session_id, report_id)

    def record_tool_execution(self, run_id: str, session_id: str) -> Run:
        return self._runs.increment_tool_executions(run_id, session_id)

    def record_model_interaction(self, run_id: str, session_id: str) -> Run:
        return self._runs.increment_model_interactions(run_id, session_id)


__all__ = ["RunService"]
