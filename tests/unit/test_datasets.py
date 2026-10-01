from hashlib import sha256

from quantlab_agent.application.datasets import DatasetImportResult, DatasetService
from quantlab_agent.domain.errors import ErrorCode
from quantlab_agent.domain.models import DatasetMetadata, PriceBasis
from quantlab_agent.domain.policies import DatasetImportPolicy


def metadata(**overrides: object) -> DatasetMetadata:
    values: dict[str, object] = {
        "asset_id": "DEMO_A",
        "source_name": "synthetic test fixture",
        "price_basis": PriceBasis.FORWARD_ADJUSTED,
        "currency": "cny",
        "frequency": "daily",
        "calendar_label": "synthetic weekdays",
        "daily_series_complete": True,
        "is_synthetic": True,
    }
    values.update(overrides)
    return DatasetMetadata(**values)


def issue_codes(result: DatasetImportResult) -> set[str]:
    return {issue.code for issue in result.quality_report.issues}


def test_valid_csv_creates_normalized_snapshot() -> None:
    content = b"date,close\n2024-01-02,100\n2024-01-03,101.5\n"

    result = DatasetService().import_csv(content, metadata=metadata(), session_id="session-1")

    assert result.ok
    assert result.dataset is not None
    assert result.dataset.manifest.row_count == 2
    assert result.dataset.manifest.metadata.currency == "CNY"
    assert [point.close for point in result.dataset.points] == [100.0, 101.5]
    assert result.dataset.manifest.raw_sha256 == sha256(content).hexdigest()
    assert len(result.dataset.manifest.normalized_sha256) == 64


def test_unsorted_dates_are_stably_sorted_and_reported() -> None:
    content = b"date,close\n2024-01-03,101\n2024-01-02,100\n"

    result = DatasetService().import_csv(content, metadata=metadata(), session_id="session-1")

    assert result.ok
    assert result.dataset is not None
    assert [point.close for point in result.dataset.points] == [100.0, 101.0]
    assert "UNSORTED_DATES" in issue_codes(result)
    assert result.quality_report.transformations
    assert result.dataset.manifest.raw_sha256 != result.dataset.manifest.normalized_sha256


def test_unknown_price_basis_is_warning_not_silent_assumption() -> None:
    content = b"date,close\n2024-01-02,100\n2024-01-03,101\n"

    result = DatasetService().import_csv(
        content,
        metadata=metadata(price_basis=PriceBasis.UNKNOWN),
        session_id="session-1",
    )

    assert result.ok
    assert "UNKNOWN_PRICE_BASIS" in issue_codes(result)


def test_unconfirmed_daily_completeness_disables_silent_annualization() -> None:
    content = b"date,close\n2024-01-02,100\n2024-01-03,101\n"

    result = DatasetService().import_csv(
        content,
        metadata=metadata(daily_series_complete=False),
        session_id="session-1",
    )

    assert result.ok
    assert "DAILY_COMPLETENESS_UNCONFIRMED" in issue_codes(result)


def test_conflicting_duplicate_dates_are_rejected_with_csv_rows() -> None:
    content = b"date,close\n2024-01-02,100\n2024-01-02,101\n"

    result = DatasetService().import_csv(content, metadata=metadata(), session_id="session-1")

    assert not result.ok
    assert result.dataset is None
    issue = next(issue for issue in result.quality_report.issues if issue.code == "DUPLICATE_DATE")
    assert issue.row_numbers == (2, 3)
    assert issue.details["conflicting_dates"] == ["2024-01-02"]


def test_invalid_dates_and_prices_report_all_affected_rows() -> None:
    content = b"date,close\n2024-1-02,100\nnot-a-date,0\n2024-01-04,not-a-number\n"

    result = DatasetService().import_csv(content, metadata=metadata(), session_id="session-1")

    assert not result.ok
    date_issue = next(
        issue for issue in result.quality_report.issues if issue.code == "INVALID_DATE"
    )
    price_issue = next(
        issue for issue in result.quality_report.issues if issue.code == "INVALID_PRICE"
    )
    assert date_issue.row_numbers == (2, 3)
    assert price_issue.row_numbers == (3, 4)


def test_missing_column_is_rejected() -> None:
    result = DatasetService().import_csv(
        b"date,open\n2024-01-02,100\n",
        metadata=metadata(),
        session_id="session-1",
    )

    assert not result.ok
    assert issue_codes(result) == {ErrorCode.MISSING_COLUMN.value}


def test_non_daily_frequency_is_rejected() -> None:
    result = DatasetService().import_csv(
        b"date,close\n2024-01-02,100\n2024-01-09,101\n",
        metadata=metadata(frequency="weekly"),
        session_id="session-1",
    )

    assert not result.ok
    assert ErrorCode.UNSUPPORTED_FREQUENCY.value in issue_codes(result)


def test_file_size_limit_is_enforced_before_parsing() -> None:
    service = DatasetService(DatasetImportPolicy(max_file_bytes=10))

    result = service.import_csv(
        b"date,close\n2024-01-02,100\n",
        metadata=metadata(),
        session_id="session-1",
    )

    assert not result.ok
    assert issue_codes(result) == {ErrorCode.FILE_TOO_LARGE.value}
