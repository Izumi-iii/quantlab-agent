"""PlanExecutor — runs the tool chain selected by ``PlanValidator``.

This is a thin wrapper around ``ToolRegistry.execute(...)`` that picks
the right sequence of tool calls per ``Intent``. It does NOT register
new tools; it composes the existing six tools registered by
``default_registry``.

State transitions are delegated to ``RunService``: ``data_quality`` /
``metrics`` / ``report`` finish via ``mark_succeeded`` (only the
``report`` path calls ``build_report`` which marks succeeded itself),
``clarify`` calls ``mark_needs_clarification``, and any uncaught tool
error is left in the run's ``tool_calls.jsonl`` for the UI to render.
"""

from __future__ import annotations

from quantlab_agent.agent.plan_validator import ClarificationRequest, OutOfScopeError
from quantlab_agent.agent.tools import ToolRegistry
from quantlab_agent.application.runs import RunService
from quantlab_agent.domain.errors import ErrorCode, QuantLabError
from quantlab_agent.domain.models import (
    ChartKind,
    Intent,
    MetricName,
    ResolvedPlan,
    Run,
)


class PlanExecutor:
    def __init__(
        self,
        *,
        registry: ToolRegistry,
        run_service: RunService,
    ) -> None:
        self._registry = registry
        self._runs = run_service

    def execute(
        self,
        *,
        run_id: str,
        session_id: str,
        plan: ResolvedPlan | ClarificationRequest | OutOfScopeError,
    ) -> Run:
        if isinstance(plan, ClarificationRequest):
            return self._runs.mark_needs_clarification(
                run_id,
                session_id,
                message=plan.question,
                details={
                    "clarifying_question": plan.question,
                    "user_visible_summary": plan.summary,
                    "intent": Intent.CLARIFY.value,
                },
            )
        if isinstance(plan, OutOfScopeError):
            return self._runs.mark_failed(
                run_id,
                session_id,
                code=plan.code.value,
                message=str(plan),
                retryable=False,
                details={
                    "intent": Intent.OUT_OF_SCOPE.value,
                    "user_visible_summary": plan.user_message,
                },
            )
        return self._execute_resolved(run_id, session_id, plan)

    # -- internals ----------------------------------------------------------

    def _execute_resolved(
        self,
        run_id: str,
        session_id: str,
        plan: ResolvedPlan,
    ) -> Run:
        # Persist the resolved plan into context_snapshot so the UI can
        # render it alongside the run state.
        run = self._runs.get_run(run_id, session_id)
        snapshot = dict(run.context_snapshot)
        snapshot["intent"] = plan.intent.value
        snapshot["plan_summary"] = plan.plan_summary
        snapshot["resolved_dataset_ids"] = list(plan.resolved_dataset_ids)
        if plan.date_range is not None:
            snapshot["requested_start"] = plan.date_range.start.isoformat()
            snapshot["requested_end"] = plan.date_range.end.isoformat()
        if plan.effective_start is not None:
            snapshot["effective_start"] = plan.effective_start.isoformat()
        if plan.effective_end is not None:
            snapshot["effective_end"] = plan.effective_end.isoformat()
        if plan.effective_start is not None:
            snapshot["execution_start"] = plan.effective_start.isoformat()
        if plan.effective_end is not None:
            snapshot["execution_end"] = plan.effective_end.isoformat()
        metrics_for_execution = plan.metrics or self._default_metrics()
        snapshot["requested_metrics"] = [m.value for m in metrics_for_execution]
        if plan.user_visible_summary:
            snapshot["user_visible_summary"] = plan.user_visible_summary
        self._runs.update_context_snapshot(run_id, session_id, snapshot)

        dataset_ids = list(plan.resolved_dataset_ids)
        if not dataset_ids:
            raise QuantLabError(
                ErrorCode.INVALID_ARGUMENT,
                "Plan resolved with no datasets; cannot execute.",
            )

        if plan.intent is Intent.DATA_QUALITY:
            return self._execute_data_quality(run_id, session_id, dataset_ids)

        if plan.intent is Intent.METRICS:
            return self._execute_metrics(
                run_id,
                session_id,
                dataset_ids,
                metrics=metrics_for_execution,
            )

        if plan.intent is Intent.REPORT:
            return self._execute_report(
                run_id,
                session_id,
                dataset_ids,
                metrics=metrics_for_execution,
                charts=plan.charts or self._default_chart_kinds(),
            )

        if plan.intent is Intent.CHART:
            return self._execute_chart(
                run_id,
                session_id,
                dataset_ids,
                charts=plan.charts or self._default_chart_kinds(),
            )

        raise QuantLabError(
            ErrorCode.INVALID_ARGUMENT,
            f"Unsupported intent: {plan.intent.value}",
        )

    # -- per-intent branches ------------------------------------------------

    def _execute_data_quality(
        self,
        run_id: str,
        session_id: str,
        dataset_ids: list[str],
    ) -> Run:
        for ds_id in dataset_ids:
            env = self._registry.execute(
                run_id=run_id,
                session_id=session_id,
                tool_name="inspect_dataset",
                arguments={"dataset_id": ds_id},
            )
            if not env.ok:
                return self._runs.get_run(run_id, session_id)
        return self._runs.mark_succeeded(run_id, session_id)

    def _execute_metrics(
        self,
        run_id: str,
        session_id: str,
        dataset_ids: list[str],
        *,
        metrics: tuple[MetricName, ...],
    ) -> Run:
        env = self._call_inspect(run_id, session_id, dataset_ids)
        if env is not None and not env.ok:
            return self._runs.get_run(run_id, session_id)

        if not isinstance(env.data, dict) or "analysis_id" not in env.data:
            return self._runs.get_run(run_id, session_id)
        analysis_id = env.data["analysis_id"]
        env = self._registry.execute(
            run_id=run_id,
            session_id=session_id,
            tool_name="compute_metrics",
            arguments={"analysis_id": analysis_id},
        )
        if not env.ok:
            return self._runs.get_run(run_id, session_id)
        return self._runs.mark_succeeded(run_id, session_id)

    def _execute_report(
        self,
        run_id: str,
        session_id: str,
        dataset_ids: list[str],
        *,
        metrics: tuple[MetricName, ...],
        charts: tuple[ChartKind, ...],
    ) -> Run:
        env = self._call_inspect(run_id, session_id, dataset_ids)
        if env is not None and not env.ok:
            return self._runs.get_run(run_id, session_id)
        if not isinstance(env.data, dict) or "analysis_id" not in env.data:
            return self._runs.get_run(run_id, session_id)
        analysis_id = env.data["analysis_id"]

        env = self._registry.execute(
            run_id=run_id,
            session_id=session_id,
            tool_name="compute_metrics",
            arguments={"analysis_id": analysis_id},
        )
        if not env.ok:
            return self._runs.get_run(run_id, session_id)
        metrics_id = env.data["metrics_id"]

        env = self._registry.execute(
            run_id=run_id,
            session_id=session_id,
            tool_name="create_charts",
            arguments={
                "analysis_id": analysis_id,
                "kinds": [k.value for k in charts],
            },
        )
        if not env.ok:
            return self._runs.get_run(run_id, session_id)
        chart_ids = list(env.data["chart_ids"])

        env = self._registry.execute(
            run_id=run_id,
            session_id=session_id,
            tool_name="build_report",
            arguments={
                "analysis_id": analysis_id,
                "metrics_id": metrics_id,
                "chart_ids": chart_ids,
            },
        )
        return self._runs.get_run(run_id, session_id)

    def _execute_chart(
        self,
        run_id: str,
        session_id: str,
        dataset_ids: list[str],
        *,
        charts: tuple[ChartKind, ...],
    ) -> Run:
        # Stub — chart-only intent ships in M7; for now we run
        # inspect + prepare + create_charts.
        env = self._call_inspect(run_id, session_id, dataset_ids)
        if env is not None and not env.ok:
            return self._runs.get_run(run_id, session_id)
        if not isinstance(env.data, dict) or "analysis_id" not in env.data:
            return self._runs.get_run(run_id, session_id)
        analysis_id = env.data["analysis_id"]
        env = self._registry.execute(
            run_id=run_id,
            session_id=session_id,
            tool_name="create_charts",
            arguments={
                "analysis_id": analysis_id,
                "kinds": [k.value for k in charts],
            },
        )
        if not env.ok:
            return self._runs.get_run(run_id, session_id)
        return self._runs.mark_succeeded(run_id, session_id)

    # -- helpers ------------------------------------------------------------

    def _call_inspect(
        self,
        run_id: str,
        session_id: str,
        dataset_ids: list[str],
    ):
        """Run inspect_dataset for each id, then prepare_analysis.

        Returns the prepare_analysis envelope. The agent uses the
        returned ``analysis_id`` for downstream calls.
        """
        for ds_id in dataset_ids:
            env = self._registry.execute(
                run_id=run_id,
                session_id=session_id,
                tool_name="inspect_dataset",
                arguments={"dataset_id": ds_id},
            )
            if not env.ok:
                return env

        run = self._runs.get_run(run_id, session_id)
        requested_start = run.context_snapshot.get(
            "execution_start",
            run.context_snapshot.get("effective_start", "2024-01-02"),
        )
        requested_end = run.context_snapshot.get(
            "execution_end",
            run.context_snapshot.get("effective_end", "2024-01-15"),
        )
        requested_metrics = run.context_snapshot.get(
            "requested_metrics",
            [m.value for m in self._default_metrics()],
        )
        env = self._registry.execute(
            run_id=run_id,
            session_id=session_id,
            tool_name="prepare_analysis",
            arguments={
                "dataset_ids": dataset_ids,
                "requested_start": requested_start,
                "requested_end": requested_end,
                "requested_metrics": list(requested_metrics),
            },
        )
        return env

    @staticmethod
    def _default_metrics() -> tuple[MetricName, ...]:
        return (MetricName.PERIOD_RETURN, MetricName.MAX_DRAWDOWN)

    @staticmethod
    def _default_chart_kinds() -> tuple[ChartKind, ...]:
        return (ChartKind.NORMALIZED_PRICES, ChartKind.DRAWDOWN)


__all__ = ["PlanExecutor"]
