"""Dataset profiling — column-by-column summary of a normalized dataset.

Produces a ``DatasetProfile`` (per-column statistics and an overall
quality summary) without depending on a date range or a prepared
analysis. Pure read of the existing ``ImportedDataset`` snapshot.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass

from quantlab_agent.application.datasets import ImportedDataset
from quantlab_agent.domain.models import (
    ColumnProfile,
    DatasetProfile,
    QualityReport,
)


@dataclass(frozen=True, slots=True)
class ProfilingService:
    """Compute a ``DatasetProfile`` for any ``ImportedDataset``."""

    def profile(self, dataset: ImportedDataset) -> DatasetProfile:
        manifest = dataset.manifest
        points = list(dataset.points)
        row_count = len(points)
        if row_count == 0:
            return DatasetProfile(
                dataset_id=manifest.dataset_id,
                asset_id=manifest.metadata.asset_id,
                row_count=0,
                columns=(
                    ColumnProfile(
                        name="date",
                        semantic_type="date",
                        missing_count=0,
                        unique_count=0,
                    ),
                    ColumnProfile(
                        name="close",
                        semantic_type="numeric_price",
                        missing_count=0,
                        unique_count=0,
                    ),
                ),
                quality_summary=_quality_summary(manifest.quality_report),
            )

        dates = [point.date for point in points]
        prices = [point.close for point in points]
        unique_dates = len(set(dates))
        unique_prices = len(set(prices))

        return DatasetProfile(
            dataset_id=manifest.dataset_id,
            asset_id=manifest.metadata.asset_id,
            row_count=row_count,
            columns=(
                ColumnProfile(
                    name="date",
                    semantic_type="date",
                    missing_count=0,
                    unique_count=unique_dates,
                    min=min(dates).isoformat(),
                    max=max(dates).isoformat(),
                ),
                ColumnProfile(
                    name="close",
                    semantic_type="numeric_price",
                    missing_count=0,
                    unique_count=unique_prices,
                    min=round(min(prices), 6),
                    max=round(max(prices), 6),
                    mean=round(statistics.fmean(prices), 6),
                    std=round(statistics.stdev(prices), 6) if row_count >= 2 else None,
                ),
            ),
            quality_summary=_quality_summary(manifest.quality_report),
        )


def _quality_summary(report: QualityReport) -> dict[str, object]:
    error_count = sum(1 for issue in report.issues if issue.severity.value == "error")
    warning_count = sum(1 for issue in report.issues if issue.severity.value == "warning")
    top = [
        {
            "code": issue.code,
            "severity": issue.severity.value,
            "message": issue.message,
        }
        for issue in report.issues[:3]
    ]
    return {
        "error_count": error_count,
        "warning_count": warning_count,
        "top_issues": top,
    }


__all__ = ["ProfilingService"]
