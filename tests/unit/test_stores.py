"""Unit tests for the local store adapters."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from quantlab_agent.adapters.local_stores import (
    LocalChartStore,
    LocalDatasetStore,
    LocalReportStore,
    LocalRunStore,
)
from quantlab_agent.application.datasets import DatasetService
from quantlab_agent.domain.errors import ErrorCode, QuantLabError
from quantlab_agent.domain.models import (
    ChartArtifact,
    ChartKind,
    DatasetMetadata,
    PriceBasis,
    ReportArtifact,
    ReportSection,
    Run,
    RunBudget,
    RunMode,
    RunStatus,
)
from quantlab_agent.domain.policies import DEFAULT_RUN_BUDGET

SESSION_A = "00000000-0000-4000-8000-000000000001"
SESSION_B = "00000000-0000-4000-8000-000000000002"
RUN_ID = "11111111-1111-4111-8111-111111111111"
DATASET_ID = "66666666-6666-4666-8666-666666666666"
CHART_ID = "22222222-2222-4222-8222-222222222222"
REPORT_ID = "44444444-4444-4444-8444-444444444444"
ANALYSIS_ID = "33333333-3333-4333-8333-333333333333"
METRICS_ID = "55555555-5555-4555-8555-555555555555"


def _budget() -> RunBudget:
    return RunBudget(
        max_model_interactions=DEFAULT_RUN_BUDGET.max_model_interactions,
        max_tool_executions=DEFAULT_RUN_BUDGET.max_tool_executions,
        max_same_validation_retry=DEFAULT_RUN_BUDGET.max_same_validation_retry,
        max_retryable_network_errors=DEFAULT_RUN_BUDGET.max_retryable_network_errors,
        per_request_timeout_seconds=DEFAULT_RUN_BUDGET.per_request_timeout_seconds,
        total_deadline_seconds=DEFAULT_RUN_BUDGET.total_deadline_seconds,
    )


def _import_demo(asset_id: str = "DEMO_A") -> object:
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
    content = b"date,close\n2024-01-02,100\n2024-01-03,101\n2024-01-04,99\n"
    result = DatasetService().import_csv(content, metadata=metadata, session_id=SESSION_A)
    assert result.dataset is not None
    return result.dataset


def _make_run() -> Run:
    return Run(
        run_id=RUN_ID,
        session_id=SESSION_A,
        mode=RunMode.DEMO,
        status=RunStatus.RUNNING,
        user_request="compare DEMO_A vs DEMO_B in 2024-01",
        dataset_ids=(DATASET_ID,),
        budgets=_budget(),
        created_at=datetime.now(UTC),
    )


def _chart_artifact() -> ChartArtifact:
    return ChartArtifact(
        chart_id=CHART_ID,
        run_id=RUN_ID,
        analysis_id=ANALYSIS_ID,
        kind=ChartKind.NORMALIZED_PRICES,
        png_path="charts/foo/normalized_prices.png",
        data_path="charts/foo/normalized_prices.json",
        data_sha256="0" * 64,
        title="Normalized prices",
        x_label="date",
        y_label="price (base=100)",
        series_labels=("DEMO_A",),
        created_at=datetime.now(UTC),
    )


def _report_artifact() -> ReportArtifact:
    return ReportArtifact(
        report_id=REPORT_ID,
        run_id=RUN_ID,
        analysis_id=ANALYSIS_ID,
        metrics_id=METRICS_ID,
        chart_ids=(CHART_ID,),
        section_ids=(ReportSection.OVERVIEW,),
        evidence_refs=(),
        markdown_path="reports/foo/report.md",
        created_at=datetime.now(UTC),
    )


# --- dataset store -------------------------------------------------------


def test_dataset_round_trip(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path)
    dataset = _import_demo()
    store.save(dataset, SESSION_A)

    fetched = store.get(dataset.manifest.dataset_id, SESSION_A)
    assert fetched.manifest.dataset_id == dataset.manifest.dataset_id
    assert [p.close for p in fetched.points] == [100.0, 101.0, 99.0]


def test_dataset_get_rejects_wrong_session(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path)
    dataset = _import_demo()
    store.save(dataset, SESSION_A)

    with pytest.raises(QuantLabError) as error:
        store.get(dataset.manifest.dataset_id, SESSION_B)
    assert error.value.code is ErrorCode.UNKNOWN_REFERENCE


def test_dataset_list_in_session_returns_summaries(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path)
    dataset = _import_demo()
    store.save(dataset, SESSION_A)

    items = store.list_in_session(SESSION_A)

    assert items == [
        {
            "dataset_id": dataset.manifest.dataset_id,
            "asset_id": "DEMO_A",
            "date_min": "2024-01-02",
            "date_max": "2024-01-04",
            "row_count": 3,
        }
    ]


def test_dataset_invalid_id_rejected(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path)
    with pytest.raises(QuantLabError) as error:
        store.get("../escape", SESSION_A)
    assert error.value.code is ErrorCode.UNKNOWN_REFERENCE


def test_atomic_write_no_tmp_left(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path)
    dataset = _import_demo()
    store.save(dataset, SESSION_A)

    leftovers = list(tmp_path.rglob("*.tmp"))
    assert leftovers == []


def test_atomic_write_preserves_binary_payload(tmp_path: Path) -> None:
    """Under Python 3.14 on Windows, ``os.open`` defaults to text mode and
    silently rewrites every LF to CRLF — which corrupts binary formats
    like PNG. ``_atomic_write_bytes`` must explicitly pass ``os.O_BINARY``
    so payloads reach disk byte-for-byte unchanged.
    """
    from quantlab_agent.adapters.local_stores import _atomic_write_bytes

    target = tmp_path / "binary.bin"
    # Standard PNG signature + a chunk with several LF bytes inside it.
    payload = b"\x89PNG\r\n\x1a\n" + b"\x00\x01\x02\n\x03\nrest\n"

    _atomic_write_bytes(target, payload)

    on_disk = target.read_bytes()
    assert on_disk == payload, (
        f"_atomic_write_bytes corrupted the payload:\n"
        f"  in : {payload[:16]!r}\n"
        f"  out: {on_disk[:16]!r}"
    )


# --- run store ------------------------------------------------------------


def test_run_create_get_round_trip(tmp_path: Path) -> None:
    store = LocalRunStore(tmp_path)
    store.create(_make_run())

    fetched = store.get(RUN_ID, SESSION_A)
    assert fetched.run_id == RUN_ID
    assert fetched.status is RunStatus.RUNNING


def test_run_transition_cas_blocks_mismatched(tmp_path: Path) -> None:
    store = LocalRunStore(tmp_path)
    store.create(_make_run())

    store.transition(
        RUN_ID,
        SESSION_A,
        expected_status=RunStatus.RUNNING,
        new_status=RunStatus.SUCCEEDED,
    )

    with pytest.raises(QuantLabError) as error:
        store.transition(
            RUN_ID,
            SESSION_A,
            expected_status=RunStatus.RUNNING,
            new_status=RunStatus.SUCCEEDED,
        )
    assert error.value.code is ErrorCode.STALE_RUN


def test_run_increment_tool_executions(tmp_path: Path) -> None:
    store = LocalRunStore(tmp_path)
    store.create(_make_run())

    after = store.increment_tool_executions(RUN_ID, SESSION_A)
    assert after.counters.tool_executions_used == 1


def test_run_session_isolation(tmp_path: Path) -> None:
    store = LocalRunStore(tmp_path)
    store.create(_make_run())

    with pytest.raises(QuantLabError) as error:
        store.get(RUN_ID, SESSION_B)
    assert error.value.code is ErrorCode.UNKNOWN_REFERENCE


# --- chart / report store -------------------------------------------------


def test_chart_save_and_get(tmp_path: Path) -> None:
    run_store = LocalRunStore(tmp_path)
    chart_store = LocalChartStore(tmp_path)
    run_store.create(_make_run())

    chart = _chart_artifact()
    chart_store.save(
        chart,
        session_id=SESSION_A,
        png_bytes=b"\x89PNG\r\n\x1a\n" + b"x" * 200,
        data_payload={"series": []},
    )

    fetched = chart_store.get(chart.chart_id, SESSION_A, RUN_ID)
    assert fetched.chart_id == chart.chart_id
    assert fetched.kind is ChartKind.NORMALIZED_PRICES


def test_chart_get_rejects_wrong_session(tmp_path: Path) -> None:
    run_store = LocalRunStore(tmp_path)
    chart_store = LocalChartStore(tmp_path)
    run_store.create(_make_run())

    chart = _chart_artifact()
    chart_store.save(
        chart,
        session_id=SESSION_A,
        png_bytes=b"\x89PNG\r\n\x1a\n" + b"x" * 200,
        data_payload={"series": []},
    )

    with pytest.raises(QuantLabError) as error:
        chart_store.get(chart.chart_id, SESSION_B, RUN_ID)
    assert error.value.code is ErrorCode.UNKNOWN_REFERENCE


def test_report_save_and_get(tmp_path: Path) -> None:
    run_store = LocalRunStore(tmp_path)
    report_store = LocalReportStore(tmp_path)
    run_store.create(_make_run())

    report = _report_artifact()
    report_store.save(report, session_id=SESSION_A, markdown="# Hello")

    fetched = report_store.get(REPORT_ID, SESSION_A, RUN_ID)
    assert fetched.report_id == REPORT_ID
    assert report_store.get_markdown_path(REPORT_ID, SESSION_A, RUN_ID).endswith("report.md")


def test_report_rejects_wrong_session(tmp_path: Path) -> None:
    run_store = LocalRunStore(tmp_path)
    report_store = LocalReportStore(tmp_path)
    run_store.create(_make_run())

    report = _report_artifact()
    report_store.save(report, session_id=SESSION_A, markdown="# Hello")

    with pytest.raises(QuantLabError) as error:
        report_store.get(REPORT_ID, SESSION_B, RUN_ID)
    assert error.value.code is ErrorCode.UNKNOWN_REFERENCE


def test_path_traversal_in_dataset_id_rejected(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path)
    with pytest.raises(QuantLabError) as error:
        store.get("..", SESSION_A)
    assert error.value.code is ErrorCode.UNKNOWN_REFERENCE


def test_list_in_session_empty_when_no_data(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path)
    assert store.list_in_session(SESSION_A) == []


def test_list_in_session_returns_summaries_sorted(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path)
    # Import two datasets — manifests are sorted alphabetically on disk
    # so the listing should be stable regardless of save order.
    ds_a = _import_demo(asset_id="DEMO_A")
    ds_b = _import_demo(asset_id="DEMO_B")
    store.save(ds_a, SESSION_A)
    store.save(ds_b, SESSION_A)

    items = store.list_in_session(SESSION_A)
    assert [item["asset_id"] for item in items] == ["DEMO_A", "DEMO_B"]
    # Each summary carries the four fields the tool layer exposes.
    first = items[0]
    assert set(first.keys()) == {
        "dataset_id",
        "asset_id",
        "date_min",
        "date_max",
        "row_count",
    }
    assert first["dataset_id"] == ds_a.manifest.dataset_id
    assert first["row_count"] == 3


def test_list_in_session_isolated_per_session(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path)
    ds = _import_demo(asset_id="DEMO_A")
    store.save(ds, SESSION_A)

    # SESSION_B has no data even though SESSION_A does.
    assert store.list_in_session(SESSION_B) == []
    assert len(store.list_in_session(SESSION_A)) == 1


def test_list_in_session_skips_dirs_without_manifest(tmp_path: Path) -> None:
    """A stray dataset directory (no manifest.json) must be ignored
    rather than crash the listing — the disk layout may contain
    half-written directories from interrupted runs.
    """
    store = LocalDatasetStore(tmp_path)
    # Real dataset
    ds = _import_demo(asset_id="DEMO_A")
    store.save(ds, SESSION_A)
    # Stray directory: looks like a dataset but has no manifest.
    stray = tmp_path / SESSION_A / "datasets" / "00000000-0000-4000-8000-000000000abc"
    stray.mkdir(parents=True)
    (stray / "normalized.csv").write_text("date,close\n2024-01-02,1\n")

    items = store.list_in_session(SESSION_A)
    assert [item["asset_id"] for item in items] == ["DEMO_A"]


def test_list_in_session_rejects_non_uuid_session_id(tmp_path: Path) -> None:
    store = LocalDatasetStore(tmp_path)
    with pytest.raises(QuantLabError) as error:
        store.list_in_session("not-a-uuid")
    assert error.value.code is ErrorCode.UNKNOWN_REFERENCE
