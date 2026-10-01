"""Centralized limits and thresholds for the first project version."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class DatasetImportPolicy:
    max_file_bytes: int = 5 * 1024 * 1024
    max_rows: int = 50_000
    abnormal_simple_return_threshold: float = 0.50


SUPPORTED_FREQUENCY = "daily"
DEFAULT_ANNUALIZATION_FACTOR = 252
MIN_PRICE_POINTS = 2
MIN_RETURN_OBSERVATIONS_FOR_VOLATILITY = 2
SHORT_SAMPLE_RETURN_OBSERVATIONS = 20
