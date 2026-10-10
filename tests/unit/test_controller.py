"""Tests for AgentController with the in-memory FakeProvider."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quantlab_agent.adapters.fake_provider import FakeProvider
from quantlab_agent.adapters.local_stores import (
    LocalChartStore,
    LocalDatasetStore,
    LocalReportStore,
    LocalRunStore,
)
from quantlab_agent.adapters.plotting import PlotService
from quantlab_agent.agent.controller import AgentController, is_supported_analysis_request
from quantlab_agent.agent.tools import default_registry
from quantlab_agent.application.analyses import AnalysisService
from quantlab_agent.application.charts import ChartService
from quantlab_agent.application.datasets import DatasetService
from quantlab_agent.application.reports import ReportService
from quantlab_agent.application.runs import RunService
from quantlab_agent.domain.models import (
    Run,
    RunBudget,
    RunCounters,
    RunMode,
)
from quantlab_agent.ports.model_provider import ModelTurn, ToolCall

SESSION = "00000000-0000-4000-8000-000000000099"


def _build_stack(tmp_path: Path):
    runs_dir = tmp_path
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
    return registry, run_service


def _seed_run(run_service: RunService, run_id: str = "11111111-1111-4111-8111-111111111111") -> Run:
    """Create a pre-seeded Run directly via the store."""
    run_service._runs.create(  # noqa: SLF001 - test fixture writes through store
        Run(
            run_id=run_id,
            session_id=SESSION,
            mode=RunMode.REAL_AGENT,
            status=RunStatus.RUNNING,
            user_request="test",
            dataset_ids=(),
            budgets=RunBudget(
                max_model_interactions=4,
                max_tool_executions=8,
                max_same_validation_retry=1,
                max_retryable_network_errors=1,
                per_request_timeout_seconds=10,
                total_deadline_seconds=60,
            ),
            counters=RunCounters(),
            created_at=datetime.now(UTC),
        )
    )
    return run_service.get_run(run_id, SESSION)


# Late import to avoid double-line at top.
from quantlab_agent.domain.models import RunStatus  # noqa: E402


def test_controller_marks_text_without_report_as_needs_clarification(
    tmp_path: Path,
) -> None:
    registry, run_service = _build_stack(tmp_path)
    run = _seed_run(run_service)
    scripted = FakeProvider(
        [
            ModelTurn(text="Report generated.", finish_reason="stop"),
        ],
        echo_calls=True,
    )
    controller = AgentController(
        model_provider=scripted,
        run_service=run_service,
        tool_registry=registry,
    )
    final = controller.execute(
        run_id=run.run_id,
        session_id=SESSION,
        user_request="compare DEMO_A and DEMO_B period return",
    )
    assert final.status.value == "needs_clarification"
    assert final.failure is not None
    assert final.failure["code"] == "NEEDS_CLARIFICATION"
    assert final.failure["details"]["model_text"] == "Report generated."
    assert len(scripted.calls) == 1


def test_controller_rejects_out_of_scope_request_before_model_call(tmp_path: Path) -> None:
    registry, run_service = _build_stack(tmp_path)
    run = _seed_run(run_service)
    scripted = FakeProvider([ModelTurn(text="Here is a poem.", finish_reason="stop")])
    controller = AgentController(
        model_provider=scripted,
        run_service=run_service,
        tool_registry=registry,
    )

    final = controller.execute(
        run_id=run.run_id,
        session_id=SESSION,
        user_request="帮我写一首诗",
    )

    assert final.status.value == "failed"
    assert final.failure is not None
    assert final.failure["code"] == "OUT_OF_SCOPE"
    assert scripted.calls == []


def test_scope_gate_accepts_chinese_analysis_and_rejects_unrelated_requests() -> None:
    assert is_supported_analysis_request(
        "请比较 DEMO_A 和 DEMO_B 在 2024-01 的区间收益和最大回撤，并生成报告"
    )
    assert is_supported_analysis_request("风险怎么样？")
    assert is_supported_analysis_request("计算夏普、VaR 和 CVaR")
    assert is_supported_analysis_request("趋势图")
    assert is_supported_analysis_request("生成趋势图，并检查有没有异常常值")
    assert not is_supported_analysis_request("帮我查一下明天上海天气")


def test_controller_marks_budget_exceeded(tmp_path: Path) -> None:
    registry, run_service = _build_stack(tmp_path)
    # Tight budget: 2 model interactions; model never returns a final
    # text answer, only tool calls, so the loop must exhaust the budget.
    run = _seed_run(run_service)
    run_service._runs._write_manifest(  # noqa: SLF001 - test fixture
        run_service._runs._run_dir(run.run_id, SESSION),  # noqa: SLF001
        run.model_copy(
            update={
                "budgets": RunBudget(
                    max_model_interactions=2,
                    max_tool_executions=2,
                    max_same_validation_retry=1,
                    max_retryable_network_errors=1,
                    per_request_timeout_seconds=10,
                    total_deadline_seconds=60,
                )
            }
        ),
    )
    scripted = FakeProvider(
        [
            ModelTurn(
                tool_call=ToolCall(
                    id="t1",
                    name="inspect_dataset",
                    arguments=json.dumps({"dataset_id": "0" * 36}),
                ),
                finish_reason="tool_calls",
            ),
            ModelTurn(
                tool_call=ToolCall(
                    id="t2",
                    name="inspect_dataset",
                    arguments=json.dumps({"dataset_id": "0" * 36}),
                ),
                finish_reason="tool_calls",
            ),
            ModelTurn(text="never reached", finish_reason="stop"),
        ]
    )
    controller = AgentController(
        model_provider=scripted,
        run_service=run_service,
        tool_registry=registry,
    )
    final = controller.execute(
        run_id=run.run_id,
        session_id=SESSION,
        user_request="compare DEMO_A period return",
    )
    assert final.status.value == "failed"
    assert final.failure is not None
    assert final.failure["code"] == "BUDGET_EXCEEDED"


def test_controller_marks_failed_on_model_error(tmp_path: Path) -> None:
    registry, run_service = _build_stack(tmp_path)
    run = _seed_run(run_service)
    scripted = FakeProvider([ModelTurn(error="rate limited", finish_reason="stop")])
    controller = AgentController(
        model_provider=scripted,
        run_service=run_service,
        tool_registry=registry,
    )
    final = controller.execute(
        run_id=run.run_id,
        session_id=SESSION,
        user_request="compare DEMO_A period return",
    )
    assert final.status.value == "failed"
    assert final.failure is not None
    assert final.failure["code"] == "MODEL_ERROR"
    assert "rate limited" in final.failure["message"]


def test_controller_surfaces_protocol_error_and_lets_model_retry(
    tmp_path: Path,
) -> None:
    """When the model submits an invalid tool argument (e.g. asset_id
    instead of UUID dataset_id), the schema validator returns
    PROTOCOL_ERROR. The controller must surface this to the model via
    the tool-result message so the model can retry — not crash, not
    fabricate data, not abort the run.
    """
    registry, run_service = _build_stack(tmp_path)
    run = _seed_run(run_service)
    scripted = FakeProvider(
        [
            ModelTurn(
                tool_call=ToolCall(
                    id="call_bad",
                    name="inspect_dataset",
                    # "DEMO_A" is a 6-char asset_id, NOT a 36-char UUID;
                    # the schema validator must reject this.
                    arguments=json.dumps({"dataset_id": "DEMO_A"}),
                ),
                finish_reason="tool_calls",
            ),
            ModelTurn(text="Sorry, will retry with the UUID.", finish_reason="stop"),
        ],
        echo_calls=True,
    )
    controller = AgentController(
        model_provider=scripted,
        run_service=run_service,
        tool_registry=registry,
    )
    final = controller.execute(
        run_id=run.run_id,
        session_id=SESSION,
        user_request="inspect DEMO_A",
    )
    assert final.status.value == "needs_clarification"
    assert final.failure is not None
    assert final.failure["code"] == "NEEDS_CLARIFICATION"

    # The bad call is persisted in tool_calls.jsonl as failed.
    records = run_service.list_tool_calls(run.run_id, SESSION)
    assert len(records) == 1
    assert records[0].status.value == "failed"
    assert records[0].error_code == "PROTOCOL_ERROR"
    # Both model turns were issued.
    assert len(scripted.calls) == 2
    second_messages = scripted.calls[1]["messages"]
    assert any(
        msg.get("role") == "tool" and msg.get("tool_call_id") == "call_bad"
        for msg in second_messages
    )


def test_controller_discovers_uuids_via_list_datasets_then_inspects(
    tmp_path: Path,
) -> None:
    """The model follows the system-prompted workflow: first call
    ``list_datasets`` to discover the real UUIDs, then ``inspect_dataset``
    with one of those UUIDs. The whole chain succeeds without any
    asset_id leaking into the dataset_id slot.
    """
    from quantlab_agent.adapters.local_stores import LocalDatasetStore
    from quantlab_agent.application.datasets import DatasetService
    from quantlab_agent.domain.models import DatasetMetadata, PriceBasis
    from quantlab_agent.ports.model_provider import ModelProvider

    # Seed two datasets into the session before the model runs.
    dataset_store = LocalDatasetStore(tmp_path)
    ds_service = DatasetService()
    for asset_id in ("DEMO_A", "DEMO_B"):
        metadata = DatasetMetadata(
            asset_id=asset_id,
            source_name="test",
            price_basis=PriceBasis.FORWARD_ADJUSTED,
            currency="CNY",
            frequency="daily",
            calendar_label="test",
            daily_series_complete=True,
            is_synthetic=True,
        )
        result = ds_service.import_csv(
            b"date,close\n2024-01-02,100\n2024-01-03,101\n2024-01-04,102\n",
            metadata=metadata,
            session_id=SESSION,
        )
        assert result.dataset is not None
        dataset_store.save(result.dataset, SESSION)

    registry, run_service = _build_stack(tmp_path)
    run = _seed_run(run_service)

    # A dynamic provider: turn 1 calls list_datasets({}); turn 2 picks a
    # UUID out of the previous tool result and calls inspect_dataset with
    # it; turn 3 returns a final answer. We need turn 2 to be conditional
    # on the actual UUIDs because they are randomly generated at import.
    class _DiscoveryProvider(ModelProvider):
        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []
            self._step = 0

        def complete_with_tools(
            self,
            messages: list[dict[str, Any]],
            tools: list[dict[str, Any]],
            timeout_seconds: float,
        ) -> ModelTurn:
            self.calls.append({"messages": list(messages)})
            self._step += 1
            if self._step == 1:
                return ModelTurn(
                    tool_call=ToolCall(
                        id="call_list",
                        name="list_datasets",
                        arguments=json.dumps({}),
                    ),
                    finish_reason="tool_calls",
                )
            if self._step == 2:
                # Pull the list_datasets tool result from the message
                # history and reuse its first dataset_id.
                tool_messages = [msg for msg in messages if msg.get("role") == "tool"]
                assert tool_messages, "model turn 2 must see the list_datasets result"
                last_tool = tool_messages[-1]
                envelope = json.loads(last_tool["content"])
                datasets = envelope["data"]["datasets"]
                assert datasets, "session should have seeded datasets"
                first_uuid = datasets[0]["dataset_id"]
                return ModelTurn(
                    tool_call=ToolCall(
                        id="call_inspect",
                        name="inspect_dataset",
                        arguments=json.dumps({"dataset_id": first_uuid}),
                    ),
                    finish_reason="tool_calls",
                )
            return ModelTurn(
                text="Inspected DEMO_A successfully.",
                finish_reason="stop",
            )

    provider = _DiscoveryProvider()
    controller = AgentController(
        model_provider=provider,
        run_service=run_service,
        tool_registry=registry,
    )
    final = controller.execute(
        run_id=run.run_id,
        session_id=SESSION,
        user_request="inspect DEMO_A and build a report",
    )
    assert final.status.value == "needs_clarification"
    assert final.failure is not None
    assert final.failure["code"] == "NEEDS_CLARIFICATION"

    # Both tool calls succeeded and were persisted.
    records = run_service.list_tool_calls(run.run_id, SESSION)
    assert [r.tool_name for r in records] == ["list_datasets", "inspect_dataset"]
    assert all(r.status.value == "succeeded" for r in records)

    # The list_datasets tool-result contained two UUIDs — proves the
    # model got real data to work from rather than guessing.
    list_call, inspect_call = records
    list_envelope_data = list_call.result_envelope.data
    assert list_envelope_data is not None
    returned_ids = {item["dataset_id"] for item in list_envelope_data["datasets"]}
    assert len(returned_ids) == 2
    # inspect_dataset bound the same UUID the model pulled from the list.
    inspect_envelope_data = inspect_call.result_envelope.data
    assert inspect_envelope_data is not None
    assert inspect_envelope_data["asset_id"] in {"DEMO_A", "DEMO_B"}
    assert inspect_envelope_data["dataset_id"] in returned_ids
    # After inspect_dataset, the run has exactly one dataset bound.
    final_run = run_service.get_run(run.run_id, SESSION)
    assert len(final_run.dataset_ids) == 1
    assert final_run.dataset_ids[0] in returned_ids
