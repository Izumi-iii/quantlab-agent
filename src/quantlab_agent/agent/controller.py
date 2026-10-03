"""AgentController — drives the real-model tool loop.

The controller owns one tool-calling loop per ``execute(run_id, ...)``
call. It:
  1. Builds the system + user messages.
  2. Calls the ``ModelProvider`` with the current message history.
  3. For each ``ModelTurn``:
     - tool_call → invoke ``ToolRegistry.execute``; record the
       tool-result message; loop continues.
     - text → treat as final answer; mark run succeeded.
     - error → mark run failed; stop.
  4. Stops on budget exhaustion (model interactions or tool executions)
     and marks the run accordingly.

It does not write files directly; persistence flows through the same
``RunService`` and stores the demo uses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from quantlab_agent.agent.tool_format import tool_definitions_to_openai
from quantlab_agent.agent.tools import ToolRegistry
from quantlab_agent.application.runs import RunService
from quantlab_agent.domain.errors import ErrorCode, QuantLabError
from quantlab_agent.domain.models import Run
from quantlab_agent.ports.model_provider import ModelProvider

SYSTEM_PROMPT = (
    "You are QuantLab Agent, a deterministic tool-using assistant for "
    "historical financial data analysis. You MUST drive every analysis "
    "through the registered tools rather than computing numbers "
    "yourself. Always pass exact ISO dates and tool-friendly "
    "identifiers. When a tool returns ok=false, surface the error code "
    "and adjust your next call rather than fabricating numbers.\n\n"
    "Workflow for multi-asset requests: "
    "(1) call `inspect_dataset` for each named asset to discover the "
    "dataset_id (UUID); "
    "(2) use those UUIDs in `prepare_analysis` / `compute_metrics` / "
    "`create_charts` / `build_report`. "
    "Never use the human-readable asset_id (e.g. \"DEMO_A\") where a "
    "UUID-shaped dataset_id is expected — the schema validator will "
    "reject it with PROTOCOL_ERROR."
)


class AgentController:
    def __init__(
        self,
        *,
        model_provider: ModelProvider,
        run_service: RunService,
        tool_registry: ToolRegistry,
    ) -> None:
        self._model = model_provider
        self.run_service = run_service
        self._registry = tool_registry

    def execute(
        self,
        *,
        run_id: str,
        session_id: str,
        user_request: str,
    ) -> Run:
        run = self.run_service.get_run(run_id, session_id)
        budget = run.budgets
        tools = tool_definitions_to_openai(list(self._registry.definitions()))
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_request},
        ]
        # The provider enforces its own per-call timeout; we cap the loop
        # by model interactions and tool executions only.
        for _ in range(budget.max_model_interactions):
            turn = self._model.complete_with_tools(
                messages=messages,
                tools=tools,
                timeout_seconds=budget.per_request_timeout_seconds,
            )

            if turn.error:
                self.run_service.mark_failed(
                    run_id,
                    session_id,
                    code="MODEL_ERROR",
                    message=turn.error,
                    retryable=False,
                )
                return self.run_service.get_run(run_id, session_id)

            if turn.tool_call:
                # Parse the model-supplied arguments.
                try:
                    arguments = json.loads(turn.tool_call.arguments or "{}")
                except json.JSONDecodeError as exc:
                    self.run_service.mark_failed(
                        run_id,
                        session_id,
                        code="MODEL_ERROR",
                        message=f"Model returned invalid JSON for tool call: {exc}",
                        retryable=False,
                    )
                    return self.run_service.get_run(run_id, session_id)
                envelope = self._registry.execute(
                    run_id=run_id,
                    session_id=session_id,
                    tool_call_id=turn.tool_call.id,
                    tool_name=turn.tool_call.name,
                    arguments=arguments,
                )
                messages.append(
                    {
                        "role": "assistant",
                        "tool_calls": [
                            {
                                "id": turn.tool_call.id,
                                "type": "function",
                                "function": {
                                    "name": turn.tool_call.name,
                                    "arguments": turn.tool_call.arguments,
                                },
                            }
                        ],
                    }
                )
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": turn.tool_call.id,
                        "content": json.dumps(envelope.model_dump(mode="json"), default=str),
                    }
                )
                continue

            if turn.text is not None:
                # Model produced a final natural-language answer;
                # mark the run succeeded without binding a report.
                # The build_report tool, if registered, will already
                # have produced the Markdown artifact and called
                # mark_succeeded itself.
                try:
                    run_after = self.run_service.get_run(run_id, session_id)
                    if run_after.status.value != "succeeded":
                        self.run_service.mark_succeeded(run_id, session_id)
                except QuantLabError as exc:
                    if exc.code is not ErrorCode.STALE_RUN:
                        raise
                return self.run_service.get_run(run_id, session_id)

        # Budget exhausted.
        self.run_service.mark_failed(
            run_id,
            session_id,
            code="BUDGET_EXCEEDED",
            message=(
                f"Model-interaction budget ({budget.max_model_interactions}) "
                "exhausted before the run reached a final answer."
            ),
            retryable=True,
        )
        return self.run_service.get_run(run_id, session_id)


__all__ = ["AgentController", "SYSTEM_PROMPT", "build_real_agent_stack"]


def build_real_agent_stack(
    runs_dir: Path,
    model_config: Any,
) -> AgentController:
    """Compose the same dependency graph as the demo but route through
    a real model provider. Used by the CLI ``chat`` command and the
    Streamlit UI's Real Model tab.
    """
    from quantlab_agent.adapters.local_stores import (
        LocalChartStore,
        LocalDatasetStore,
        LocalReportStore,
        LocalRunStore,
    )
    from quantlab_agent.adapters.openai_compatible import OpenAICompatibleProvider
    from quantlab_agent.adapters.plotting import PlotService
    from quantlab_agent.agent.tools import default_registry
    from quantlab_agent.application.analyses import AnalysisService
    from quantlab_agent.application.charts import ChartService
    from quantlab_agent.application.datasets import DatasetService
    from quantlab_agent.application.reports import ReportService

    runs_dir = Path(runs_dir).resolve()
    dataset_store = LocalDatasetStore(runs_dir)
    run_store = LocalRunStore(runs_dir)
    chart_store = LocalChartStore(runs_dir)
    report_store = LocalReportStore(runs_dir)
    dataset_service = DatasetService()
    analysis_service = AnalysisService()
    run_service = RunService(run_store)
    chart_service = ChartService(
        chart_store=chart_store,
        plot_service=PlotService(),
        run_service=run_service,
    )
    report_service = ReportService(report_store=report_store, run_service=run_service)
    registry = default_registry(
        dataset_service=dataset_service,
        analysis_service=analysis_service,
        chart_service=chart_service,
        report_service=report_service,
        run_service=run_service,
        dataset_store=dataset_store,
        run_store=run_store,
        chart_store=chart_store,
        report_store=report_store,
    )
    provider = OpenAICompatibleProvider(
        base_url=model_config.base_url,
        api_key=model_config.api_key,
        model=model_config.model,
        timeout_seconds=model_config.timeout_seconds,
        temperature=model_config.temperature,
        max_tokens=model_config.max_tokens,
    )
    return AgentController(
        model_provider=provider,
        run_service=run_service,
        tool_registry=registry,
    )
