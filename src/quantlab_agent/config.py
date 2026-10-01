"""Environment-driven configuration.

For M2 we only need ``RUNS_DIR`` and the matplotlib backend hook. Real
model provider settings are deferred to M3.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class AppConfig:
    app_mode: str = "demo"
    runs_dir: Path = Path("runs")
    matplotlib_backend: str = "Agg"


def load_config() -> AppConfig:
    runs_dir = Path(os.environ.get("QUANTLAB_RUNS_DIR", "runs"))
    return AppConfig(
        app_mode=os.environ.get("QUANTLAB_APP_MODE", "demo"),
        runs_dir=runs_dir,
        matplotlib_backend=os.environ.get("QUANTLAB_MATPLOTLIB_BACKEND", "Agg"),
    )


__all__ = ["AppConfig", "load_config"]
