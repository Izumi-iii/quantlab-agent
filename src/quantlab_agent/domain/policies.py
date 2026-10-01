"""Centralized limits and thresholds for the first project version."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DatasetImportPolicy:
    max_file_bytes: int = 5 * 1024 * 1024
    max_rows: int = 50_000
    abnormal_simple_return_threshold: float = 0.50


@dataclass(frozen=True, slots=True)
class RunBudgetPolicy:
    """Per-run budgets enforced by RunService (per PROJECT_PLAN §12.1)."""

    max_model_interactions: int = 8
    max_tool_executions: int = 12
    max_same_validation_retry: int = 1
    max_retryable_network_errors: int = 1
    per_request_timeout_seconds: int = 30
    total_deadline_seconds: int = 120


SUPPORTED_FREQUENCY = "daily"
DEFAULT_ANNUALIZATION_FACTOR = 252
MIN_PRICE_POINTS = 2
MIN_RETURN_OBSERVATIONS_FOR_VOLATILITY = 2
SHORT_SAMPLE_RETURN_OBSERVATIONS = 20

DEFAULT_RUN_BUDGET = RunBudgetPolicy()
