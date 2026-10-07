"""Unit tests for PlanValidator."""

from __future__ import annotations

import pytest

from quantlab_agent.agent.plan_validator import (
    ClarificationRequest,
    OutOfScopeError,
    PlanValidator,
)
from quantlab_agent.domain.errors import QuantLabError
from quantlab_agent.domain.models import (
    AnalysisPlan,
    DateRange,
    Intent,
    MetricName,
    ResolvedPlan,
)


class _StubResolver:
    def __init__(self, items):
        self._items = items

    def list_in_session(self, session_id: str):
        return self._items


A_ID = "0" * 8 + "-0000-4000-8000-" + "0" * 12 + "0001"
B_ID = "0" * 8 + "-0000-4000-8000-" + "0" * 12 + "0002"


def _resolver_two() -> _StubResolver:
    return _StubResolver(
        [
            {
                "dataset_id": A_ID,
                "asset_id": "DEMO_A",
                "date_min": "2024-01-02",
                "date_max": "2024-01-15",
                "row_count": 10,
            },
            {
                "dataset_id": B_ID,
                "asset_id": "DEMO_B",
                "date_min": "2024-01-02",
                "date_max": "2024-01-15",
                "row_count": 10,
            },
        ]
    )


def _resolver_single() -> _StubResolver:
    return _StubResolver(
        [
            {
                "dataset_id": A_ID,
                "asset_id": "DEMO_A",
                "date_min": "2024-02-01",
                "date_max": "2024-02-15",
                "row_count": 8,
            },
        ]
    )


def test_validator_out_of_scope_short_circuits() -> None:
    plan = AnalysisPlan(intent=Intent.OUT_OF_SCOPE, user_visible_summary="nope")
    result = PlanValidator(resolver=_resolver_two()).validate(plan, session_id="x")
    assert isinstance(result, OutOfScopeError)


def test_validator_clarify_returns_question() -> None:
    plan = AnalysisPlan(
        intent=Intent.CLARIFY,
        clarifying_question="which?",
        user_visible_summary="...",
    )
    result = PlanValidator(resolver=_resolver_two()).validate(plan, session_id="x")
    assert isinstance(result, ClarificationRequest)
    assert result.question == "which?"


def test_validator_resolves_asset_id_to_uuid() -> None:
    plan = AnalysisPlan(
        intent=Intent.METRICS,
        dataset_refs=("DEMO_A",),
        date_range=DateRange(start="2024-01-02", end="2024-01-15"),
        metrics=(MetricName.MAX_DRAWDOWN,),
    )
    resolved = PlanValidator(resolver=_resolver_two()).validate(plan, session_id="x")
    assert isinstance(resolved, ResolvedPlan)
    assert resolved.resolved_dataset_ids == (A_ID,)


def test_validator_resolves_uuid_directly() -> None:
    plan = AnalysisPlan(
        intent=Intent.METRICS,
        dataset_refs=(A_ID,),
        metrics=(MetricName.PERIOD_RETURN,),
    )
    resolved = PlanValidator(resolver=_resolver_two()).validate(plan, session_id="x")
    assert resolved.resolved_dataset_ids == (A_ID,)


def test_validator_resolves_filename_with_csv_suffix() -> None:
    plan = AnalysisPlan(
        intent=Intent.METRICS,
        dataset_refs=("DEMO_A.csv",),
        metrics=(MetricName.PERIOD_RETURN,),
    )
    resolved = PlanValidator(resolver=_resolver_two()).validate(plan, session_id="x")
    assert resolved.resolved_dataset_ids == (A_ID,)


def test_validator_clamps_date_range_to_coverage() -> None:
    plan = AnalysisPlan(
        intent=Intent.METRICS,
        dataset_refs=("DEMO_A",),
        date_range=DateRange(start="2023-01-01", end="2023-12-31"),
        metrics=(MetricName.PERIOD_RETURN,),
    )
    resolved = PlanValidator(resolver=_resolver_two()).validate(plan, session_id="x")
    assert resolved.effective_start is not None
    assert resolved.effective_end is not None
    # Coverage for DEMO_A is 2024-01-02..2024-01-15; requested range is fully outside.
    # Validator should clamp to coverage.
    assert resolved.effective_start.isoformat() == "2024-01-02"
    assert resolved.effective_end.isoformat() == "2024-01-15"


def test_validator_single_dataset_with_no_refs_falls_back() -> None:
    plan = AnalysisPlan(intent=Intent.DATA_QUALITY, dataset_refs=(), user_visible_summary="check")
    resolved = PlanValidator(resolver=_resolver_single()).validate(plan, session_id="x")
    assert resolved.resolved_dataset_ids == (A_ID,)


def test_validator_multi_dataset_with_no_refs_uses_all_available() -> None:
    plan = AnalysisPlan(intent=Intent.DATA_QUALITY, dataset_refs=(), user_visible_summary="check")
    resolved = PlanValidator(resolver=_resolver_two()).validate(plan, session_id="x")
    assert resolved.resolved_dataset_ids == (A_ID, B_ID)


def test_validator_no_datasets_raises_invalid_argument() -> None:
    plan = AnalysisPlan(intent=Intent.DATA_QUALITY, dataset_refs=(), user_visible_summary="check")
    empty_resolver = _StubResolver([])
    with pytest.raises(QuantLabError) as excinfo:
        PlanValidator(resolver=empty_resolver).validate(plan, session_id="x")
    assert excinfo.value.code.value == "INVALID_ARGUMENT"


def test_validator_unknown_ref_multi_dataset_returns_no_resolved() -> None:
    plan = AnalysisPlan(
        intent=Intent.METRICS,
        dataset_refs=("UNKNOWN",),
        metrics=(MetricName.PERIOD_RETURN,),
    )
    with pytest.raises(QuantLabError):
        PlanValidator(resolver=_resolver_two()).validate(plan, session_id="x")
