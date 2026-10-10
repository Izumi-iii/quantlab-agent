"""ReportService — produce Markdown reports bound to a verified analysis.

The Evidence Validator runs first; if any reference (analysis, metrics,
chart) does not line up with the run, ``UNKNOWN_REFERENCE`` is raised
and no markdown is written.

The markdown template uses ``{{ key }}`` placeholders. A small
``render`` helper substitutes placeholders without pulling in Jinja2.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from quantlab_agent.adapters.local_stores import utcnow
from quantlab_agent.application.runs import RunService
from quantlab_agent.domain.errors import ErrorCode, QuantLabError
from quantlab_agent.domain.models import (
    AssetMetricResult,
    ChartArtifact,
    EvidenceRef,
    MetricName,
    MetricResult,
    ReportArtifact,
    ReportSection,
    Run,
)
from quantlab_agent.ports.stores import ReportStore

_PLACEHOLDER_RE = __import__("re").compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


def _render(template: str, mapping: dict[str, Any]) -> str:
    def replace(match: __import__("re").Match[str]) -> str:
        key = match.group(1)
        if key not in mapping:
            raise QuantLabError(
                ErrorCode.INVALID_ARGUMENT,
                f"Report template references unknown key: {key}",
            )
        return str(mapping[key])

    return _PLACEHOLDER_RE.sub(replace, template)


class ReportService:
    """Build, validate, and persist the Markdown report for a run."""

    TEMPLATE: str = (
        "# QuantLab 数据分析报告\n\n"
        "## 1. 分析结论\n\n"
        "{{ analysis_summary }}\n\n"
        "## 2. 分析范围\n\n"
        "- 运行模式：{{ mode_label }}\n"
        "- 用户问题：{{ user_request }}\n"
        "- 分析编号：{{ run_id }}\n\n"
        "{{ data_sources }}\n\n"
        "## 3. 数据与质量说明\n\n"
        "{{ data_quality }}\n\n"
        "## 4. 计算口径\n\n"
        "{{ methodology }}\n\n"
        "## 5. 指标明细\n\n"
        "{{ metrics_table }}\n\n"
        "## 6. 结论边界\n\n"
        "{{ limitations }}\n\n"
        "## 7. 追溯信息\n\n"
        "{{ run_info }}\n"
    )

    def __init__(
        self,
        *,
        report_store: ReportStore,
        run_service: RunService,
    ) -> None:
        self._reports = report_store
        self._runs = run_service

    def build_report(
        self,
        *,
        run_id: str,
        session_id: str,
        analysis_id: str,
        metrics_id: str,
        metrics: MetricResult,
        charts: tuple[ChartArtifact, ...],
    ) -> ReportArtifact:
        # Reference ownership — every ID must belong to this run/session.
        run = self._runs.assert_analysis_owned(run_id, session_id, analysis_id)
        self._runs.assert_metrics_owned(run_id, session_id, metrics_id)
        for chart in charts:
            self._runs.assert_chart_owned(run_id, session_id, chart.chart_id)

        # Cross-consistency: every metric and every chart must point at the
        # same analysis_id. A mismatch means the caller is mixing references.
        if metrics.analysis_id != analysis_id:
            raise QuantLabError(
                ErrorCode.UNKNOWN_REFERENCE,
                "Metrics do not reference the run's analysis.",
                details={
                    "metrics_analysis_id": metrics.analysis_id,
                    "expected_analysis_id": analysis_id,
                },
            )
        for chart in charts:
            if chart.analysis_id != analysis_id:
                raise QuantLabError(
                    ErrorCode.UNKNOWN_REFERENCE,
                    "Chart does not reference the run's analysis.",
                    details={
                        "chart_id": chart.chart_id,
                        "chart_analysis_id": chart.analysis_id,
                        "expected_analysis_id": analysis_id,
                    },
                )

        completed_at = utcnow()
        artifact = ReportArtifact(
            report_id=str(uuid4()),
            run_id=run_id,
            analysis_id=analysis_id,
            metrics_id=metrics_id,
            chart_ids=tuple(c.chart_id for c in charts),
            section_ids=tuple(ReportSection),
            evidence_refs=self._build_evidence_refs(run, metrics, charts),
            markdown_path="",
            created_at=completed_at,
        )

        report_run = run.model_copy(update={"completed_at": completed_at})
        context = self._build_context(run=report_run, metrics=metrics, charts=charts)
        markdown = _render(ReportService.TEMPLATE, context)

        self._reports.save(artifact, session_id=session_id, markdown=markdown)
        self._runs.bind_report(run_id, session_id, artifact.report_id)
        self._runs.mark_succeeded(run_id, session_id, completed_at=completed_at)
        return artifact

    # -- context construction ---------------------------------------------

    def _build_context(
        self,
        *,
        run: Run,
        metrics: MetricResult,
        charts: tuple[ChartArtifact, ...],
    ) -> dict[str, Any]:
        mode_label = "确定性演示模式" if run.mode.value == "demo" else "模型规划模式"
        assets_summary = ", ".join(asset.asset_id for asset in metrics.assets)
        data_sources = (
            f"- 分析资产：{assets_summary}\n"
            f"- 数据集数量：{len(run.dataset_ids)}\n"
            f"- 请求区间：{run.context_snapshot.get('requested_start')} 至 "
            f"{run.context_snapshot.get('requested_end')}\n"
            f"- 实际分析区间：{run.context_snapshot.get('effective_start')} 至 "
            f"{run.context_snapshot.get('effective_end')}\n"
            f"- 日期对齐方式：{self._alignment_label(run.context_snapshot.get('alignment_policy'))}\n"
        )
        data_quality = (
            "- 日频数据是否完整由用户声明，系统未独立验证交易日历。\n"
            "- 导入时会执行数据校验；具体缺失、排序或异常问题请以数据质量检查结果为准。\n"
            "- 指标成功计算不等于数据已被证明完整、准确或不存在异常。\n"
        )
        methodology = (
            "- 区间收益：分析区间内末次价格 / 首次价格 - 1，不是年化收益。\n"
            "- 年化波动率：简单日收益的样本标准差乘以 252 的平方根；"
            "需满足日频完整性声明及日期对齐条件。\n"
            "- 最大回撤：区间内价格相对截至当时历史最高价的跌幅最小值；"
            "历史最高价从分析区间起点开始累计。\n"
            "- 以下文字总结根据已计算指标按确定规则生成，不是预测或投资建议。\n"
        )
        metrics_table = self._format_metrics_table(metrics.assets)
        limitations = self._format_limitations(run, metrics)
        run_info = (
            f"- 创建时间：{run.created_at.isoformat()}\n"
            f"- 完成时间：{run.completed_at.isoformat() if run.completed_at else '未记录'}\n"
            f"- 指标结果编号：{metrics.metrics_id}\n"
            f"- 数据集编号：{', '.join(run.dataset_ids)}\n"
            f"- 图表编号：{', '.join(c.chart_id for c in charts) or '无'}\n"
        )
        return {
            "mode_label": mode_label,
            "user_request": run.user_request,
            "run_id": run.run_id,
            "data_sources": data_sources,
            "data_quality": data_quality,
            "methodology": methodology,
            "metrics_table": metrics_table,
            "limitations": limitations,
            "run_info": run_info,
            "analysis_summary": self._format_analysis_summary(run, metrics),
        }

    @staticmethod
    def _alignment_label(policy: str | None) -> str:
        return {
            "common_observation_dates": "共同观测日期",
            "single_asset_dates": "单资产观测日期",
        }.get(policy, policy or "未记录")

    @staticmethod
    def _format_analysis_summary(run: Run, metrics: MetricResult) -> str:
        start = run.context_snapshot.get("effective_start", "未记录")
        end = run.context_snapshot.get("effective_end", "未记录")
        paragraphs = [f"本次结论仅覆盖 {start} 至 {end} 的历史价格数据。"]
        for asset in metrics.assets:
            values = asset.metrics
            period = values.get(MetricName.PERIOD_RETURN)
            drawdown = values.get(MetricName.MAX_DRAWDOWN)
            volatility = values.get(MetricName.ANNUALIZED_VOLATILITY)
            notes = []
            if period is not None and period.value is not None:
                direction = "高于" if period.value > 0 else "低于" if period.value < 0 else "等于"
                notes.append(
                    f"区间收益为 {period.value * 100:+.2f}%，期末价格{direction}期初。"
                    "这描述的是区间起止表现，不代表期间持续上涨或下跌。"
                )
            else:
                notes.append("区间收益未提供或不可用，无法判断区间起止涨跌。")
            if drawdown is not None and drawdown.value is not None:
                loss = abs(drawdown.value)
                if loss == 0:
                    notes.append(
                        "观测价格中未出现相对区间内历史高点的回撤；这不意味着未来没有风险。"
                    )
                else:
                    notes.append(
                        f"最大回撤为 {drawdown.value * 100:.2f}%，"
                        f"即价格曾从此前的区间内高点下跌 {loss * 100:.2f}%。"
                    )
                    if period is not None and period.value is not None and period.value > 0:
                        notes.append(
                            "虽然期末取得正收益，持有期间仍经历过回撤，不能只凭最终收益判断过程平稳。"
                        )
                    if loss < 1:
                        rebound = loss / (1 - loss)
                        notes.append(
                            f"按该跌幅换算，从对应低点回到此前高点需上涨约 {rebound * 100:.2f}%"
                            "（跌幅 / (1 - 跌幅)）。这是幅度换算，不表示已恢复或将恢复。"
                        )
            else:
                notes.append("最大回撤未提供或不可用，不能据此判断历史高点至低点的损失幅度。")
            if volatility is not None:
                if volatility.value is None:
                    notes.append("年化波动率不可用，不据此给出波动高低或资产稳定性的结论。")
                else:
                    notes.append(
                        f"年化波动率为 {volatility.value * 100:.2f}%，反映日收益的离散程度，"
                        "不是预期收益，也不是最大可能亏损；未设定比较基准，不将其简单标为高风险或低风险。"
                    )
                    if volatility.observations < 20:
                        notes.append("日收益观测少于 20 条，波动率估计对少量价格变化较敏感。")
            if not any(metric.value is not None for metric in values.values()):
                notes.append("当前没有可用指标，不能形成实质性的收益或风险结论。")
            paragraphs.append(f"### {asset.asset_id}\n\n" + "\n\n".join(notes))
        if len(metrics.assets) > 1:
            comparisons = []
            aligned = run.context_snapshot.get("alignment_policy") == "common_observation_dates"
            for name, label in (
                (MetricName.PERIOD_RETURN, "区间收益"),
                (MetricName.MAX_DRAWDOWN, "最大回撤"),
                (MetricName.ANNUALIZED_VOLATILITY, "年化波动率"),
            ):
                available = [
                    (a.asset_id, a.metrics[name])
                    for a in metrics.assets
                    if name in a.metrics and a.metrics[name].value is not None
                ]
                if not aligned or len(available) != len(metrics.assets):
                    continue
                if len({metric.observations for _, metric in available}) != 1:
                    continue
                low = min(available, key=lambda item: item[1].value)
                high = max(available, key=lambda item: item[1].value)
                gap = (high[1].value - low[1].value) * 100
                if gap == 0:
                    comparisons.append(f"各资产的{label}相同。")
                elif name is MetricName.MAX_DRAWDOWN:
                    comparisons.append(
                        f"{high[0]} 的最大回撤较浅，{low[0]} 较深，跌幅相差 {gap:.2f} 个百分点。"
                    )
                else:
                    comparisons.append(
                        f"{high[0]} 的{label}最高，{low[0]} 最低，相差 {gap:.2f} 个百分点。"
                    )
            paragraphs.append(
                "### 资产间比较\n\n"
                + (
                    "\n\n".join(comparisons)
                    if comparisons
                    else "缺少共同日期、同口径的完整指标，不做直接排名。"
                )
                + "\n\n收益、回撤和波动各描述不同侧面；不能把收益排名直接当作综合优劣或买卖依据。"
            )
        return "\n\n".join(paragraphs)

    @staticmethod
    def _format_metrics_table(assets: tuple[AssetMetricResult, ...]) -> str:
        lines = [
            "| 资产 | 指标 | 数值 | 观测数 | 计算备注 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for asset in assets:
            for metric_name, metric in asset.metrics.items():
                value = "不可用" if metric.value is None else f"{metric.value * 100:.2f}%"
                assumptions = (
                    "；".join(ReportService._note_label(note) for note in metric.assumptions) or "—"
                )
                unavailable = (
                    ReportService._note_label(metric.unavailable_reason)
                    if metric.unavailable_reason
                    else "—"
                )
                note = unavailable if metric.value is None else assumptions
                lines.append(
                    f"| {asset.asset_id} | {ReportService._metric_label(metric_name)} | {value} | "
                    f"{metric.observations} | {note} |"
                )
        return "\n".join(lines)

    @staticmethod
    def _format_limitations(run: Run, metrics: MetricResult) -> str:
        unavailable: list[str] = []
        for asset in metrics.assets:
            for metric_name, metric in asset.metrics.items():
                if metric.value is None:
                    unavailable.append(
                        f"- {asset.asset_id} 的{ReportService._metric_label(metric_name)}不可用：{ReportService._note_label(metric.unavailable_reason)}"
                    )
        notes = [
            "- 本报告描述已上传的历史价格，不预测未来表现，不提供买卖建议。",
            "- 收益采用所选价格口径，未额外计入手续费、滑点、税费或未体现在价格中的现金分红。",
            "- 最大回撤只覆盖选定区间，不能说明区间外的历史风险；波动率不等于损失上限。",
            "- 未计算或不可用的指标不会被补写成确定结论；本报告不推断涨跌的外部原因。",
        ]
        return "\n".join(notes + unavailable)

    @staticmethod
    def _metric_label(name: MetricName) -> str:
        return {
            MetricName.PERIOD_RETURN: "区间收益",
            MetricName.MAX_DRAWDOWN: "最大回撤",
            MetricName.ANNUALIZED_VOLATILITY: "年化波动率",
        }[name]

    @staticmethod
    def _note_label(note: str) -> str:
        labels = {
            "Uses the selected price basis and first/last observations.": "使用所选价格口径及区间首末观测值",
            "Running peak begins at the first observation in the analysis window.": "历史高点从分析区间的首次观测开始累计",
            "Daily-series completeness is user-declared and not independently verified.": "日频完整性由用户声明，未独立核验",
            "The sample contains fewer than 20 return observations.": "日收益观测少于 20 条，样本较短",
            "At least two return observations are required.": "至少需要两条收益观测",
            "At least two price observations are required.": "至少需要两条价格观测",
            "Daily-series completeness was not confirmed.": "尚未确认日频数据完整性",
            "The original date sequences differ; interval returns cannot be treated as daily returns.": "原始日期序列不一致，区间收益不能当作日收益",
            "date sequences differ": "日期序列不一致",
        }
        if note.startswith("Simple daily returns annualized with sqrt(") and note.endswith(")."):
            factor = note.removeprefix("Simple daily returns annualized with sqrt(").removesuffix(
                ")."
            )
            return f"简单日收益按 {factor} 个交易日年化"
        return labels.get(note, note)

    @staticmethod
    def _build_evidence_refs(
        run: Run, metrics: MetricResult, charts: tuple[ChartArtifact, ...]
    ) -> tuple[EvidenceRef, ...]:
        refs: list[EvidenceRef] = []
        for dataset_id in run.dataset_ids:
            refs.append(EvidenceRef(kind="dataset", ref_id=dataset_id))
        if run.analysis_id:
            refs.append(EvidenceRef(kind="analysis", ref_id=run.analysis_id))
        refs.append(EvidenceRef(kind="metrics", ref_id=metrics.metrics_id))
        for chart in charts:
            refs.append(EvidenceRef(kind="chart", ref_id=chart.chart_id))
        return tuple(refs)


__all__ = ["ReportService"]
