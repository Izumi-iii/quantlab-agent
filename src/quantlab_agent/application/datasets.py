"""CSV import and data-quality checks.

This is the boundary where untrusted file bytes become a validated dataset
snapshot. No model is involved in this process.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from io import StringIO
from uuid import uuid4

import numpy as np
import pandas as pd

from quantlab_agent.domain.errors import ErrorCode
from quantlab_agent.domain.models import (
    DatasetManifest,
    DatasetMetadata,
    IssueSeverity,
    PriceBasis,
    PricePoint,
    QualityIssue,
    QualityReport,
)
from quantlab_agent.domain.policies import SUPPORTED_FREQUENCY, DatasetImportPolicy


@dataclass(frozen=True, slots=True)
class ImportedDataset:
    manifest: DatasetManifest
    points: tuple[PricePoint, ...]


@dataclass(frozen=True, slots=True)
class DatasetImportResult:
    dataset: ImportedDataset | None
    quality_report: QualityReport

    @property
    def ok(self) -> bool:
        return self.dataset is not None and not self.quality_report.has_errors


class DatasetService:
    REQUIRED_COLUMNS = ("date", "close")

    def __init__(self, policy: DatasetImportPolicy | None = None) -> None:
        self._policy = policy or DatasetImportPolicy()

    def import_csv(
        self,
        content: bytes,
        *,
        metadata: DatasetMetadata,
        session_id: str,
    ) -> DatasetImportResult:
        issues: list[QualityIssue] = []
        transformations: list[str] = []

        if not content:
            return self._failed(ErrorCode.INVALID_FILE, "CSV file is empty.")
        if len(content) > self._policy.max_file_bytes:
            return self._failed(
                ErrorCode.FILE_TOO_LARGE,
                "CSV file exceeds the configured size limit.",
                details={
                    "bytes": len(content),
                    "max_bytes": self._policy.max_file_bytes,
                },
            )

        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            return self._failed(
                ErrorCode.INVALID_ENCODING,
                "CSV must use UTF-8 or UTF-8 with BOM encoding.",
                details={"byte_offset": exc.start},
            )

        try:
            frame = pd.read_csv(StringIO(text), dtype=str, keep_default_na=False)
        except Exception as exc:
            return self._failed(
                ErrorCode.INVALID_FILE,
                "CSV could not be parsed.",
                details={"parser_error": type(exc).__name__},
            )

        if len(frame) > self._policy.max_rows:
            return self._failed(
                ErrorCode.FILE_TOO_LARGE,
                "CSV exceeds the configured row limit.",
                details={"rows": len(frame), "max_rows": self._policy.max_rows},
            )

        missing = [column for column in self.REQUIRED_COLUMNS if column not in frame.columns]
        if missing:
            return self._failed(
                ErrorCode.MISSING_COLUMN,
                "CSV is missing required columns.",
                details={
                    "missing_columns": missing,
                    "required_columns": list(self.REQUIRED_COLUMNS),
                },
            )
        if frame.empty:
            return self._failed(ErrorCode.INVALID_FILE, "CSV contains a header but no data rows.")

        normalized = frame.loc[:, self.REQUIRED_COLUMNS].copy()
        csv_rows = pd.Series(np.arange(2, len(normalized) + 2), index=normalized.index)

        date_text = normalized["date"].str.strip()
        date_shape_valid = date_text.str.fullmatch(r"\d{4}-\d{2}-\d{2}")
        parsed_dates = pd.to_datetime(date_text, format="%Y-%m-%d", errors="coerce")
        invalid_date_mask = ~date_shape_valid | parsed_dates.isna()
        if invalid_date_mask.any():
            issues.append(
                QualityIssue(
                    severity=IssueSeverity.ERROR,
                    code=ErrorCode.INVALID_DATE.value,
                    message="Dates must be valid values in YYYY-MM-DD format.",
                    row_numbers=tuple(int(row) for row in csv_rows[invalid_date_mask]),
                )
            )

        close_text = normalized["close"].str.strip()
        parsed_close = pd.to_numeric(close_text, errors="coerce")
        close_array = parsed_close.to_numpy(dtype=float, na_value=np.nan)
        invalid_price_mask = parsed_close.isna() | ~np.isfinite(close_array) | (parsed_close <= 0)
        if invalid_price_mask.any():
            issues.append(
                QualityIssue(
                    severity=IssueSeverity.ERROR,
                    code=ErrorCode.INVALID_PRICE.value,
                    message="Close prices must be finite numbers greater than zero.",
                    row_numbers=tuple(int(row) for row in csv_rows[invalid_price_mask]),
                )
            )

        if not invalid_date_mask.any():
            duplicate_mask = parsed_dates.duplicated(keep=False)
            if duplicate_mask.any():
                duplicate_rows = tuple(int(row) for row in csv_rows[duplicate_mask])
                duplicate_view = pd.DataFrame(
                    {"date": parsed_dates[duplicate_mask], "close": close_text[duplicate_mask]}
                )
                conflicting_dates = [
                    timestamp.date().isoformat()
                    for timestamp, group in duplicate_view.groupby("date", sort=True)
                    if group["close"].nunique(dropna=False) > 1
                ]
                issues.append(
                    QualityIssue(
                        severity=IssueSeverity.ERROR,
                        code=ErrorCode.DUPLICATE_DATE.value,
                        message="CSV contains duplicate dates and must be corrected before analysis.",
                        row_numbers=duplicate_rows,
                        details={"conflicting_dates": conflicting_dates},
                    )
                )

        if metadata.frequency != SUPPORTED_FREQUENCY:
            issues.append(
                QualityIssue(
                    severity=IssueSeverity.ERROR,
                    code=ErrorCode.UNSUPPORTED_FREQUENCY.value,
                    message="The first version supports daily data only.",
                    details={"received": metadata.frequency, "supported": SUPPORTED_FREQUENCY},
                )
            )

        if metadata.price_basis is PriceBasis.UNKNOWN:
            issues.append(
                QualityIssue(
                    severity=IssueSeverity.WARNING,
                    code="UNKNOWN_PRICE_BASIS",
                    message="Price basis is unknown; comparisons may require clarification.",
                )
            )

        if any(issue.severity is IssueSeverity.ERROR for issue in issues):
            return DatasetImportResult(
                dataset=None,
                quality_report=QualityReport(issues=tuple(issues)),
            )

        normalized["date"] = parsed_dates
        normalized["close"] = parsed_close.astype(float)
        if not normalized["date"].is_monotonic_increasing:
            normalized = normalized.sort_values("date", kind="stable").reset_index(drop=True)
            transformations.append("Rows were stably sorted by date in ascending order.")
            issues.append(
                QualityIssue(
                    severity=IssueSeverity.WARNING,
                    code="UNSORTED_DATES",
                    message="Dates were not ascending; the normalized snapshot was sorted.",
                )
            )
        else:
            normalized = normalized.reset_index(drop=True)

        returns = (
            normalized["close"].iloc[1:].to_numpy() / normalized["close"].iloc[:-1].to_numpy() - 1.0
        )
        abnormal_positions = np.flatnonzero(
            np.abs(returns) > self._policy.abnormal_simple_return_threshold
        )
        if abnormal_positions.size:
            abnormal_dates = tuple(
                normalized.iloc[int(position) + 1]["date"].date().isoformat()
                for position in abnormal_positions
            )
            issues.append(
                QualityIssue(
                    severity=IssueSeverity.WARNING,
                    code="ABNORMAL_PRICE_MOVE",
                    message="Large price changes were found; verify adjustment and source data.",
                    details={
                        "threshold": self._policy.abnormal_simple_return_threshold,
                        "dates": abnormal_dates,
                    },
                )
            )

        if not metadata.daily_series_complete:
            issues.append(
                QualityIssue(
                    severity=IssueSeverity.WARNING,
                    code="DAILY_COMPLETENESS_UNCONFIRMED",
                    message="Daily-series completeness was not declared; daily annualization will be disabled.",
                )
            )

        normalized_csv = normalized.to_csv(
            index=False,
            date_format="%Y-%m-%d",
            lineterminator="\n",
            float_format="%.12g",
        ).encode("utf-8")
        report = QualityReport(
            issues=tuple(issues),
            transformations=tuple(transformations),
        )
        manifest = DatasetManifest(
            dataset_id=str(uuid4()),
            session_id=session_id,
            metadata=metadata,
            raw_sha256=sha256(content).hexdigest(),
            normalized_sha256=sha256(normalized_csv).hexdigest(),
            date_min=normalized["date"].iloc[0].date(),
            date_max=normalized["date"].iloc[-1].date(),
            row_count=len(normalized),
            imported_at=datetime.now(UTC),
            quality_report=report,
        )
        return DatasetImportResult(
            dataset=ImportedDataset(
                manifest=manifest,
                points=tuple(
                    PricePoint(date=row.date.date(), close=float(row.close))
                    for row in normalized.itertuples(index=False)
                ),
            ),
            quality_report=report,
        )

    @staticmethod
    def _failed(
        code: ErrorCode,
        message: str,
        *,
        details: dict[str, object] | None = None,
    ) -> DatasetImportResult:
        issue = QualityIssue(
            severity=IssueSeverity.ERROR,
            code=code.value,
            message=message,
            details=details or {},
        )
        return DatasetImportResult(dataset=None, quality_report=QualityReport(issues=(issue,)))
