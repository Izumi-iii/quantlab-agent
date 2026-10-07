"""Errors shared by the deterministic core.

Domain errors carry a stable machine-readable code and a separate user-facing
message. Application code should branch on ``code`` instead of matching text.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    INVALID_FILE = "INVALID_FILE"
    FILE_TOO_LARGE = "FILE_TOO_LARGE"
    INVALID_ENCODING = "INVALID_ENCODING"
    MISSING_COLUMN = "MISSING_COLUMN"
    INVALID_DATE = "INVALID_DATE"
    INVALID_PRICE = "INVALID_PRICE"
    DUPLICATE_DATE = "DUPLICATE_DATE"
    UNSUPPORTED_FREQUENCY = "UNSUPPORTED_FREQUENCY"
    INCOMPATIBLE_PRICE_BASIS = "INCOMPATIBLE_PRICE_BASIS"
    INCOMPATIBLE_CURRENCY = "INCOMPATIBLE_CURRENCY"
    INVALID_DATE_RANGE = "INVALID_DATE_RANGE"
    NO_DATA_IN_RANGE = "NO_DATA_IN_RANGE"
    NO_OVERLAP = "NO_OVERLAP"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    STALE_RUN = "STALE_RUN"
    UNKNOWN_REFERENCE = "UNKNOWN_REFERENCE"
    BUDGET_EXCEEDED = "BUDGET_EXCEEDED"
    TOOL_FAILURE = "TOOL_FAILURE"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"
    UNKNOWN_TOOL = "UNKNOWN_TOOL"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    NEEDS_CLARIFICATION = "NEEDS_CLARIFICATION"


class QuantLabError(Exception):
    """Expected application error that can be shown safely to a user."""

    def __init__(
        self,
        code: ErrorCode,
        user_message: str,
        *,
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message
        self.retryable = retryable
        self.details = details or {}

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.user_message,
            "retryable": self.retryable,
            "details": self.details,
        }
