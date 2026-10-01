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
        "# QuantLab analysis report\n\n"
        "## 1. Overview\n\n"
        "- Mode: {{ mode_label }}\n"
        "- User request: {{ user_request }}\n"
        "- Run ID: {{ run_id }}\n\n"
        "## 2. Data sources\n\n"
        "{{ data_sources }}\n\n"
        "## 3. Data quality\n\n"
        "{{ data_quality }}\n\n"
        "## 4. Methodology\n\n"
        "{{ methodology }}\n\n"
        "## 5. Metrics table\n\n"
        "{{ metrics_table }}\n\n"
        "## 6. Limitations\n\n"
        "{{ limitations }}\n\n"
        "## 7. Run info\n\n"
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
        mode_label = "Deterministic demo mode" if run.mode.value == "demo" else "Real agent mode"
        assets_summary = ", ".join(asset.asset_id for asset in metrics.assets)
        data_sources = (
            f"- Assets: {assets_summary}\n"
            f"- Datasets bound: {len(run.dataset_ids)}\n"
            f"- Analysis window: {run.context_snapshot.get('requested_start')} → "
            f"{run.context_snapshot.get('requested_end')}\n"
            f"- Effective window: {run.context_snapshot.get('effective_start')} → "
            f"{run.context_snapshot.get('effective_end')}\n"
            f"- Alignment: {run.context_snapshot.get('alignment_policy')}\n"
        )
        data_quality = (
            "- Daily-series completeness is user-declared.\n"
            "- Abnormal price moves and unsorted inputs are reported "
            "during dataset import.\n"
        )
        methodology = (
            "- Period return: last/first - 1 over the selected window.\n"
            "- Annualized volatility: sample std of simple returns × √252 "
            "(only when daily completeness is declared and date sequences align).\n"
            "- Max drawdown: minimum of price/running_peak - 1 within the "
            "analysis window.\n"
        )
        metrics_table = self._format_metrics_table(metrics.assets)
        limitations = self._format_limitations(run, metrics)
        run_info = (
            f"- Run created at: {run.created_at.isoformat()}\n"
            f"- Run completed at: {run.completed_at.isoformat() if run.completed_at else 'n/a'}\n"
            f"- Mode: {run.mode.value}\n"
            f"- Datasets: {', '.join(run.dataset_ids)}\n"
            f"- Charts: {', '.join(c.chart_id for c in charts)}\n"
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
        }

    @staticmethod
    def _format_metrics_table(assets: tuple[AssetMetricResult, ...]) -> str:
        lines = [
            "| Asset | Metric | Value | Observations | Notes |",
            "| --- | --- | --- | --- | --- |",
        ]
        for asset in assets:
            for metric_name, metric in asset.metrics.items():
                value = "n/a" if metric.value is None else f"{metric.value * 100:.2f}%"
                assumptions = "; ".join(metric.assumptions) or "—"
                unavailable = metric.unavailable_reason or "—"
                note = unavailable if metric.value is None else assumptions
                lines.append(
                    f"| {asset.asset_id} | {metric_name.value} | {value} | "
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
                        f"- {asset.asset_id}.{metric_name.value}: {metric.unavailable_reason}"
                    )
        if not unavailable:
            return "- No metric was forced into the unavailable state.\n"
        return "\n".join(["The following metrics could not be computed:"] + unavailable)

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
