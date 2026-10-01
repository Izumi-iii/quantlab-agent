"""Storage and persistence Protocols.

These are intentionally small: each Protocol exposes only what the
application / agent layer needs. The concrete implementation lives in
``adapters/local_stores.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from quantlab_agent.application.datasets import ImportedDataset
from quantlab_agent.domain.models import (
    ChartArtifact,
    ReportArtifact,
    Run,
    RunStatus,
    ToolCallRecord,
)


class DatasetSnapshot(Protocol):
    """Frozen view of a dataset returned by the store."""

    dataset_id: str
    session_id: str
    manifest: object  # DatasetManifest; structural Protocol avoids the import


class DatasetStore(Protocol):
    def save(self, dataset: ImportedDataset, session_id: str) -> str: ...

    def get(self, dataset_id: str, session_id: str) -> ImportedDataset: ...

    def get_normalized_csv_path(self, dataset_id: str, session_id: str) -> str: ...


class RunStore(Protocol):
    def create(self, run: Run) -> None: ...

    def get(self, run_id: str, session_id: str) -> Run: ...

    def transition(
        self,
        run_id: str,
        session_id: str,
        *,
        expected_status: RunStatus,
        new_status: RunStatus,
        failure: dict | None = None,
        completed_at: datetime | None = None,
    ) -> Run: ...

    def bind_analysis(self, run_id: str, session_id: str, analysis_id: str) -> Run: ...
    def bind_metrics(self, run_id: str, session_id: str, metrics_id: str) -> Run: ...
    def bind_chart(self, run_id: str, session_id: str, chart_id: str) -> Run: ...
    def bind_report(self, run_id: str, session_id: str, report_id: str) -> Run: ...
    def add_dataset(self, run_id: str, session_id: str, dataset_id: str) -> Run: ...
    def update_context_snapshot(
        self, run_id: str, session_id: str, context_snapshot: dict
    ) -> Run: ...

    def increment_tool_executions(self, run_id: str, session_id: str) -> Run: ...
    def increment_model_interactions(self, run_id: str, session_id: str) -> Run: ...

    def append_tool_call(self, run_id: str, session_id: str, record: ToolCallRecord) -> None: ...

    def list_tool_calls(self, run_id: str, session_id: str) -> tuple[ToolCallRecord, ...]: ...


class ChartStore(Protocol):
    def save(
        self,
        chart: ChartArtifact,
        *,
        session_id: str,
        png_bytes: bytes,
        data_payload: dict,
    ) -> None: ...

    def get(self, chart_id: str, session_id: str, run_id: str) -> ChartArtifact: ...

    def get_png_path(self, chart_id: str, session_id: str, run_id: str) -> str: ...

    def get_data_path(self, chart_id: str, session_id: str, run_id: str) -> str: ...


class ReportStore(Protocol):
    def save(
        self,
        report: ReportArtifact,
        *,
        session_id: str,
        markdown: str,
    ) -> None: ...

    def get(self, report_id: str, session_id: str, run_id: str) -> ReportArtifact: ...

    def get_markdown_path(self, report_id: str, session_id: str, run_id: str) -> str: ...
