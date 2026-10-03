"""Deterministic demo controller.

Runs three preset scenarios through the **same** ToolRegistry used by
the future real-model path. No alternative code paths; every scenario
is just a fixed sequence of tool calls.
"""

from __future__ import annotations

from pathlib import Path

from quantlab_agent.adapters.local_stores import (
    LocalChartStore,
    LocalDatasetStore,
    LocalReportStore,
    LocalRunStore,
)
from quantlab_agent.adapters.plotting import PlotService
from quantlab_agent.agent.tools import ToolRegistry, ToolResultEnvelope
from quantlab_agent.application.analyses import AnalysisService
from quantlab_agent.application.charts import ChartService
from quantlab_agent.application.datasets import DatasetService
from quantlab_agent.application.reports import ReportService
from quantlab_agent.application.runs import RunService
from quantlab_agent.domain.models import (
    ChartKind,
    DatasetMetadata,
    MetricName,
    PriceBasis,
    Run,
    RunMode,
)

EXAMPLES_DIR = Path(__file__).parents[3] / "data" / "examples"


class DemoController:
    def __init__(
        self,
        *,
        runs_dir: Path,
        registry: ToolRegistry,
        run_service: RunService,
        dataset_service: DatasetService,
        dataset_store: LocalDatasetStore | None = None,
        chart_store: LocalChartStore | None = None,
        report_store: LocalReportStore | None = None,
    ) -> None:
        self._runs_dir = runs_dir
        self._registry = registry
        self._runs = run_service
        self._datasets = dataset_service
        # Public attributes so the UI can read artifacts produced by the
        # tool pipeline (chart PNGs, report markdown).
        self.dataset_store = dataset_store or LocalDatasetStore(runs_dir)
        self.chart_store = chart_store or LocalChartStore(runs_dir)
        self.report_store = report_store or LocalReportStore(runs_dir)

    # -- scenarios ---------------------------------------------------------

    DEFAULT_SESSION_ID = "00000000-0000-4000-8000-000000000099"

    def run_two_asset(self, session_id: str = DEFAULT_SESSION_ID) -> Run:
        return self._run_compare(
            session_id=session_id,
            user_request="Compare DEMO_A and DEMO_B in 2024-01.",
            dataset_files=(("DEMO_A.csv", "DEMO_A"), ("DEMO_B.csv", "DEMO_B")),
        )

    def run_single_asset(self, session_id: str = DEFAULT_SESSION_ID) -> Run:
        run = self._bootstrap_run(session_id, user_request="Describe DEMO_A in 2024-01.")
        ds_a = self._import_dataset("DEMO_A.csv", "DEMO_A", session_id)
        self._runs.add_dataset(run.run_id, session_id, ds_a)
        self._execute_pipeline(
            run_id=run.run_id,
            session_id=session_id,
            dataset_ids=[ds_a],
        )
        return self._runs.get_run(run.run_id, session_id)

    def run_duplicate_date_failure(self, session_id: str = DEFAULT_SESSION_ID) -> Run:
        run = self._bootstrap_run(
            session_id,
            user_request="Compare INVALID_DUPLICATE and DEMO_B in 2024-01.",
        )
        # Importing INVALID_DUPLICATE.csv is expected to fail at the
        # dataset service; we surface its DUPLICATE_DATE error through the
        # run state without requiring a successful inspect_dataset call.
        metadata = DatasetMetadata(
            asset_id="INVALID_DUPLICATE",
            source_name="repository synthetic example",
            price_basis=PriceBasis.FORWARD_ADJUSTED,
            currency="CNY",
            frequency="daily",
            calendar_label="synthetic weekdays",
            daily_series_complete=True,
            is_synthetic=True,
        )
        path = EXAMPLES_DIR / "INVALID_DUPLICATE.csv"
        result = self._datasets.import_csv(
            path.read_bytes(), metadata=metadata, session_id=session_id
        )
        if result.dataset is not None:
            raise RuntimeError("Expected INVALID_DUPLICATE.csv to be rejected by import_csv.")
        # Pick the first error code from the quality report.
        first_error = next(
            (issue for issue in result.quality_report.issues if issue.severity.value == "error"),
            None,
        )
        if first_error is None:
            raise RuntimeError("Expected at least one error-level quality issue.")
        self._runs.mark_failed(
            run.run_id,
            session_id,
            code=first_error.code,
            message=first_error.message,
            retryable=False,
            details={"row_numbers": list(first_error.row_numbers)},
        )
        return self._runs.get_run(run.run_id, session_id)

    def run_all(self, session_id: str = DEFAULT_SESSION_ID) -> tuple[Run, ...]:
        return (
            self.run_two_asset(session_id),
            self.run_single_asset(session_id),
            self.run_duplicate_date_failure(session_id),
        )

    # -- helpers -----------------------------------------------------------

    def _run_compare(
        self,
        *,
        session_id: str,
        user_request: str,
        dataset_files: tuple[tuple[str, str], ...],
    ) -> Run:
        run = self._bootstrap_run(session_id, user_request=user_request)
        dataset_ids = [
            self._import_dataset(filename, asset_id, session_id)
            for filename, asset_id in dataset_files
        ]
        for ds_id in dataset_ids:
            self._runs.add_dataset(run.run_id, session_id, ds_id)
        self._execute_pipeline(
            run_id=run.run_id,
            session_id=session_id,
            dataset_ids=dataset_ids,
        )
        return self._runs.get_run(run.run_id, session_id)

    def _bootstrap_run(self, session_id: str, *, user_request: str) -> Run:
        return self._runs.create_run(
            session_id=session_id,
            mode=RunMode.DEMO,
            user_request=user_request,
        )

    def _import_dataset(self, filename: str, asset_id: str, session_id: str) -> str:
        metadata = DatasetMetadata(
            asset_id=asset_id,
            source_name="repository synthetic example",
            price_basis=PriceBasis.FORWARD_ADJUSTED,
            currency="CNY",
            frequency="daily",
            calendar_label="synthetic weekdays",
            daily_series_complete=True,
            is_synthetic=True,
        )
        path = EXAMPLES_DIR / filename
        result = self._datasets.import_csv(
            path.read_bytes(), metadata=metadata, session_id=session_id
        )
        assert result.dataset is not None, f"Demo scenario requires a clean dataset: {filename}"
        self.dataset_store.save(result.dataset, session_id)
        return result.dataset.manifest.dataset_id

    def _execute_pipeline(
        self,
        *,
        run_id: str,
        session_id: str,
        dataset_ids: list[str],
        requested_start: str = "2024-01-02",
        requested_end: str = "2024-01-15",
        requested_metrics: tuple[str, ...] = (
            MetricName.PERIOD_RETURN.value,
            MetricName.MAX_DRAWDOWN.value,
        ),
    ) -> list[ToolResultEnvelope]:
        envelopes: list[ToolResultEnvelope] = []

        for ds_id in dataset_ids:
            env = self._registry.execute(
                run_id=run_id,
                session_id=session_id,
                tool_name="inspect_dataset",
                arguments={"dataset_id": ds_id},
            )
            envelopes.append(env)

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
        envelopes.append(env)
        if not env.ok:
            return envelopes
        analysis_id = env.data["analysis_id"]

        env = self._registry.execute(
            run_id=run_id,
            session_id=session_id,
            tool_name="compute_metrics",
            arguments={"analysis_id": analysis_id},
        )
        envelopes.append(env)
        if not env.ok:
            return envelopes
        metrics_id = env.data["metrics_id"]

        env = self._registry.execute(
            run_id=run_id,
            session_id=session_id,
            tool_name="create_charts",
            arguments={
                "analysis_id": analysis_id,
                "kinds": [
                    ChartKind.NORMALIZED_PRICES.value,
                    ChartKind.DRAWDOWN.value,
                ],
            },
        )
        envelopes.append(env)
        if not env.ok:
            return envelopes
        chart_ids = env.data["chart_ids"]

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
        envelopes.append(env)
        return envelopes


def default_demo_controller(runs_dir: Path) -> DemoController:
    """Compose the full stack and return a ready-to-run demo controller."""
    runs_dir = Path(runs_dir).resolve()
    dataset_store = LocalDatasetStore(runs_dir)
    run_store = LocalRunStore(runs_dir)
    chart_store = LocalChartStore(runs_dir)
    report_store = LocalReportStore(runs_dir)
    dataset_service = DatasetService()
    analysis_service = AnalysisService()
    run_service = RunService(run_store)
    chart_service = ChartService(
        chart_store=chart_store, plot_service=PlotService(), run_service=run_service
    )
    report_service = ReportService(report_store=report_store, run_service=run_service)
    from quantlab_agent.agent.tools import default_registry

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
    return DemoController(
        runs_dir=runs_dir,
        registry=registry,
        run_service=run_service,
        dataset_service=dataset_service,
        dataset_store=dataset_store,
        chart_store=chart_store,
        report_store=report_store,
    )


__all__ = ["DemoController", "default_demo_controller"]
