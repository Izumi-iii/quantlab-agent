"""PlanValidator — resolves ``AnalysisPlan`` references and clamps dates.

Sitting between the ``Planner`` and ``PlanExecutor``, the validator:

* Resolves user-facing ``dataset_refs`` (asset_ids, filenames, or
  UUIDs) to current-session ``dataset_id`` UUIDs via
  ``LocalDatasetStore.list_in_session``.
* Clamps the requested ``date_range`` to the union of dataset
  coverage.
* Short-circuits ``out_of_scope`` to a dedicated error type.
* Wraps ``clarify`` intent in a ``ClarificationRequest`` so the
  executor does not run any tools.

The validator never touches ``RunStore``; it only inspects the
``DatasetStore`` to resolve references. ``PlanExecutor`` is
responsible for persisting the resolved plan onto the run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol
from uuid import UUID

from quantlab_agent.domain.errors import ErrorCode, QuantLabError
from quantlab_agent.domain.models import (
    AnalysisPlan,
    DateRange,
    Intent,
    ResolvedPlan,
)


class ClarificationRequest(Exception):
    """Planner emitted ``intent=clarify``; no tools should run."""

    def __init__(self, question: str, *, summary: str = "") -> None:
        super().__init__(question)
        self.question = question
        self.summary = summary


class OutOfScopeError(QuantLabError):
    """Planner (or pre-gate) decided the request is out of scope."""

    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.OUT_OF_SCOPE, message, retryable=False)


# ---------------------------------------------------------------------------
# Dataset resolver — minimal protocol so we don't depend on the concrete store.
# ---------------------------------------------------------------------------


class DatasetResolver(Protocol):
    def list_in_session(self, session_id: str) -> list[dict[str, Any]]: ...


# ---------------------------------------------------------------------------
# PlanValidator
# ---------------------------------------------------------------------------


@dataclass
class PlanValidator:
    """Validate and resolve an ``AnalysisPlan``."""

    resolver: DatasetResolver

    def validate(
        self,
        plan: AnalysisPlan,
        *,
        session_id: str,
    ) -> ResolvedPlan | ClarificationRequest | OutOfScopeError:
        if plan.intent is Intent.OUT_OF_SCOPE:
            return OutOfScopeError("超出范围：我目前只处理已上传 CSV 的历史价格数据分析。")

        if plan.intent is Intent.CLARIFY:
            assert plan.clarifying_question is not None  # AnalysisPlan enforces it
            return ClarificationRequest(plan.clarifying_question, summary=plan.user_visible_summary)

        available = list(self.resolver.list_in_session(session_id))
        if not available:
            raise QuantLabError(
                ErrorCode.INVALID_ARGUMENT,
                "No datasets imported in this session — upload at least one CSV first.",
            )

        resolved_ids = self._resolve_dataset_refs(plan.dataset_refs, available)
        if not resolved_ids:
            raise QuantLabError(
                ErrorCode.INVALID_ARGUMENT,
                "Plan did not name any dataset and no fallback is available.",
            )

        effective_start, effective_end = self._resolve_date_range(
            plan.date_range, resolved_ids, available
        )

        summary = self._build_plan_summary(plan, resolved_ids, available)
        return ResolvedPlan(
            intent=plan.intent,
            resolved_dataset_ids=tuple(resolved_ids),
            date_range=plan.date_range,
            effective_start=effective_start,
            effective_end=effective_end,
            metrics=plan.metrics,
            charts=plan.charts,
            rolling_windows=plan.rolling_windows,
            extras=plan.extras,
            clarifying_question=plan.clarifying_question,
            user_visible_summary=plan.user_visible_summary,
            plan_summary=summary,
        )

    # -- helpers ------------------------------------------------------------

    @staticmethod
    def _resolve_dataset_refs(
        refs: tuple[str, ...],
        available: list[dict[str, Any]],
    ) -> list[str]:
        if not available:
            return []
        by_asset: dict[str, str] = {item["asset_id"]: item["dataset_id"] for item in available}
        by_uuid: dict[str, str] = {item["dataset_id"]: item["dataset_id"] for item in available}

        if not refs:
            return [item["dataset_id"] for item in available]

        resolved: list[str] = []
        seen: set[str] = set()
        for ref in refs:
            stripped = ref.strip()
            if not stripped:
                continue
            # Direct UUID lookup first.
            if stripped in by_uuid:
                if stripped not in seen:
                    resolved.append(stripped)
                    seen.add(stripped)
                continue
            # asset_id lookup (case-insensitive).
            key = next((k for k in by_asset if k.lower() == stripped.lower()), None)
            if key is not None:
                ds_id = by_asset[key]
                if ds_id not in seen:
                    resolved.append(ds_id)
                    seen.add(ds_id)
                continue
            # Filename-style ref (e.g. "DEMO_A.csv"): strip suffix.
            base = stripped.rsplit(".", 1)[0] if "." in stripped else stripped
            key = next((k for k in by_asset if k.lower() == base.lower()), None)
            if key is not None:
                ds_id = by_asset[key]
                if ds_id not in seen:
                    resolved.append(ds_id)
                    seen.add(ds_id)
                continue
            # Unknown reference — silently drop. The validator does not
            # raise here so the planner can recover on its next pass;
            # the executor will see zero resolved IDs and the upstream
            # check will raise INVALID_ARGUMENT.
        # Unknown references are silently dropped. If all named refs were
        # unknown, return an empty list so the caller can raise one stable
        # INVALID_ARGUMENT error.
        if not resolved:
            return []
        return resolved

    @staticmethod
    def _resolve_date_range(
        requested: DateRange | None,
        resolved_ids: list[str],
        available: list[dict[str, Any]],
    ) -> tuple[date | None, date | None]:
        if not resolved_ids:
            return (None, None)
        by_id = {item["dataset_id"]: item for item in available}
        coverage = [by_id[ds_id] for ds_id in resolved_ids if ds_id in by_id]
        if not coverage:
            return (None, None)
        coverage_min = min(date.fromisoformat(item["date_min"]) for item in coverage)
        coverage_max = max(date.fromisoformat(item["date_max"]) for item in coverage)
        if requested is None:
            return coverage_min, coverage_max
        requested_start = requested.start
        requested_end = requested.end
        effective_start = max(requested_start, coverage_min)
        effective_end = min(requested_end, coverage_max)
        if effective_start > effective_end:
            return coverage_min, coverage_max
        return effective_start, effective_end

    @staticmethod
    def _build_plan_summary(
        plan: AnalysisPlan,
        resolved_ids: list[str],
        available: list[dict[str, Any]],
    ) -> str:
        from quantlab_agent.domain.models import AnalysisExtra

        by_id = {item["dataset_id"]: item for item in available}
        asset_labels = [by_id[ds]["asset_id"] for ds in resolved_ids if ds in by_id]
        target = ", ".join(asset_labels) if asset_labels else "the imported datasets"
        if plan.intent is Intent.DATA_QUALITY:
            return f"Inspecting data quality for {target}."
        if plan.intent is Intent.PROFILE:
            return f"Profiling {target}."
        if plan.intent is Intent.METRICS:
            base = f"Computing metrics for {target}."
            if AnalysisExtra.DESCRIBE_PRICE_SERIES in plan.extras:
                base += " Will also describe the price series."
            return base
        if plan.intent is Intent.CHART:
            chart_list = ", ".join(c.value for c in plan.charts) or "default charts"
            return f"Creating {chart_list} for {target}."
        if plan.intent is Intent.REPORT:
            return f"Building a Markdown report for {target}."
        return f"Plan ready for {target}."

    @staticmethod
    def is_uuid(value: str) -> bool:
        try:
            UUID(value)
            return True
        except ValueError:
            return False


__all__ = [
    "PlanValidator",
    "ClarificationRequest",
    "OutOfScopeError",
    "DatasetResolver",
]
