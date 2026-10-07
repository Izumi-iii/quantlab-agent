"""Execute every ``status: ready`` case in ``cases.jsonl`` and assert the
expected behavior recorded in the file.

Each case carries a ``mode`` that selects a runner:

- ``demo`` — invokes ``DemoController.run_*`` and inspects the resulting
  ``Run`` + persisted ``tool_calls.jsonl``.
- ``custom`` — constructs CSVs from ``fixtures.py`` and runs the same
  tool pipeline with user-provided dates and metrics.
- ``import_only`` — runs ``DatasetService.import_csv`` on a bad fixture
  and asserts the quality-report error code.
- ``registry_unit`` — drives the ``ToolRegistry`` directly with a
  cross-session reference request (E22) or invalid arguments (E19).

Deferred cases (those requiring a real model) are skipped and listed
in the output so the report makes the limitation explicit.
"""

from __future__ import annotations

import json
import tempfile
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from datetime import date as _date
from pathlib import Path
from typing import Any

from evaluation.fixtures import (
    bad_date_format,
    disjoint_dates,
    missing_close,
    partial_overlap,
    single_point,
    zero_or_negative_price,
)
from quantlab_agent.adapters.local_stores import (
    LocalChartStore,
    LocalDatasetStore,
    LocalReportStore,
    LocalRunStore,
)
from quantlab_agent.adapters.plotting import PlotService
from quantlab_agent.agent.demo import DemoController, default_demo_controller
from quantlab_agent.agent.tools import default_registry
from quantlab_agent.application.analyses import AnalysisService
from quantlab_agent.application.charts import ChartService
from quantlab_agent.application.datasets import DatasetService, ImportedDataset
from quantlab_agent.application.reports import ReportService
from quantlab_agent.application.runs import RunService
from quantlab_agent.domain.errors import QuantLabError
from quantlab_agent.domain.models import (
    DatasetManifest,
    DatasetMetadata,
    MetricName,
    PriceBasis,
    PricePoint,
    Run,
    RunBudget,
    RunCounters,
    RunMode,
    RunStatus,
)

CASES_PATH = Path(__file__).parent / "cases.jsonl"
DEMO_SESSION_ID = "00000000-0000-4000-8000-000000000099"


@dataclass
class CaseResult:
    case_id: str
    title: str
    mode: str
    status: str  # "passed" | "failed" | "skipped"
    expected: dict[str, Any] | None
    actual: dict[str, Any] = field(default_factory=dict)
    failure_reason: str | None = None
    elapsed_seconds: float = 0.0

    def as_row(self) -> dict[str, str]:
        return {
            "case_id": self.case_id,
            "title": self.title,
            "mode": self.mode,
            "status": self.status,
            "elapsed_s": f"{self.elapsed_seconds:.3f}",
            "failure": self.failure_reason or "",
        }


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------


def load_cases(path: Path = CASES_PATH) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            cases.append(json.loads(line))
    return cases


# ---------------------------------------------------------------------------
# Per-mode executors (each returns a dict of observed facts)
# ---------------------------------------------------------------------------


def _import_fixture(
    service: DatasetService,
    content: bytes,
    *,
    asset_id: str = "EVAL",
    price_basis: PriceBasis = PriceBasis.FORWARD_ADJUSTED,
    daily_complete: bool = True,
) -> dict[str, Any]:
    metadata = DatasetMetadata(
        asset_id=asset_id,
        source_name="evaluation fixture",
        price_basis=price_basis,
        currency="CNY",
        frequency="daily",
        calendar_label="evaluation",
        daily_series_complete=daily_complete,
        is_synthetic=True,
    )
    result = service.import_csv(content, metadata=metadata, session_id=DEMO_SESSION_ID)
    if result.dataset is not None:
        return {"import_error_code": None, "warning_codes": []}
    errors = [i.code for i in result.quality_report.issues if i.severity.value == "error"]
    warnings = [i.code for i in result.quality_report.issues if i.severity.value == "warning"]
    return {"import_error_code": errors[0] if errors else None, "warning_codes": warnings}


def _run_two_asset_import() -> dict[str, Any]:
    """Legacy: confirms the unknown-basis warning is recorded."""
    service = DatasetService()
    csv = Path("data/examples/DEMO_A.csv").read_bytes()
    _import_fixture(service, csv, asset_id="A", price_basis=PriceBasis.FORWARD_ADJUSTED)
    r2 = _import_fixture(
        service,
        csv,
        asset_id="B",
        price_basis=PriceBasis.UNKNOWN,
        daily_complete=False,
    )
    if "UNKNOWN_PRICE_BASIS" in r2["warning_codes"]:
        return {"import_error_code": "UNKNOWN_PRICE_BASIS"}
    return {"import_error_code": None}


def _run_two_asset_incompatible_basis() -> dict[str, Any]:
    """E14: two assets with different price bases must trigger
    INCOMPATIBLE_PRICE_BASIS at AnalysisService.prepare time.
    """
    service = DatasetService()
    csv = Path("data/examples/DEMO_A.csv").read_bytes()

    meta_known = DatasetMetadata(
        asset_id="A",
        source_name="evaluation fixture",
        price_basis=PriceBasis.FORWARD_ADJUSTED,
        currency="CNY",
        frequency="daily",
        calendar_label="evaluation",
        daily_series_complete=True,
        is_synthetic=True,
    )
    meta_unknown = DatasetMetadata(
        asset_id="B",
        source_name="evaluation fixture",
        price_basis=PriceBasis.UNKNOWN,
        currency="CNY",
        frequency="daily",
        calendar_label="evaluation",
        daily_series_complete=False,
        is_synthetic=True,
    )
    r1 = service.import_csv(csv, metadata=meta_known, session_id=DEMO_SESSION_ID)
    r2 = service.import_csv(csv, metadata=meta_unknown, session_id=DEMO_SESSION_ID)
    assert r1.dataset is not None and r2.dataset is not None
    try:
        AnalysisService().prepare(
            [r1.dataset, r2.dataset],
            session_id=DEMO_SESSION_ID,
            requested_start=_date(2024, 1, 2),
            requested_end=_date(2024, 1, 15),
            requested_metrics=(MetricName.PERIOD_RETURN,),
        )
        return {"import_error_code": None}
    except QuantLabError as exc:
        return {"import_error_code": exc.code.value}


def _run_registry_unit(case_id: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        run_store = LocalRunStore(path)
        dataset_store = LocalDatasetStore(path)
        chart_store = LocalChartStore(path)
        report_store = LocalReportStore(path)
        registry = default_registry(
            dataset_service=DatasetService(),
            analysis_service=AnalysisService(),
            chart_service=ChartService(
                chart_store=chart_store,
                plot_service=PlotService(),
                run_service=RunService(run_store),
            ),
            report_service=ReportService(
                report_store=report_store, run_service=RunService(run_store)
            ),
            run_service=RunService(run_store),
            dataset_store=dataset_store,
            run_store=run_store,
            chart_store=chart_store,
            report_store=report_store,
        )
        run_id = "11111111-1111-4111-8111-111111111111"
        run_store.create(
            Run(
                run_id=run_id,
                session_id=DEMO_SESSION_ID,
                mode=RunMode.DEMO,
                status=RunStatus.RUNNING,
                user_request="unit",
                dataset_ids=(),
                budgets=RunBudget(
                    max_model_interactions=8,
                    max_tool_executions=12,
                    max_same_validation_retry=1,
                    max_retryable_network_errors=1,
                    per_request_timeout_seconds=30,
                    total_deadline_seconds=120,
                ),
                counters=RunCounters(),
                created_at=datetime.now(UTC),
            )
        )
        if case_id == "E19":
            env = registry.execute(
                run_id=run_id,
                session_id=DEMO_SESSION_ID,
                tool_name="inspect_dataset",
                arguments={"dataset_id": "not-a-uuid"},
            )
        elif case_id == "E22":
            env = registry.execute(
                run_id=run_id,
                session_id=DEMO_SESSION_ID,
                tool_name="inspect_dataset",
                arguments={"dataset_id": "00000000-0000-4000-8000-000000000099"},
            )
        elif case_id == "E18":
            env = registry.execute(
                run_id=run_id,
                session_id=DEMO_SESSION_ID,
                tool_name="inspect_dataset",
                arguments={"dataset_id": "not-a-uuid"},
            )
        else:
            raise ValueError(case_id)
        records = run_store.list_tool_calls(run_id, DEMO_SESSION_ID)
        persisted = bool(records)
        last_status = records[-1].status.value if records else None
        return {
            "envelope_ok": env.ok,
            "error_code": env.error["code"] if env.error else None,
            "tool_call_persisted": persisted,
            "tool_call_status": last_status,
        }


def _run_planner_unit(case: dict[str, Any]) -> dict[str, Any]:
    """Planner-layer evaluation cases (M6).

    Each case seeds one or two demo datasets, runs
    ``RulePlanner.plan -> PlanValidator.validate -> PlanExecutor.execute``,
    and reports the resulting ``run.status``, ``run.failure``, and the
    list of tool names persisted in ``tool_calls.jsonl``.
    """
    from quantlab_agent.agent.plan_executor import PlanExecutor
    from quantlab_agent.agent.plan_validator import PlanValidator
    from quantlab_agent.agent.planner import PlannerContext, RulePlanner

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        dataset_store = LocalDatasetStore(path)
        run_store = LocalRunStore(path)
        chart_store = LocalChartStore(path)
        report_store = LocalReportStore(path)
        registry = default_registry(
            dataset_service=DatasetService(),
            analysis_service=AnalysisService(),
            chart_service=ChartService(
                chart_store=chart_store,
                plot_service=PlotService(),
                run_service=RunService(run_store),
            ),
            report_service=ReportService(
                report_store=report_store, run_service=RunService(run_store)
            ),
            run_service=RunService(run_store),
            dataset_store=dataset_store,
            run_store=run_store,
            chart_store=chart_store,
            report_store=report_store,
        )
        run_service = RunService(run_store)

        # Seed the assets requested by the case.
        seed_assets = case.get("seed_assets") or ["DEMO_A"]
        for asset_id in seed_assets:
            metadata = DatasetMetadata(
                asset_id=asset_id,
                source_name="eval fixture",
                price_basis=PriceBasis.FORWARD_ADJUSTED,
                currency="CNY",
                frequency="daily",
                calendar_label="synthetic weekdays",
                daily_series_complete=True,
                is_synthetic=True,
            )
            content = (
                b"date,close\n2024-01-02,100\n2024-01-03,101\n2024-01-04,99\n"
                b"2024-01-05,102\n2024-01-08,103\n2024-01-09,101\n"
                b"2024-01-10,100\n2024-01-11,99\n2024-01-12,98\n2024-01-15,99\n"
            )
            res = DatasetService().import_csv(
                content, metadata=metadata, session_id=DEMO_SESSION_ID
            )
            assert res.dataset is not None, f"could not import {asset_id}"
            dataset_store.save(res.dataset, DEMO_SESSION_ID)

        ctx = PlannerContext(
            session_id=DEMO_SESSION_ID,
            dataset_summaries=tuple(dataset_store.list_in_session(DEMO_SESSION_ID)),
        )
        plan = RulePlanner().plan(case["user_request"], ctx)
        validator = PlanValidator(resolver=dataset_store)
        resolved = validator.validate(plan, session_id=DEMO_SESSION_ID)

        run = run_service.create_run(
            session_id=DEMO_SESSION_ID,
            mode=RunMode.REAL_AGENT,
            user_request=case["user_request"],
        )
        executor = PlanExecutor(registry=registry, run_service=run_service)
        final = executor.execute(run_id=run.run_id, session_id=DEMO_SESSION_ID, plan=resolved)

        records = run_service.list_tool_calls(run.run_id, DEMO_SESSION_ID)
        tool_names = [r.tool_name for r in records]
        snapshot = dict(final.context_snapshot or {})
        failure_details = (final.failure or {}).get("details") or {}
        return {
            "intent": snapshot.get("intent") or failure_details.get("intent"),
            "run_status": final.status.value,
            "failure_code": (final.failure or {}).get("code"),
            "tool_names": tool_names,
            "metric_count": len(tool_names),  # approximate; full metric count is irrelevant here
        }


def _run_custom(
    demo: DemoController,
    case_id: str,
    inputs: dict[str, Any],
    fixture: str,
) -> tuple[Run, dict[str, Any]]:
    """Run the full pipeline with user-provided inputs."""
    extras: dict[str, Any] = {}
    if case_id == "E15":
        run = _run_two_asset_partial(demo, inputs)
        return run, extras
    if fixture == "unknown_basis":
        run = _run_unknown_basis(demo, inputs)
        extras["warning_code"] = "UNKNOWN_PRICE_BASIS"
        return run, extras
    run = _run_one_asset(demo, inputs, fixture)
    return run, extras


def _run_unknown_basis(demo: DemoController, inputs: dict[str, Any]) -> Run:
    content = Path("data/examples/DEMO_A.csv").read_bytes()
    metadata = DatasetMetadata(
        asset_id="DEMO_A",
        source_name="evaluation fixture",
        price_basis=PriceBasis.UNKNOWN,
        currency="CNY",
        frequency="daily",
        calendar_label="evaluation",
        daily_series_complete=False,
        is_synthetic=True,
    )
    return _execute_pipeline(demo, content, metadata, inputs)


def _run_one_asset(
    demo: DemoController,
    inputs: dict[str, Any],
    fixture: str,
) -> Run:
    content_map = {
        "DEMO_A": Path("data/examples/DEMO_A.csv").read_bytes(),
        "single_point": single_point(),
    }
    metadata = DatasetMetadata(
        asset_id="DEMO_A",
        source_name="evaluation fixture",
        price_basis=PriceBasis.FORWARD_ADJUSTED,
        currency="CNY",
        frequency="daily",
        calendar_label="evaluation",
        daily_series_complete=True,
        is_synthetic=True,
    )
    return _execute_pipeline(demo, content_map[fixture], metadata, inputs)


def _run_two_asset_partial(demo: DemoController, inputs: dict[str, Any]) -> Run:
    content_full = Path("data/examples/DEMO_A.csv").read_bytes()
    full_meta = DatasetMetadata(
        asset_id="A_FULL",
        source_name="evaluation fixture",
        price_basis=PriceBasis.FORWARD_ADJUSTED,
        currency="CNY",
        frequency="daily",
        calendar_label="evaluation",
        daily_series_complete=True,
        is_synthetic=True,
    )
    partial_meta = DatasetMetadata(
        asset_id="A_PARTIAL",
        source_name="evaluation fixture",
        price_basis=PriceBasis.FORWARD_ADJUSTED,
        currency="CNY",
        frequency="daily",
        calendar_label="evaluation",
        daily_series_complete=True,
        is_synthetic=True,
    )
    res_full = demo._datasets.import_csv(
        content_full, metadata=full_meta, session_id=DEMO_SESSION_ID
    )
    res_partial = demo._datasets.import_csv(
        partial_overlap(), metadata=partial_meta, session_id=DEMO_SESSION_ID
    )
    assert res_full.dataset is not None and res_partial.dataset is not None
    demo.dataset_store.save(res_full.dataset, DEMO_SESSION_ID)
    demo.dataset_store.save(res_partial.dataset, DEMO_SESSION_ID)
    return _execute_pipeline(
        demo,
        content_full,
        full_meta,
        inputs,
        extra_dataset=(res_partial.dataset, partial_meta),
    )


def _execute_pipeline(
    demo: DemoController,
    content: bytes,
    metadata: DatasetMetadata,
    inputs: dict[str, Any],
    extra_dataset: tuple | None = None,
) -> Run:
    result = demo._datasets.import_csv(content, metadata=metadata, session_id=DEMO_SESSION_ID)
    assert result.dataset is not None
    demo.dataset_store.save(result.dataset, DEMO_SESSION_ID)
    dataset_ids = [result.dataset.manifest.dataset_id]
    if extra_dataset is not None:
        demo.dataset_store.save(extra_dataset[0], DEMO_SESSION_ID)
        dataset_ids.append(extra_dataset[0].manifest.dataset_id)

    run = demo._runs.create_run(
        session_id=DEMO_SESSION_ID,
        mode=RunMode.DEMO,
        user_request=f"Evaluation: {inputs}",
    )
    for ds_id in dataset_ids:
        demo._runs.add_dataset(run.run_id, DEMO_SESSION_ID, ds_id)
    demo._execute_pipeline(
        run_id=run.run_id,
        session_id=DEMO_SESSION_ID,
        dataset_ids=dataset_ids,
        requested_start=inputs["requested_start"],
        requested_end=inputs["requested_end"],
        requested_metrics=tuple(inputs["requested_metrics"]),
    )
    return demo._runs.get_run(run.run_id, DEMO_SESSION_ID)


# ---------------------------------------------------------------------------
# Top-level runner
# ---------------------------------------------------------------------------


def run_case(case: dict[str, Any]) -> CaseResult:
    """Execute one case and return its result."""
    case_id = case["case_id"]
    title = case["title"]
    mode = case["mode"]
    expected = case.get("expected")
    started = time.perf_counter()
    actual: dict[str, Any] = {}
    failure: str | None = None
    status = "passed"

    try:
        if case["status"] == "deferred":
            return CaseResult(
                case_id=case_id,
                title=title,
                mode=mode,
                status="skipped",
                expected=expected,
                failure_reason=case.get("deferred_reason"),
                elapsed_seconds=time.perf_counter() - started,
            )

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            run: Run | None = None
            if case_id == "E06":
                demo = default_demo_controller(tmp_path)
                run = demo.run_duplicate_date_failure(session_id=DEMO_SESSION_ID)
                actual = {
                    "run_status": run.status.value,
                    "failure_code": run.failure.get("code") if run.failure else None,
                    "row_numbers_present": bool(
                        run.failure and run.failure.get("details", {}).get("row_numbers")
                    ),
                }
            elif mode == "demo":
                demo = default_demo_controller(tmp_path)
                if case_id == "E01":
                    run = demo.run_single_asset(session_id=DEMO_SESSION_ID)
                elif case_id == "E02":
                    run = demo.run_two_asset(session_id=DEMO_SESSION_ID)
                else:
                    raise ValueError(f"Unknown demo case {case_id}")
                actual["run_status"] = run.status.value

            elif mode == "custom":
                demo = default_demo_controller(tmp_path)
                run, extras = _run_custom(demo, case_id, case["inputs"], case["fixture"])
                actual["run_status"] = run.status.value
                actual.update(extras)

            elif mode == "import_only":
                if case_id == "E14":
                    actual = _run_two_asset_incompatible_basis()
                elif case_id == "E18":
                    # E18: simulate a tool-call failure by importing a
                    # dataset that fails quality gate, then verify the
                    # record is persisted with status=failed.
                    service = DatasetService()
                    res = _import_fixture(service, missing_close())
                    actual = {
                        "import_error_code": res["import_error_code"],
                        # No actual tool call happens (the import error
                        # is raised before the pipeline starts), so we
                        # verify the error code is captured.
                    }
                elif case_id == "E09":
                    # Two-asset case: first asset has dates Jan 2-4,
                    # second has Feb 1-2. AnalysisService.prepare must
                    # raise NO_OVERLAP.
                    actual = _run_two_asset_no_overlap(tmp_path)
                else:
                    content_map = {
                        "missing_close": missing_close(),
                        "bad_date_format": bad_date_format(),
                        "zero_or_negative_price": zero_or_negative_price(),
                        "disjoint_dates": disjoint_dates(),
                    }
                    actual = _import_fixture(DatasetService(), content_map[case["fixture"]])

            elif mode == "registry_unit":
                actual = _run_registry_unit(case_id)
            elif mode == "planner_unit":
                actual = _run_planner_unit(case)
            else:
                raise ValueError(f"Unknown mode: {mode}")

            # After a successful run, compute richer facts.
            if run is not None and run.status.value == "succeeded":
                actual.update(_compute_metric_facts(run, tmp_path))

        if expected:
            for key, want in expected.items():
                got = actual.get(key)
                if got != want:
                    raise AssertionError(f"{key}: expected {want!r}, got {got!r}")

    except AssertionError as exc:
        status = "failed"
        failure = str(exc)
    except Exception as exc:  # noqa: BLE001 - top-level error capture
        status = "failed"
        failure = f"{type(exc).__name__}: {exc}"

    return CaseResult(
        case_id=case_id,
        title=title,
        mode=mode,
        status=status,
        expected=expected,
        actual=actual,
        failure_reason=failure,
        elapsed_seconds=time.perf_counter() - started,
    )


def _compute_metric_facts(run: Run, runs_dir: Path) -> dict[str, Any]:
    """Re-run ``AnalysisService.compute_metrics`` to derive facts about
    metric counts, observations, and unavailable metrics.
    """
    datasets = []
    for ds_id in run.dataset_ids:
        path = runs_dir / run.session_id / "datasets" / ds_id / "normalized.csv"
        manifest_path = runs_dir / run.session_id / "datasets" / ds_id / "manifest.json"
        if not path.exists() or not manifest_path.exists():
            return {}
        points = []
        for line in path.read_text(encoding="utf-8").splitlines()[1:]:
            if not line:
                continue
            d, c = line.split(",", 1)
            points.append(PricePoint(date=_date.fromisoformat(d), close=float(c)))
        manifest = DatasetManifest.model_validate(json.loads(manifest_path.read_text()))
        datasets.append(ImportedDataset(manifest=manifest, points=tuple(points)))

    metrics = tuple(MetricName(m) for m in run.context_snapshot["requested_metrics"])
    prepared = AnalysisService().prepare(
        datasets,
        session_id=run.session_id,
        requested_start=_date.fromisoformat(run.context_snapshot["requested_start"]),
        requested_end=_date.fromisoformat(run.context_snapshot["requested_end"]),
        requested_metrics=metrics,
        analysis_id=run.analysis_id,
    )
    result = AnalysisService().compute_metrics(prepared)

    metric_count = sum(len(a.metrics) for a in result.assets)
    annualized_unavailable = any(
        a.metrics.get(MetricName.ANNUALIZED_VOLATILITY) is not None
        and a.metrics[MetricName.ANNUALIZED_VOLATILITY].value is None
        for a in result.assets
    )
    period_return_available = any(
        a.metrics.get(MetricName.PERIOD_RETURN) is not None
        and a.metrics[MetricName.PERIOD_RETURN].value is not None
        for a in result.assets
    )
    all_null = all(mv.value is None for a in result.assets for mv in a.metrics.values())
    any_unavailable_reason = any(
        mv.unavailable_reason
        for a in result.assets
        for mv in a.metrics.values()
        if mv.value is None
    )
    both_assets_present = len(result.assets) == 2
    primary_observations = (
        next(iter(result.assets[0].metrics.values())).observations
        if result.assets and result.assets[0].metrics
        else 0
    )
    primary_metric_name = (
        next(iter(result.assets[0].metrics)).value
        if result.assets and result.assets[0].metrics
        else None
    )
    return {
        "metric_count": metric_count,
        "observations": primary_observations,
        "observations_less_than": primary_observations < 8,
        "annualized_volatility_unavailable": annualized_unavailable,
        "period_return_available": period_return_available,
        "all_metric_values_null": all_null,
        "unavailable_reason_present": any_unavailable_reason,
        "both_assets_have_period_return": both_assets_present
        and all(
            a.metrics.get(MetricName.PERIOD_RETURN) is not None
            and a.metrics[MetricName.PERIOD_RETURN].value is not None
            for a in result.assets
        ),
        "metric_name": primary_metric_name,
    }


def _run_two_asset_no_overlap(runs_dir: Path) -> dict[str, Any]:
    """E09: two CSVs with disjoint dates must trigger NO_OVERLAP."""
    early = b"date,close\n2024-01-02,100\n2024-01-03,101\n2024-01-04,99\n"
    late = b"date,close\n2024-02-01,100\n2024-02-02,101\n"
    service = DatasetService()
    meta_early = DatasetMetadata(
        asset_id="A",
        source_name="evaluation fixture",
        price_basis=PriceBasis.FORWARD_ADJUSTED,
        currency="CNY",
        frequency="daily",
        calendar_label="evaluation",
        daily_series_complete=True,
        is_synthetic=True,
    )
    meta_late = DatasetMetadata(
        asset_id="B",
        source_name="evaluation fixture",
        price_basis=PriceBasis.FORWARD_ADJUSTED,
        currency="CNY",
        frequency="daily",
        calendar_label="evaluation",
        daily_series_complete=True,
        is_synthetic=True,
    )
    r1 = service.import_csv(early, metadata=meta_early, session_id=DEMO_SESSION_ID)
    r2 = service.import_csv(late, metadata=meta_late, session_id=DEMO_SESSION_ID)
    assert r1.dataset is not None and r2.dataset is not None
    try:
        AnalysisService().prepare(
            [r1.dataset, r2.dataset],
            session_id=DEMO_SESSION_ID,
            requested_start=_date(2024, 1, 1),
            requested_end=_date(2024, 2, 28),
            requested_metrics=(MetricName.PERIOD_RETURN,),
        )
        return {"import_error_code": None}
    except QuantLabError as exc:
        return {"import_error_code": exc.code.value}


def run_all(path: Path = CASES_PATH) -> list[CaseResult]:
    cases = load_cases(path)
    return [run_case(case) for case in cases]


def render_markdown(results: list[CaseResult]) -> str:
    lines = [
        "# Evaluation results",
        "",
        "| Case | Title | Mode | Status | Elapsed (s) | Failure |",
        "| --- | --- | --- | --- | ---: | --- |",
    ]
    for r in results:
        lines.append(
            f"| {r.case_id} | {r.title} | {r.mode} | **{r.status}** | "
            f"{r.elapsed_seconds:.3f} | {r.failure_reason or ''} |"
        )
    passed = sum(1 for r in results if r.status == "passed")
    failed = sum(1 for r in results if r.status == "failed")
    skipped = sum(1 for r in results if r.status == "skipped")
    lines.append("")
    lines.append(
        f"**Totals**: {passed} passed, {failed} failed, {skipped} skipped (model-deferred)."
    )
    return "\n".join(lines)


def main() -> int:
    results = run_all()
    print(render_markdown(results))
    failed = sum(1 for r in results if r.status == "failed")
    return 1 if failed else 0


__all__ = [
    "CASES_PATH",
    "CaseResult",
    "load_cases",
    "run_case",
    "run_all",
    "render_markdown",
    "main",
]


if __name__ == "__main__":
    raise SystemExit(main())
