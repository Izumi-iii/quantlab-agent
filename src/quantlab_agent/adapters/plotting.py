"""matplotlib-based plot service for chart artifacts.

Uses the object-oriented API (``Figure`` / ``Axes``), not ``pyplot``, so
lifecycle is explicit. The Agg backend is forced at import time so the
service works on headless systems (Windows, CI containers, etc.).
"""

from __future__ import annotations

import matplotlib

matplotlib.use("Agg")  # noqa: E402  (must precede pyplot import)

from io import BytesIO  # noqa: E402
from typing import Any  # noqa: E402

import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from quantlab_agent.domain.metrics import drawdown_series  # noqa: E402

_PNG_MAGIC = b"\x89PNG"


class PlotService:
    """Render chart PNGs and emit a JSON-friendly data payload."""

    def render_series(
        self, *, series_by_asset: dict[str, pd.Series], title: str, value_label: str
    ) -> tuple[bytes, dict[str, Any]]:
        fig, ax = plt.subplots(figsize=(8.0, 4.5), dpi=120)
        for asset_id, series in series_by_asset.items():
            ax.plot(series.index, series.to_numpy(), label=asset_id, linewidth=1.5)
        ax.set_title(title)
        ax.set_xlabel("date")
        ax.set_ylabel(value_label)
        ax.legend(loc="best", fontsize=9)
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        fig.autofmt_xdate()
        result = self._finalize(fig, series_by_asset, value_label=value_label)
        plt.close(fig)
        return result

    def render_normalized_prices(
        self,
        *,
        series_by_asset: dict[str, pd.Series],
        title: str,
    ) -> tuple[bytes, dict[str, Any]]:
        fig, ax = plt.subplots(figsize=(8.0, 4.5), dpi=120)
        for asset_id, series in series_by_asset.items():
            ax.plot(series.index, series.to_numpy(), label=asset_id, linewidth=1.5)
        ax.set_title(title)
        ax.set_xlabel("date")
        ax.set_ylabel("price (base = 100)")
        ax.legend(loc="best", fontsize=9)
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        fig.autofmt_xdate()
        png_bytes, data_payload = self._finalize(fig, series_by_asset, value_label="price")

        ax.clear()
        plt.close(fig)
        return png_bytes, data_payload

    def render_drawdown(
        self,
        *,
        series_by_asset: dict[str, pd.Series],
        title: str,
    ) -> tuple[bytes, dict[str, Any]]:
        fig, ax = plt.subplots(figsize=(8.0, 4.5), dpi=120)
        drawdowns: dict[str, pd.Series] = {}
        for asset_id, series in series_by_asset.items():
            drawdown = (
                drawdown_series(series)
                if len(series) >= 2
                else pd.Series(float("nan"), index=series.index)
            )
            drawdowns[asset_id] = drawdown
            ax.fill_between(
                series.index,
                drawdown.to_numpy(),
                0.0,
                alpha=0.35,
                label=asset_id,
            )
            ax.plot(series.index, drawdown.to_numpy(), linewidth=1.0)
        ax.set_title(title)
        ax.set_xlabel("date")
        ax.set_ylabel("drawdown")
        ax.legend(loc="best", fontsize=9)
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        fig.autofmt_xdate()
        png_bytes, data_payload = self._finalize(fig, drawdowns, value_label="drawdown")

        ax.clear()
        plt.close(fig)
        return png_bytes, data_payload

    # -- internals ---------------------------------------------------------

    def _finalize(
        self,
        fig: Any,
        series_by_asset: dict[str, pd.Series],
        *,
        value_label: str,
    ) -> tuple[bytes, dict[str, Any]]:
        buf = BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        png_bytes = buf.getvalue()
        if not png_bytes.startswith(_PNG_MAGIC):
            raise RuntimeError("Generated image is not a valid PNG.")
        buf.close()
        # Note: matplotlib on Windows writes correct PNG bytes; the
        # ``_atomic_write_bytes`` helper in ``adapters.local_stores`` is
        # responsible for opening the file in O_BINARY mode so those bytes
        # reach disk intact.

        data_payload: dict[str, Any] = {
            "schema_version": 2,
            "axes": {"x": "date", "y": value_label},
            "series": [
                {
                    "asset_id": asset_id,
                    "x": [ts.date().isoformat() for ts in series.index],
                    "y": [float(v) if pd.notna(v) else None for v in series.to_numpy()],
                }
                for asset_id, series in series_by_asset.items()
            ],
        }
        return png_bytes, data_payload


__all__ = ["PlotService"]
