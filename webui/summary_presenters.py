"""Deterministic summary text for the WebUI agent bubble.

Each presenter is a pure function that takes a ``Run`` and the
``tool_calls.jsonl`` records persisted by ``ToolRegistry``, and returns
a short, deterministic, user-facing string suitable for the left rail
bubble. No model calls; no free-form text; structure is enforced.

The presenters read tool call envelopes from ``ToolCallRecord`` and the
plan summary from ``Run.context_snapshot``. They never compute new
metrics — if a metric is not in the tool results, it is reported as
"not computed".

Allowed dependencies:
- ``quantlab_agent.domain.*``
- ``quantlab_agent.application.*`` (read-only services)
- standard library

The module MUST NOT import ``quantlab_agent.agent.planner`` to avoid
circular dependency with the planner layer.
"""

from __future__ import annotations

import statistics
from typing import Any, Iterable

from quantlab_agent.domain.models import (
    AnalysisExtra,
    AnomalyReport,
    AssetSeriesSummary,
    DatasetProfile,
    Intent,
    PriceSeriesSummary,
    RiskAnalysisResult,
    RollingReport,
    Run,
)


def _format_pct(value: float | None) -> str:
    if value is None:
        return "不可用"
    return f"{value * 100:+.2f}%"


def _format_price(value: float | None) -> str:
    if value is None:
        return "不可用"
    return f"{value:.2f}"


def _metric_label(name: str) -> str:
    labels = {
        "period_return": "区间收益",
        "max_drawdown": "最大回撤",
        "annualized_volatility": "年化波动率",
        "sharpe_ratio": "夏普",
        "sortino_ratio": "Sortino",
        "calmar_ratio": "Calmar",
        "var_95": "VaR95",
        "cvar_95": "CVaR95",
        "mean_daily_return": "日均收益",
        "std_daily_return": "日收益标准差",
        "annualized_return": "年化收益",
    }
    return labels.get(name, name)


def _tool_payload(record: Any) -> dict[str, Any] | None:
    env = getattr(record, "result_envelope", None)
    if env is None:
        return None
    return env.data if env.ok else None


def _first_payload(records: Iterable[Any], tool_name: str) -> dict[str, Any] | None:
    for r in records:
        if r.tool_name == tool_name:
            payload = _tool_payload(r)
            if payload is not None:
                return payload
    return None


def summarize_profile(run: Run, tool_calls: tuple[Any, ...]) -> str:
    payload = _first_payload(tool_calls, "profile_dataset")
    if payload is None:
        return "尚未生成数据概况。"
    try:
        profile = DatasetProfile.model_validate(payload)
    except Exception:  # noqa: BLE001 - shape mismatch → fallback text
        return "数据概况已生成，但当前结果格式无法展示。"

    cols = profile.columns
    date_col = next((c for c in cols if c.semantic_type == "date"), None)
    price_col = next((c for c in cols if c.semantic_type == "numeric_price"), None)

    lines: list[str] = []
    lines.append(f"数据概况：{profile.asset_id}")
    lines.append(f"- 行数：{profile.row_count}")
    if date_col is not None and date_col.min and date_col.max:
        lines.append(
            f"- 日期范围：{date_col.min} 至 {date_col.max}，{date_col.unique_count} 个观测点"
        )
    if price_col is not None:
        price_line = f"- 收盘价：{_format_price(price_col.min)} 至 {_format_price(price_col.max)}"
        if price_col.mean is not None:
            price_line += (
                f"，均值 {_format_price(price_col.mean)}，标准差 {_format_price(price_col.std)}"
            )
        lines.append(price_line)
    qs = profile.quality_summary
    if qs.get("error_count") or qs.get("warning_count"):
        lines.append(
            f"- 数据质量：{qs.get('error_count', 0)} 个错误，{qs.get('warning_count', 0)} 个警告"
        )
    else:
        lines.append("- 数据质量：未发现错误或警告")
    return "\n".join(lines)


def summarize_describe(run: Run, tool_calls: tuple[Any, ...]) -> str:
    payload = _first_payload(tool_calls, "describe_price_series")
    if payload is None:
        return "尚未生成走势摘要。"
    try:
        summary = PriceSeriesSummary.model_validate(payload)
    except Exception:  # noqa: BLE001
        return "走势摘要已生成，但当前结果格式无法展示。"

    head = f"走势摘要：{summary.effective_start} 至 {summary.effective_end}"
    asset_lines = [_render_asset_describe(asset) for asset in summary.assets]
    body = "\n".join(line for line in asset_lines if line)
    return f"{head}\n{body}".strip()


def _render_asset_describe(asset: AssetSeriesSummary) -> str:
    if asset.total_return is None:
        return f"- {asset.asset_id}: 数据不足，无法生成摘要。"
    parts: list[str] = []
    parts.append(
        f"- {asset.asset_id}: 累计收益 {_format_pct(asset.total_return)}；"
        f"价格区间 {_format_price(asset.min_price)}（{asset.min_price_date}）"
        f"至 {_format_price(asset.max_price)}（{asset.max_price_date}）"
    )
    if asset.up_days is not None and asset.down_days is not None:
        parts.append(
            f"  上涨/下跌/持平：{asset.up_days}/{asset.down_days}/{asset.flat_days or 0} 天"
        )
    if asset.max_daily_gain is not None and asset.max_daily_loss is not None:
        parts.append(
            f"  最大单日涨幅 {asset.max_daily_gain * 100:+.2f}%（{asset.max_daily_gain_date}），"
            f"最大单日跌幅 {asset.max_daily_loss * 100:.2f}%（{asset.max_daily_loss_date}）"
        )
    if asset.longest_up_streak is not None:
        parts.append(
            f"  最长连续上涨 {asset.longest_up_streak} 天，最长连续下跌 {asset.longest_down_streak or 0} 天"
        )
    return "\n".join(parts)


def summarize_metrics(run: Run, tool_calls: tuple[Any, ...]) -> str:
    payload = _first_payload(tool_calls, "compute_metrics")
    if payload is None:
        return "Metrics were not computed."
    assets = payload.get("assets") or []
    if not assets:
        return "Metrics were computed but produced no assets."

    lines: list[str] = ["指标计算完成。"]
    for entry in assets:
        asset_id = entry.get("asset_id", "?")
        metrics = entry.get("metrics") or {}
        parts: list[str] = []
        for name, value in metrics.items():
            v = value.get("value")
            if v is None:
                reason = value.get("unavailable_reason") or "not computed"
                parts.append(f"{_metric_label(name)}=不可用（{reason}）")
            else:
                parts.append(f"{_metric_label(name)}={v:.4f}")
        if parts:
            lines.append(f"{asset_id}: " + ", ".join(parts) + ".")
    return "\n".join(lines)


def summarize_chart(run: Run, tool_calls: tuple[Any, ...]) -> str:
    payload = _first_payload(tool_calls, "create_charts")
    if payload is None:
        return "未生成图表。"
    chart_ids = payload.get("chart_ids") or []
    kinds = payload.get("kinds") or []
    windows = payload.get("windows") or []
    if not chart_ids:
        return "未生成图表。"
    labels = {
        "normalized_prices": "归一化价格走势",
        "drawdown": "历史回撤",
        "rolling_return": "滚动收益",
        "rolling_volatility": "滚动年化波动率",
        "rolling_drawdown": "窗口最大回撤",
    }
    names = [
        f"{windows[index]} 日" + labels.get(kind, kind)
        if index < len(windows) and windows[index]
        else labels.get(kind, kind)
        for index, kind in enumerate(kinds)
    ]
    return f"图表已生成：{len(chart_ids)} 张（{'、'.join(names) if names else '默认图表'}）。"


def summarize_anomalies(run: Run, tool_calls: tuple[Any, ...]) -> str | None:
    payload = _first_payload(tool_calls, "detect_anomalies")
    if payload is None:
        return None
    try:
        report = AnomalyReport.model_validate(payload)
    except Exception:  # noqa: BLE001
        return None
    total_items = sum(len(items) for _, items in report.asset_anomalies)
    if total_items == 0:
        return "异常检查完成：在当前阈值下未发现明显异常。"
    parts: list[str] = []
    for asset_id, items in report.asset_anomalies:
        if not items:
            continue
        first_three = items[:3]
        joined = "；".join(f"{it.date} {it.kind.value}" for it in first_three)
        suffix = f"；另有 {len(items) - 3} 个" if len(items) > 3 else ""
        parts.append(f"{asset_id}: {joined}{suffix}")
    if not parts:
        return "异常检查完成：在当前阈值下未发现明显异常。"
    return f"异常检查完成：发现 {total_items} 个疑似异常。\n" + "\n".join(
        f"- {part}" for part in parts
    )


def summarize_risk(run: Run, tool_calls: tuple[Any, ...]) -> str | None:
    payload = _first_payload(tool_calls, "compute_risk_metrics")
    if payload is None:
        return None
    try:
        result = RiskAnalysisResult.model_validate(payload)
    except Exception:  # noqa: BLE001
        return None
    if not result.assets:
        return "风险指标不可用。"
    parts: list[str] = []
    for asset in result.assets:
        values = asset.values
        if not values:
            continue
        sharpe = values.get("sharpe_ratio")
        var = values.get("var_95")
        cvar = values.get("cvar_95")
        calmar = values.get("calmar_ratio")
        snippet = []
        if sharpe is not None:
            snippet.append(f"Sharpe {sharpe:.2f}")
        if var is not None:
            snippet.append(f"VaR95 {var * 100:.2f}%")
        if cvar is not None:
            snippet.append(f"CVaR95 {cvar * 100:.2f}%")
        if calmar is not None:
            snippet.append(f"Calmar {calmar:.2f}")
        if snippet:
            parts.append(f"{asset.asset_id}: " + ", ".join(snippet))
    if not parts:
        return "风险指标不可用。"
    return f"风险指标（按 {result.annualization_factor} 个交易日年化）：\n" + "\n".join(
        f"- {part}" for part in parts
    )


def summarize_rolling(run: Run, tool_calls: tuple[Any, ...]) -> str | None:
    payload = _first_payload(tool_calls, "compute_rolling_metrics")
    if payload is None:
        return None
    try:
        report = RollingReport.model_validate(payload)
    except Exception:  # noqa: BLE001
        return None
    if not report.series:
        return "滚动指标不可用。"
    kinds = set(run.context_snapshot.get("requested_charts") or [])
    labels = {
        "rolling_volatility": "滚动年化波动率",
        "rolling_return": "滚动收益",
        "rolling_drawdown": "窗口最大回撤",
        "rolling_sharpe": "滚动夏普比率",
    }
    notes = []
    for sample in report.series:
        if kinds and sample.metric not in kinds:
            continue
        valid = [point for point in sample.points if point.value is not None]
        label = f"{sample.asset_id} · {sample.window} 日{labels[sample.metric]}"
        if valid:
            point = valid[-1]
            value = (
                f"{point.value:.2f}"
                if sample.metric == "rolling_sharpe"
                else f"{point.value * 100:.2f}%"
            )
            notes.append(f"- {label}：{value}（{point.date}）")
            if (
                run.context_snapshot.get("reference_run_id")
                and sample.metric == "rolling_volatility"
            ):
                typical = statistics.median(p.value for p in valid)
                peak = max(valid, key=lambda p: p.value)
                relative = (
                    "高于" if point.value > typical else "低于" if point.value < typical else "等于"
                )
                notes.append(
                    f"  最新值{relative}历史滚动中位数 {typical * 100:.2f}%；最高值 {peak.value * 100:.2f}%（{peak.date}）。"
                )
        else:
            notes.append(f"- {label}：数据不足，尚无完整窗口。")
    # Regime change hint: compare last 60d vol vs median vol on the same series.
    regime = ""
    vol_series = next(
        (s for s in report.series if s.metric == "rolling_volatility" and s.window == 60),
        None,
    )
    if vol_series is not None:
        values = [p.value for p in vol_series.points if p.value is not None]
        if len(values) >= 5:
            median = statistics.median(values)
            last_v = values[-1]
            if median > 0 and last_v > 1.5 * median:
                regime = "\n- 最近 60 日波动率明显高于历史滚动中位数。"
    return (
        f"滚动指标已计算：窗口 {list(report.windows)}（按观测条数，非自然日）。\n"
        + "\n".join(notes)
        + regime
    )


def summarize_run(run: Run, tool_calls: tuple[Any, ...]) -> str | None:
    """Pick the right presenter for the NEW intents / extras introduced
    in M7 / M8 / M9. Returns ``None`` for legacy intents so the caller
    falls back to its existing legacy summarizers
    (``_summarize_data_quality``, ``_summarize_metrics``,
    ``_summarize_chart``).
    """
    snapshot = dict(run.context_snapshot or {})
    intent_raw = snapshot.get("intent")
    if not intent_raw and run.failure:
        intent_raw = run.failure.get("details", {}).get("intent")
    extras_raw = snapshot.get("extras") or []
    extras = {AnalysisExtra(e) for e in extras_raw if e in AnalysisExtra._value2member_map_}

    try:
        intent = Intent(intent_raw) if intent_raw else None
    except ValueError:
        intent = None

    if intent is Intent.PROFILE:
        return summarize_profile(run, tool_calls)
    parts = []
    for extra, presenter in (
        (AnalysisExtra.DESCRIBE_PRICE_SERIES, summarize_describe),
        (AnalysisExtra.RISK, summarize_risk),
        (AnalysisExtra.ANOMALIES, summarize_anomalies),
        (AnalysisExtra.ROLLING, summarize_rolling),
    ):
        if extra in extras:
            parts.append(presenter(run, tool_calls))
    if intent is Intent.CHART and parts:
        parts.append(summarize_chart(run, tool_calls))
    return "\n".join(part for part in parts if part) or None


__all__ = [
    "summarize_profile",
    "summarize_describe",
    "summarize_metrics",
    "summarize_chart",
    "summarize_anomalies",
    "summarize_risk",
    "summarize_rolling",
    "summarize_run",
]
