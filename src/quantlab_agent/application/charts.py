"""ChartService — render prepared analyses into chart artifacts and persist them.

ChartService is intentionally narrow: it takes an already-prepared
analysis, renders PNGs via PlotService, and persists the artifacts
through ChartStore. Re-preparing the analysis (re-loading datasets +
re-slicing) is the caller's responsibility — typically the
``create_charts`` tool handler — so ChartService does not depend on
DatasetStore or AnalysisService.
"""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any
from uuid import uuid4

import pandas as pd

from quantlab_agent.adapters.local_stores import utcnow
from quantlab_agent.adapters.plotting import PlotService
from quantlab_agent.application.analyses import PreparedAnalysis
from quantlab_agent.application.rolling import RollingMetricsService
from quantlab_agent.application.runs import RunService
from quantlab_agent.domain.errors import ErrorCode, QuantLabError
from quantlab_agent.domain.models import (
    ChartArtifact,
    ChartKind,
    RollingReport,
)
from quantlab_agent.ports.stores import ChartStore


class ChartService:
    def __init__(
        self,
        *,
        chart_store: ChartStore,
        plot_service: PlotService,
        run_service: RunService,
    ) -> None:
        self._charts = chart_store
        self._plot = plot_service
        self._runs = run_service

    def create_charts(
        self,
        *,
        run_id: str,
        session_id: str,
        analysis: PreparedAnalysis,
        kinds: tuple[ChartKind, ...],
        rolling_windows: tuple[int, ...] = (60,),
        rolling_report: RollingReport | None = None,
    ) -> tuple[ChartArtifact, ...]:
        # Reference ownership is enforced by the ToolRegistry before this
        # method runs; we trust the caller here.
        series_by_asset: dict[str, pd.Series] = {}
        for asset in analysis.assets:
            base = float(asset.prices[0])
            series_by_asset[asset.asset_id] = pd.Series(
                [p / base * 100.0 for p in asset.prices],
                index=asset.to_series().index,
                name=asset.asset_id,
                dtype=float,
            )

        artifacts: list[ChartArtifact] = []
        rolling_kinds = {
            ChartKind.ROLLING_RETURN,
            ChartKind.ROLLING_VOLATILITY,
            ChartKind.ROLLING_DRAWDOWN,
        }
        if any(kind in rolling_kinds for kind in kinds) and rolling_report is None:
            rolling_report = RollingMetricsService(
                annualization_factor=analysis.spec.annualization_factor
            ).compute(analysis, windows=rolling_windows)
        jobs = [
            (kind, window)
            for kind in dict.fromkeys(kinds)
            for window in (
                tuple(dict.fromkeys(rolling_windows)) if kind in rolling_kinds else (None,)
            )
        ]
        for kind, window in jobs:
            if window is not None:
                assert rolling_report is not None
                rolling_series = {
                    item.asset_id: pd.Series(
                        [point.value for point in item.points],
                        index=pd.to_datetime([point.date for point in item.points]),
                        dtype=float,
                    )
                    for item in rolling_report.series
                    if item.metric == kind.value and item.window == window
                }
                title = f"{window}-observation {kind.value}: {', '.join(rolling_series)}"
                png_bytes, data_payload = self._plot.render_series(
                    series_by_asset=rolling_series, title=title, value_label=kind.value
                )
                data_payload["window"] = window
                data_payload["annualization_factor"] = analysis.spec.annualization_factor
            else:
                title = self._title_for(kind, analysis)
                png_bytes, data_payload = self._render(kind, series_by_asset)
            artifact = ChartArtifact(
                chart_id=str(uuid4()),
                run_id=run_id,
                analysis_id=analysis.spec.analysis_id,
                kind=kind,
                window=window,
                png_path="",
                data_path="",
                data_sha256=sha256(
                    json.dumps(data_payload, sort_keys=True).encode("utf-8")
                ).hexdigest(),
                title=title,
                x_label="date",
                y_label=self._y_label_for(kind),
                series_labels=tuple(series_by_asset.keys()),
                created_at=utcnow(),
            )
            self._charts.save(
                artifact,
                session_id=session_id,
                png_bytes=png_bytes,
                data_payload=data_payload,
            )
            self._runs.bind_chart(run_id, session_id, artifact.chart_id)
            artifacts.append(artifact)
        return tuple(artifacts)

    # -- helpers -----------------------------------------------------------

    def _render(
        self, kind: ChartKind, series_by_asset: dict[str, pd.Series]
    ) -> tuple[bytes, dict[str, Any]]:
        title = self._title_template(kind).format(assets=", ".join(series_by_asset.keys()))
        if kind is ChartKind.NORMALIZED_PRICES:
            return self._plot.render_normalized_prices(series_by_asset=series_by_asset, title=title)
        if kind is ChartKind.DRAWDOWN:
            return self._plot.render_drawdown(series_by_asset=series_by_asset, title=title)
        raise QuantLabError(
            ErrorCode.INVALID_ARGUMENT,
            f"Unsupported chart kind: {kind}",
        )

    @staticmethod
    def _title_template(kind: ChartKind) -> str:
        if kind is ChartKind.NORMALIZED_PRICES:
            return "Normalized prices (base = 100): {assets}"
        return "Drawdown from running peak: {assets}"

    @staticmethod
    def _title_for(kind: ChartKind, analysis: PreparedAnalysis) -> str:
        assets = ", ".join(asset.asset_id for asset in analysis.assets)
        return ChartService._title_template(kind).format(assets=assets)

    @staticmethod
    def _y_label_for(kind: ChartKind) -> str:
        if kind is ChartKind.NORMALIZED_PRICES:
            return "price (base = 100)"
        if kind.value.startswith("rolling_"):
            return kind.value
        return "drawdown"


__all__ = ["ChartService"]
