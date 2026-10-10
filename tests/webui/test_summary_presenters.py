"""Unit tests for ``webui.summary_presenters``."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from quantlab_agent.domain.models import (
    AssetSeriesSummary,
    ColumnProfile,
    DatasetProfile,
    Intent,
    PriceSeriesSummary,
    Provenance,
    Run,
    RunBudget,
    RunCounters,
    RunMode,
    ToolCallRecord,
    ToolResultEnvelope,
    ToolStatus,
)
from webui.summary_presenters import (
    summarize_describe,
    summarize_metrics,
    summarize_profile,
    summarize_run,
)


def _make_run(intent: str | None, extras: tuple[str, ...] = ()) -> Run:
    snapshot: dict[str, Any] = {}
    if intent is not None:
        snapshot["intent"] = intent
    if extras:
        snapshot["extras"] = list(extras)
    return Run(
        run_id="00000000-0000-4000-8000-000000000001",
        session_id="s",
        mode=RunMode.REAL_AGENT,
        status="running",  # type: ignore[arg-type]
        user_request="x",
        dataset_ids=(),
        analysis_id=None,
        metrics_id=None,
        chart_ids=(),
        report_id=None,
        budgets=RunBudget(
            max_model_interactions=8,
            max_tool_executions=12,
            max_same_validation_retry=1,
            max_retryable_network_errors=1,
            per_request_timeout_seconds=30,
            total_deadline_seconds=120,
        ),
        counters=RunCounters(),
        context_snapshot=snapshot,
        created_at=datetime.now(UTC),
    )


def _record(tool_name: str, data: dict[str, Any] | None) -> ToolCallRecord:
    return ToolCallRecord(
        tool_call_id="t",
        run_id="r",
        tool_name=tool_name,
        arguments_redacted={},
        status=ToolStatus.SUCCEEDED,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        result_envelope=ToolResultEnvelope(
            ok=True,
            run_id="r",
            tool_call_id="t",
            data=data or {},
            warnings=(),
            error=None,
            provenance=Provenance(session_id="s", run_id="r", dataset_ids=()),
        ),
    )


def test_summarize_profile_returns_human_readable_text() -> None:
    payload = DatasetProfile(
        schema_version="profile-v1",
        dataset_id="x",
        asset_id="DEMO_A",
        row_count=10,
        columns=(
            ColumnProfile(
                name="date",
                semantic_type="date",
                missing_count=0,
                unique_count=10,
                min="2024-01-02",
                max="2024-01-15",
            ),
            ColumnProfile(
                name="close",
                semantic_type="numeric_price",
                missing_count=0,
                unique_count=10,
                min=99.0,
                max=110.0,
                mean=104.5,
                std=2.5,
            ),
        ),
        quality_summary={"error_count": 0, "warning_count": 0, "top_issues": []},
    ).model_dump(mode="json")
    run = _make_run(Intent.PROFILE.value)
    text = summarize_profile(run, (_record("profile_dataset", payload),))
    assert "DEMO_A" in text
    assert "10" in text
    assert "2024-01-02" in text
    assert "2024-01-15" in text
    assert "99.00" in text or "99.0" in text
    assert "110.00" in text or "110.0" in text


def test_summarize_describe_returns_per_asset_stats() -> None:
    payload = PriceSeriesSummary(
        schema_version="describe-v1",
        analysis_id="a",
        effective_start="2024-01-02",
        effective_end="2024-01-15",
        alignment_policy="single_asset_dates",
        assets=(
            AssetSeriesSummary(
                asset_id="DEMO_A",
                start_price=100.0,
                end_price=108.9,
                min_price=99.0,
                min_price_date="2024-01-04",
                max_price=110.0,
                max_price_date="2024-01-03",
                total_return=0.089,
                up_days=2,
                down_days=1,
                flat_days=0,
                max_daily_gain=0.1,
                max_daily_gain_date="2024-01-03",
                max_daily_loss=-0.1,
                max_daily_loss_date="2024-01-04",
                longest_up_streak=1,
                longest_down_streak=1,
            ),
        ),
        assumptions="",
    ).model_dump(mode="json")
    run = _make_run(Intent.METRICS.value, extras=(Intent.METRICS.value,))
    text = summarize_describe(run, (_record("describe_price_series", payload),))
    assert "DEMO_A" in text
    assert "+8.90%" in text
    assert "2024-01-02" in text


def test_summarize_metrics_handles_null_values() -> None:
    payload = {
        "analysis_id": "a",
        "assets": [
            {
                "asset_id": "DEMO_A",
                "metrics": {
                    "period_return": {
                        "value": 0.05,
                        "observations": 10,
                    },
                    "annualized_volatility": {
                        "value": None,
                        "observations": 0,
                        "unavailable_reason": "Insufficient data",
                    },
                },
            }
        ],
    }
    text = summarize_metrics(
        _make_run(Intent.METRICS.value), (_record("compute_metrics", payload),)
    )
    assert "DEMO_A" in text
    assert "Insufficient data" in text


def test_summarize_run_dispatches_to_profile_for_new_intent() -> None:
    payload = DatasetProfile(
        schema_version="profile-v1",
        dataset_id="x",
        asset_id="DEMO_A",
        row_count=2,
        columns=(
            ColumnProfile(
                name="date",
                semantic_type="date",
                missing_count=0,
                unique_count=2,
                min="2024-01-02",
                max="2024-01-03",
            ),
            ColumnProfile(
                name="close",
                semantic_type="numeric_price",
                missing_count=0,
                unique_count=2,
                min=100.0,
                max=101.0,
            ),
        ),
        quality_summary={"error_count": 0, "warning_count": 0, "top_issues": []},
    ).model_dump(mode="json")
    run = _make_run(Intent.PROFILE.value)
    text = summarize_run(run, (_record("profile_dataset", payload),))
    assert text is not None
    assert "DEMO_A" in text


def test_summarize_run_returns_none_for_legacy_intents() -> None:
    run = _make_run(Intent.METRICS.value)
    text = summarize_run(run, ())
    assert text is None


def test_summarize_anomalies_reports_total_and_examples() -> None:
    payload = {
        "analysis_id": "a",
        "asset_anomalies": [
            (
                "DEMO_A",
                [
                    {
                        "date": "2024-01-08",
                        "kind": "extreme_positive_return",
                        "severity": "warning",
                        "value": 0.5,
                        "message": "big move",
                    },
                    {
                        "date": "2024-01-15",
                        "kind": "extreme_negative_return",
                        "severity": "warning",
                        "value": -0.2,
                        "message": "big drop",
                    },
                ],
            )
        ],
        "parameters": {"mad_k": 3.5, "absolute_threshold": 0.15, "gap_threshold_days": 10.0},
    }
    from webui.summary_presenters import summarize_anomalies

    run = _make_run(Intent.DATA_QUALITY.value, extras=("anomalies",))
    text = summarize_anomalies(run, (_record("detect_anomalies", payload),))
    assert text is not None
    assert "DEMO_A" in text
    assert "2024-01-08" in text


def test_summarize_risk_includes_sharpe_var_cvar_calmar() -> None:
    payload = {
        "analysis_id": "a",
        "annualization_factor": 252,
        "risk_free_rate": 0.0,
        "confidence_level": 0.95,
        "assets": [
            {
                "asset_id": "DEMO_A",
                "values": {
                    "sharpe_ratio": 1.2,
                    "sortino_ratio": 1.5,
                    "calmar_ratio": 0.8,
                    "var_95": 0.02,
                    "cvar_95": 0.03,
                    "mean_daily_return": 0.0005,
                    "std_daily_return": 0.01,
                    "annualized_return": 0.13,
                },
                "unavailable": {},
            }
        ],
        "assumptions": "",
    }
    from webui.summary_presenters import summarize_risk

    run = _make_run(Intent.METRICS.value, extras=("risk",))
    text = summarize_risk(run, (_record("compute_risk_metrics", payload),))
    assert text is not None
    assert "Sharpe" in text
    assert "VaR95" in text
    assert "CVaR95" in text
    assert "Calmar" in text


def test_summarize_rolling_reports_windows_and_regime_note() -> None:
    payload = {
        "analysis_id": "a",
        "windows": [20, 60, 252],
        "series": [
            {
                "asset_id": "DEMO_A",
                "metric": "rolling_volatility",
                "window": 60,
                "points": [
                    {"date": "2024-01-02", "value": 0.10},
                    {"date": "2024-01-03", "value": 0.11},
                    {"date": "2024-01-04", "value": 0.10},
                    {"date": "2024-01-05", "value": 0.12},
                    {"date": "2024-01-08", "value": 0.11},
                    {"date": "2024-01-22", "value": 0.30},
                ],
            },
            {
                "asset_id": "DEMO_A",
                "metric": "rolling_return",
                "window": 20,
                "points": [
                    {"date": "2024-01-22", "value": 0.02},
                    {"date": "2024-01-23", "value": 0.03},
                ],
            },
        ],
    }
    from webui.summary_presenters import summarize_rolling

    run = _make_run(Intent.CHART.value, extras=("rolling",))
    text = summarize_rolling(run, (_record("compute_rolling_metrics", payload),))
    assert text is not None
    assert "60" in text
    assert "30.00%" in text
