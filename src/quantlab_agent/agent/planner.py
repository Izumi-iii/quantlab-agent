"""Planner layer — converts natural language into ``AnalysisPlan``.

This sits between the user-facing request (CLI / WebUI) and the tool
registry. The planner never touches files or datasets directly; it
produces a structured ``AnalysisPlan`` which the
``PlanValidator`` then resolves and ``PlanExecutor`` then runs.

Two implementations:

- ``RulePlanner``: deterministic keyword/pattern matching. Used as the
  default fallback (and as the WebUI demo), and as the test
  backbone — every intent has a predictable mapping.
- ``LLMPlanner``: drives a real ``ModelProvider`` to emit a JSON plan.
  Used when the user has configured ``QUANTLAB_MODEL_*`` env vars.

The Protocol is intentionally minimal so a third backend (e.g. a
scripted ``FakePlanner``) can be plugged in for tests.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from quantlab_agent.agent.controller import is_supported_analysis_request
from quantlab_agent.domain.models import (
    AnalysisPlan,
    ChartKind,
    Intent,
    MetricName,
)

# ---------------------------------------------------------------------------
# Prompts for LLMPlanner — kept small and explicit.
# ---------------------------------------------------------------------------

PLANNER_SYSTEM_PROMPT = (
    "You are QuantLab Planner, a routing component that turns natural-language "
    "analysis requests into a structured JSON plan. The plan decides which "
    "deterministic tool chain to run. You NEVER compute numbers yourself. "
    "Respond with one JSON object and nothing else — no prose, no markdown.\n\n"
    "Schema:\n"
    "{\n"
    '  "intent": "data_quality" | "metrics" | "chart" | "report" | "clarify" | "out_of_scope",\n'
    '  "dataset_refs": ["DEMO_A", "DEMO_B", ...],   // empty means "all in session"\n'
    '  "date_range": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} | null,\n'
    '  "metrics": ["period_return", "annualized_volatility", "max_drawdown"],\n'
    '  "charts": ["normalized_prices", "drawdown"],\n'
    '  "clarifying_question": string | null,   // only when intent=clarify\n'
    '  "user_visible_summary": string          // 1-2 sentence agent message\n'
    "}\n\n"
    "Intent rules:\n"
    "- data_quality: user only asks about quality / inspection / sanity\n"
    "- metrics: user wants computed numbers; omit charts unless asked\n"
    "- chart: user asks to draw/plot/show a trend chart without needing metric numbers\n"
    "- report: user explicitly asks for a full report\n"
    "- clarify: request is missing essential info; ask ONE short question in clarifying_question\n"
    "- out_of_scope: request is unrelated to CSV price analysis\n"
    "If you do not know the user's intent, prefer clarify."
)

PLANNER_USER_PROMPT_TEMPLATE = (
    "Session datasets: {dataset_summaries}\n\nUser request: {user_request}\n\nPlan:"
)


class PlannerError(RuntimeError):
    """Raised when the planner cannot produce a usable plan."""


# ---------------------------------------------------------------------------
# Planner Protocol
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PlannerContext:
    """Lightweight context passed to ``Planner.plan``.

    ``dataset_summaries`` is a list of ``{dataset_id, asset_id,
    date_min, date_max, row_count}`` dicts — the same shape
    ``LocalDatasetStore.list_in_session`` returns. The planner should
    never see more than this.
    """

    session_id: str
    dataset_summaries: tuple[dict[str, Any], ...]


class Planner(Protocol):
    """Translate ``user_request`` into an ``AnalysisPlan``."""

    def plan(self, user_request: str, context: PlannerContext) -> AnalysisPlan: ...


# ---------------------------------------------------------------------------
# RulePlanner — deterministic keyword matching.
# ---------------------------------------------------------------------------


# Keywords in priority order: more specific intents come first.
_DATA_QUALITY_PATTERNS = (
    r"数据质量",
    r"quality",
    r"检查数据",
    r"检查.{0,16}数据",
    r"check.{0,16}data",
    r"看一下.{0,16}数据",
    r"看一下.{0,16}质量",
)

_REPORT_PATTERNS = (
    r"生成报告",
    r"build.{0,4}report",
    r"full.{0,4}report",
    r"完整报告",
    r"做一个.{0,30}报告",
)

_METRIC_PATTERNS = (
    r"指标",
    r"metrics?",
    r"收益",
    r"return",
    r"回撤",
    r"drawdown",
    r"波动",
    r"volatility",
    r"比较",
    r"compare",
)

_COMPARE_ONLY_PATTERNS = (
    r"走势",
    r"趋势",
    r"对比一下",
    r"看一下.{0,8}走势",
    r"画一下",
    r"compare.{0,8}trend",
    r"compare.{0,8}chart",
)

_CHART_PATTERNS = (
    r"图表",
    r"图形",
    r"趋势图",
    r"走势图",
    r"画图",
    r"作图",
    r"生成.{0,8}图",
    r"plot",
    r"chart",
    r"graph",
    r"trend",
)

_CLARIFY_TRIGGERS = (
    r"分析一下$",  # bare "analyze" with no target
    r"看看$",  # bare "take a look"
    r"^分析$",
    r"^看一下$",
)


_METRIC_NAME_KEYWORDS: tuple[tuple[str, MetricName], ...] = (
    ("区间收益", MetricName.PERIOD_RETURN),
    ("period_return", MetricName.PERIOD_RETURN),
    ("最大回撤", MetricName.MAX_DRAWDOWN),
    ("max_drawdown", MetricName.MAX_DRAWDOWN),
    ("年化波动", MetricName.ANNUALIZED_VOLATILITY),
    ("annualized_volatility", MetricName.ANNUALIZED_VOLATILITY),
    ("波动率", MetricName.ANNUALIZED_VOLATILITY),
    ("volatility", MetricName.ANNUALIZED_VOLATILITY),
)


_ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def _match_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE) for p in patterns)


def _extract_dates(text: str) -> tuple[str, str] | None:
    matches = _ISO_DATE.findall(text)
    if len(matches) >= 2:
        start, end = matches[0], matches[1]
        if start <= end:
            return start, end
    return None


def _extract_metrics(text: str) -> tuple[MetricName, ...]:
    found: list[MetricName] = []
    seen: set[MetricName] = set()
    lowered = text.lower()
    for keyword, metric in _METRIC_NAME_KEYWORDS:
        if keyword.lower() in lowered and metric not in seen:
            seen.add(metric)
            found.append(metric)
    return tuple(found)


def _extract_chart_kinds(text: str) -> tuple[ChartKind, ...]:
    found: list[ChartKind] = []
    seen: set[ChartKind] = set()
    lowered = text.lower()
    if "归一化" in lowered or "normalized" in lowered:
        found.append(ChartKind.NORMALIZED_PRICES)
        seen.add(ChartKind.NORMALIZED_PRICES)
    if "回撤" in lowered or "drawdown" in lowered:
        if ChartKind.DRAWDOWN not in seen:
            found.append(ChartKind.DRAWDOWN)
            seen.add(ChartKind.DRAWDOWN)
    return tuple(found)


def _extract_dataset_refs(text: str, available: tuple[dict[str, Any], ...]) -> tuple[str, ...]:
    """Return asset_ids that appear in the user text, in declared order.

    If the user mentions nothing concrete and only one dataset is in
    the session, default to it. Otherwise we leave the tuple empty —
    the validator falls back to "use every dataset in the session".
    """
    if not available:
        return ()
    seen: set[str] = set()
    matches: list[str] = []
    for summary in available:
        asset_id = summary["asset_id"]
        if asset_id.lower() in text.lower() and asset_id not in seen:
            seen.add(asset_id)
            matches.append(asset_id)
    if not matches and len(available) == 1:
        return (available[0]["asset_id"],)
    return tuple(matches)


class RulePlanner:
    """Deterministic planner — keyword matching only, no model call."""

    def plan(self, user_request: str, context: PlannerContext) -> AnalysisPlan:
        text = user_request.strip()
        if not text:
            raise PlannerError("user_request is empty")

        if not is_supported_analysis_request(text):
            return AnalysisPlan(
                intent=Intent.OUT_OF_SCOPE,
                user_visible_summary=(
                    "Out of scope. This agent only handles historical CSV price analysis."
                ),
            )

        available = context.dataset_summaries
        dataset_refs = _extract_dataset_refs(text, available)
        metrics = _extract_metrics(text)
        chart_kinds = _extract_chart_kinds(text)
        has_metric_signal = bool(metrics) or _match_any(text, _METRIC_PATTERNS)
        has_chart_signal = (
            bool(chart_kinds)
            or _match_any(text, _COMPARE_ONLY_PATTERNS)
            or _match_any(text, _CHART_PATTERNS)
        )
        has_number_metric_signal = bool(metrics) or _match_any(
            text,
            (
                r"指标",
                r"metrics?",
                r"收益",
                r"return",
                r"波动",
                r"volatility",
            ),
        )

        # Decide intent by precedence. data_quality wins over the
        # "which dataset?" clarification when the user has signalled it
        # explicitly — the request is unambiguous about *what* to do.

        if _match_any(text, _DATA_QUALITY_PATTERNS) and not metrics and not chart_kinds:
            return AnalysisPlan(
                intent=Intent.DATA_QUALITY,
                dataset_refs=dataset_refs,
                user_visible_summary=(
                    "I'll check the quality of the imported datasets without running any metrics."
                ),
            )

        # If the request has no dataset in scope AND no metrics/charts
        # have been signalled, ask which dataset(s).
        if (
            not dataset_refs
            and len(available) > 1
            and not has_metric_signal
            and not has_chart_signal
        ):
            return AnalysisPlan(
                intent=Intent.CLARIFY,
                clarifying_question=(
                    "Which datasets should I analyze? "
                    f"Available: {', '.join(s['asset_id'] for s in available)}."
                ),
                user_visible_summary=("I can analyze any combination of the imported datasets."),
            )

        # Bare "分析一下" / "看一下" with no target → ask for clarification.
        if not metrics and not chart_kinds and _match_any(text, _CLARIFY_TRIGGERS):
            return AnalysisPlan(
                intent=Intent.CLARIFY,
                clarifying_question=(
                    "What would you like me to analyze? "
                    "Please specify the metric (period return, max drawdown, "
                    "annualized volatility) and the date range."
                ),
                user_visible_summary="I need more detail before I can analyze.",
            )

        if _match_any(text, _REPORT_PATTERNS):
            date_range = self._maybe_date_payload(text)
            return AnalysisPlan(
                intent=Intent.REPORT,
                dataset_refs=dataset_refs,
                date_range=date_range,
                metrics=metrics
                or (
                    MetricName.PERIOD_RETURN,
                    MetricName.MAX_DRAWDOWN,
                ),
                charts=chart_kinds
                or (
                    ChartKind.NORMALIZED_PRICES,
                    ChartKind.DRAWDOWN,
                ),
                user_visible_summary=(
                    "I'll prepare a full Markdown report with metrics and charts."
                ),
            )

        if has_chart_signal and not has_number_metric_signal:
            date_range = self._maybe_date_payload(text)
            return AnalysisPlan(
                intent=Intent.CHART,
                dataset_refs=dataset_refs,
                date_range=date_range,
                charts=chart_kinds or (ChartKind.NORMALIZED_PRICES,),
                user_visible_summary=("I'll create the requested trend chart."),
            )

        if has_metric_signal or has_chart_signal:
            date_range = self._maybe_date_payload(text)
            return AnalysisPlan(
                intent=Intent.METRICS,
                dataset_refs=dataset_refs,
                date_range=date_range,
                metrics=metrics
                or (
                    MetricName.PERIOD_RETURN,
                    MetricName.MAX_DRAWDOWN,
                ),
                user_visible_summary=("I'll compute the requested metrics over the date range."),
            )

        # Fallback: ask for clarification.
        return AnalysisPlan(
            intent=Intent.CLARIFY,
            clarifying_question=(
                "I could not determine the analysis intent. "
                "Could you specify the dataset(s), date range, and metrics?"
            ),
            user_visible_summary="I need more detail to choose the right analysis path.",
        )

    @staticmethod
    def _maybe_date_payload(text: str):  # noqa: ANN205 - returns optional DateRange
        from quantlab_agent.domain.models import DateRange

        dates = _extract_dates(text)
        if dates is None:
            return None
        return DateRange(start=dates[0], end=dates[1])


# ---------------------------------------------------------------------------
# LLMPlanner — drives a real model provider.
# ---------------------------------------------------------------------------


class LLMPlanner:
    """Use a ``ModelProvider`` to ask the LLM for an ``AnalysisPlan`` JSON."""

    def __init__(
        self,
        *,
        model_provider: Any,
        tool_format_helpers: tuple[Any, ...] = (),
    ) -> None:
        self._model = model_provider
        # tool_format_helpers is reserved for future use — currently the
        # planner asks for plain JSON without registering tool specs.

    def plan(self, user_request: str, context: PlannerContext) -> AnalysisPlan:
        from quantlab_agent.domain.models import DateRange

        dataset_summaries = [
            {
                "dataset_id": s["dataset_id"],
                "asset_id": s["asset_id"],
                "date_min": s["date_min"],
                "date_max": s["date_max"],
                "row_count": s["row_count"],
            }
            for s in context.dataset_summaries
        ]
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": PLANNER_USER_PROMPT_TEMPLATE.format(
                    dataset_summaries=json.dumps(dataset_summaries, ensure_ascii=False),
                    user_request=user_request,
                ),
            },
        ]
        turn = self._model.complete_with_tools(messages=messages, tools=[], timeout_seconds=30.0)
        if turn.error:
            raise PlannerError(f"planner model call failed: {turn.error}")
        if not turn.text:
            raise PlannerError("planner model returned no text")

        raw = turn.text.strip()
        # Some models wrap JSON in ```json ... ``` fences; strip them.
        if raw.startswith("```"):
            raw = raw.strip("`")
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PlannerError(f"planner returned invalid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise PlannerError("planner payload must be a JSON object")

        # Parse the date_range sub-object if present.
        date_range: DateRange | None = None
        raw_range = payload.get("date_range")
        if isinstance(raw_range, dict):
            try:
                date_range = DateRange(start=raw_range["start"], end=raw_range["end"])
            except (KeyError, ValueError) as exc:
                raise PlannerError(f"invalid date_range in planner output: {exc}") from exc

        return AnalysisPlan(
            intent=Intent(payload["intent"]),
            dataset_refs=tuple(payload.get("dataset_refs") or ()),
            date_range=date_range,
            metrics=tuple(MetricName(m) for m in payload.get("metrics") or ()),
            charts=tuple(ChartKind(c) for c in payload.get("charts") or ()),
            clarifying_question=payload.get("clarifying_question"),
            user_visible_summary=payload.get("user_visible_summary") or "",
        )


__all__ = [
    "Planner",
    "PlannerContext",
    "PlannerError",
    "RulePlanner",
    "LLMPlanner",
    "PLANNER_SYSTEM_PROMPT",
    "PLANNER_USER_PROMPT_TEMPLATE",
]
