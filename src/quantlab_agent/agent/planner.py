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
    AnalysisExtra,
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
    '  "intent": "data_quality" | "profile" | "metrics" | "chart" | "report" | "clarify" | "out_of_scope",\n'
    '  "dataset_refs": ["DEMO_A", "DEMO_B", ...],   // empty means "all in session"\n'
    '  "date_range": {"start": "YYYY-MM-DD", "end": "YYYY-MM-DD"} | null,\n'
    '  "metrics": ["period_return", "annualized_volatility", "max_drawdown"],\n'
    '  "charts": ["normalized_prices", "drawdown"],\n'
    '  "extras": ["describe_price_series", "risk", "anomalies", "rolling"],\n'
    '  "clarifying_question": string | null,   // only when intent=clarify\n'
    '  "user_visible_summary": string          // 1-2 sentence agent message\n'
    "}\n\n"
    "Intent rules:\n"
    "- data_quality: user only asks about quality / inspection / sanity\n"
    "- profile: user asks for dataset/table/CSV overview, columns, shape, or profile\n"
    "- metrics: user wants computed numbers; omit charts unless asked\n"
    "- chart: user asks to draw/plot/show a trend chart without needing metric numbers\n"
    "- report: user explicitly asks for a full report\n"
    "- clarify: request is missing essential info; ask ONE short question in clarifying_question\n"
    "- out_of_scope: request is unrelated to CSV price analysis\n"
    "Extras rules:\n"
    "- describe_price_series: attach to metrics when user asks what the trend/performance looks like\n"
    "- risk: attach to metrics when user asks about risk, Sharpe, Sortino, Calmar, VaR, or CVaR\n"
    "- anomalies: attach to data_quality when user asks about anomalies, outliers, jumps, or gaps\n"
    "- rolling: attach to chart when user asks for rolling/window/moving metrics\n"
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


_ANOMALY_PATTERNS = (
    r"异常",
    r"跳变",
    r"缺口",
    r"疑似.{0,4}错",
    r"anomal",
    r"outlier",
    r"gap",
)

_RISK_PATTERNS = (
    r"风险",
    r"稳不稳",
    r"夏普",
    r"VaR",
    r"CVaR",
    r"回撤风险",
    r"risk",
    r"sharpe",
    r"sortino",
    r"calmar",
)

_ROLLING_PATTERNS = (
    r"滚动",
    r"窗口",
    r"60.{0,4}日",
    r"20.{0,4}日",
    r"252.{0,4}日",
    r"rolling",
    r"window",
    r"moving",
)


_PROFILE_PATTERNS = (
    r"概况",
    r"画像",
    r"这张表",
    r"看一下.{0,8}表",
    r"字段",
    r"列名",
    r"profile",
    r"describe dataset",
    r"what.{0,8}csv.{0,8}look",
)

_DESCRIBE_PATTERNS = (
    r"走势特点",
    r"表现",
    r"走势",
    r"发生了什么",
    r"describe",
    r"summarize trend",
    r"what.{0,8}trend",
    r"how.{0,8}did.{0,8}perform",
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
    r"对比一下",
    r"画一下.{0,8}图",
    r"compare.{0,8}trend",
    r"compare.{0,8}chart",
    r"compare.{0,8}graph",
)

_CHART_PATTERNS = (
    r"图表",
    r"图形",
    r"趋势图",
    r"走势图",
    r"画图",
    r"画一下",
    r"画.{0,4}走势",
    r"作图",
    r"生成.{0,8}图",
    r"plot",
    r"chart",
    r"graph",
    r"trend chart",
    r"make.{0,4}chart",
    r"draw.{0,4}chart",
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
    """Return chart kinds requested by the user.

    Conservative: only emit ``DRAWDOWN`` / ``NORMALIZED_PRICES`` when
    an explicit chart keyword is also present, otherwise a metric
    phrase like "最大回撤" would steal chart kinds from a metrics
    request. ``rolling.*`` kinds are added later by the chart branch.
    """
    found: list[ChartKind] = []
    seen: set[ChartKind] = set()
    lowered = text.lower()
    has_chart_keyword = _match_any(
        lowered,
        (
            r"图",
            r"chart",
            r"plot",
            r"graph",
            r"走势",
            r"趋势",
        ),
    )
    if has_chart_keyword:
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
                user_visible_summary=("超出范围：我目前只处理已上传 CSV 的历史价格数据分析。"),
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

        # Decide intent by precedence. profile/data_quality win over
        # the "which dataset?" clarification when the user has signalled
        # it explicitly — the request is unambiguous about *what* to do.

        if _match_any(text, _PROFILE_PATTERNS):
            return AnalysisPlan(
                intent=Intent.PROFILE,
                dataset_refs=dataset_refs,
                user_visible_summary=("我会生成数据表概况和质量摘要。"),
            )

        if _match_any(text, _DATA_QUALITY_PATTERNS) or _match_any(text, _ANOMALY_PATTERNS):
            if metrics or chart_kinds:
                # User wants metrics/charts AND quality — fall through.
                pass
            else:
                extras: tuple[AnalysisExtra, ...] = ()
                if _match_any(text, _ANOMALY_PATTERNS):
                    extras = (AnalysisExtra.ANOMALIES,)
                return AnalysisPlan(
                    intent=Intent.DATA_QUALITY,
                    dataset_refs=dataset_refs,
                    extras=extras,
                    user_visible_summary=("我会检查已导入数据的质量，并提示疑似异常。"),
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
                    f"你想分析哪些数据集？当前可选：{', '.join(s['asset_id'] for s in available)}。"
                ),
                user_visible_summary=("我可以分析当前已导入的任意数据集组合。"),
            )

        # Bare "分析一下" / "看一下" with no target → ask for clarification.
        if not metrics and not chart_kinds and _match_any(text, _CLARIFY_TRIGGERS):
            return AnalysisPlan(
                intent=Intent.CLARIFY,
                clarifying_question=(
                    "你想分析什么内容？请说明指标（区间收益、最大回撤、年化波动率等）和日期范围。"
                ),
                user_visible_summary="我需要更多信息才能继续分析。",
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
                user_visible_summary=("我会生成包含指标和图表的完整报告。"),
            )

        # "走势怎么样" / "what's the trend" → describe (metrics + extra).
        # Fires only when no explicit chart keyword (走势图 / 画图 / plot /
        # chart) is present, otherwise the chart branch below wins.
        if (
            _match_any(text, _DESCRIBE_PATTERNS)
            and not _match_any(text, _CHART_PATTERNS)
            and not metrics
        ):
            date_range = self._maybe_date_payload(text)
            return AnalysisPlan(
                intent=Intent.METRICS,
                dataset_refs=dataset_refs,
                date_range=date_range,
                metrics=(MetricName.PERIOD_RETURN, MetricName.MAX_DRAWDOWN),
                extras=(AnalysisExtra.DESCRIBE_PRICE_SERIES,),
                user_visible_summary=("我会概括这个区间内的价格走势。"),
            )

        if has_chart_signal or _match_any(text, _ROLLING_PATTERNS):
            date_range = self._maybe_date_payload(text)
            extras = ()
            if _match_any(text, _ROLLING_PATTERNS):
                extras = (AnalysisExtra.ROLLING,)
            charts = chart_kinds or (ChartKind.NORMALIZED_PRICES,)
            return AnalysisPlan(
                intent=Intent.CHART,
                dataset_refs=dataset_refs,
                date_range=date_range,
                charts=charts,
                extras=extras,
                user_visible_summary=("我会生成你需要的趋势图表。"),
            )

        if has_metric_signal or has_chart_signal or _match_any(text, _RISK_PATTERNS):
            date_range = self._maybe_date_payload(text)
            extras_list: list[AnalysisExtra] = []
            if _match_any(text, _DESCRIBE_PATTERNS):
                extras_list.append(AnalysisExtra.DESCRIBE_PRICE_SERIES)
            if _match_any(text, _RISK_PATTERNS):
                extras_list.append(AnalysisExtra.RISK)
            extras = tuple(extras_list)
            return AnalysisPlan(
                intent=Intent.METRICS,
                dataset_refs=dataset_refs,
                date_range=date_range,
                metrics=metrics
                or (
                    MetricName.PERIOD_RETURN,
                    MetricName.MAX_DRAWDOWN,
                ),
                extras=extras,
                user_visible_summary=("我会计算这个区间内的相关指标。"),
            )

        # Fallback: ask for clarification.
        return AnalysisPlan(
            intent=Intent.CLARIFY,
            clarifying_question=("我还不能确定分析意图。请说明要分析的数据集、日期范围和指标。"),
            user_visible_summary="我需要更多信息来选择合适的分析路径。",
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
            extras=tuple(AnalysisExtra(e) for e in payload.get("extras") or ()),
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
