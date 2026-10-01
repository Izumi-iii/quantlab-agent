"""Tool-handler Protocol and ToolContext dataclass."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel

from quantlab_agent.ports.stores import (
    ChartStore,
    DatasetStore,
    ReportStore,
    RunStore,
)


@dataclass(frozen=True, slots=True)
class ToolContext:
    """Per-invocation context passed from ToolRegistry to handlers.

    Handlers receive this and the validated arguments; they must not reach
    outside of ``ports`` to talk to the filesystem or model SDK directly.
    """

    run_id: str
    session_id: str
    tool_call_id: str
    started_at: datetime
    budget_state: dict[str, Any]
    dataset_store: DatasetStore
    run_store: RunStore
    chart_store: ChartStore
    report_store: ReportStore


class ToolHandler(Protocol):
    def __call__(
        self,
        ctx: ToolContext,
        arguments: BaseModel,
    ) -> dict[str, Any]: ...
