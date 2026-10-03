"""Small CSV fixtures for evaluation cases.

Cases that need bad or unusual CSVs construct them here so the
runner file stays focused on orchestration. All fixtures write into
the per-case tmp_path and return the file content as bytes.
"""

from __future__ import annotations

from pathlib import Path


def missing_close() -> bytes:
    return (
        b"date,open,high,low\n2024-01-02,100,101,99\n2024-01-03,101,102,100\n2024-01-04,99,101,98\n"
    )


def bad_date_format() -> bytes:
    return (
        b"date,close\n"
        b"2024-1-2,100\n"  # month and day not zero-padded
        b"not-a-date,101\n"
        b"2024-01-04,99\n"
    )


def zero_or_negative_price() -> bytes:
    return (
        b"date,close\n"
        b"2024-01-02,100\n"
        b"2024-01-03,0\n"  # zero price
        b"2024-01-04,-5\n"  # negative price
    )


def disjoint_dates() -> bytes:
    """Asset A in early January; asset B in late January. No overlap."""
    return b"date,close\n2024-01-02,100\n2024-01-03,101\n2024-01-04,99\n"


def single_point() -> bytes:
    """One-row CSV so any window contains at most one observation."""
    return b"date,close\n2024-01-02,100\n"


def partial_overlap() -> bytes:
    """Asset with full coverage + asset missing some mid-window dates.

    After alignment the annualized volatility must be marked
    unavailable because the common dates are not contiguous.
    """
    return (
        b"date,close\n"
        b"2024-01-02,100\n"
        b"2024-01-04,101\n"  # gap on 2024-01-03
        b"2024-01-05,99\n"
        b"2024-01-08,103\n"
        b"2024-01-09,104\n"
        b"2024-01-10,102\n"
        b"2024-01-12,105\n"
        b"2024-01-15,106\n"
    )


def write_fixture(tmp_path: Path, name: str, content: bytes) -> Path:
    """Write a fixture CSV and return the path."""
    path = tmp_path / name
    path.write_bytes(content)
    return path


__all__ = [
    "missing_close",
    "bad_date_format",
    "zero_or_negative_price",
    "disjoint_dates",
    "single_point",
    "partial_overlap",
    "write_fixture",
]
