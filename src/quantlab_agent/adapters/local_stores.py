"""Local file-backed implementations of the storage Protocols.

Layout (per architecture §12.1):

    <runs_root>/<session_id>/datasets/<dataset_id>/manifest.json
                                              normalized.csv
    <runs_root>/<session_id>/runs/<run_id>/manifest.json
                                       tool_calls.jsonl
                                       charts/<chart_id>.png
                                       charts/<chart_id>.json
                                       report.md

All IDs are validated against the UUID regex before they touch the
filesystem. Every JSON write is atomic: write to a ``.tmp`` sibling,
fsync, then ``os.replace``. Path resolution is verified to stay inside
the runs directory; anything outside is rejected as
``UNKNOWN_REFERENCE``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from quantlab_agent.application.datasets import ImportedDataset
from quantlab_agent.domain.errors import ErrorCode, QuantLabError
from quantlab_agent.domain.models import (
    ChartArtifact,
    ReportArtifact,
    Run,
    RunStatus,
    ToolCallRecord,
)

_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def _validate_uuid(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not _UUID_RE.match(value):
        raise QuantLabError(
            ErrorCode.UNKNOWN_REFERENCE,
            f"{label} must be a UUID-shaped identifier.",
            details={"received": value[:64]},
        )
    return value


def _normalize_csv(imported: ImportedDataset) -> bytes:
    lines = ["date,close"]
    for point in imported.points:
        lines.append(f"{point.date.isoformat()},{point.close:.12g}")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _atomic_write_bytes(target: Path, payload: bytes) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".tmp")
    # ``os.O_BINARY`` is a no-op on POSIX but required on Windows under
    # Python 3.14+, where ``os.open`` defaults to text mode and silently
    # rewrites every LF to CRLF — which corrupts binary formats like PNG.
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_BINARY
    fd = os.open(tmp, flags)
    try:
        os.write(fd, payload)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, target)


def _atomic_write_json(target: Path, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=False)
    _atomic_write_bytes(target, body.encode("utf-8"))


def _read_json(target: Path) -> dict[str, Any]:
    with target.open("rb") as fh:
        return json.loads(fh.read().decode("utf-8"))


def _safe_join(root: Path, *parts: str) -> Path:
    """Resolve ``parts`` and ensure the result stays under ``root``."""
    candidate = root.joinpath(*parts).resolve(strict=False)
    root_resolved = root.resolve(strict=False)
    try:
        candidate.relative_to(root_resolved)
    except ValueError as exc:
        raise QuantLabError(
            ErrorCode.UNKNOWN_REFERENCE,
            "Resolved path escapes the runs directory.",
            details={"path": str(candidate)},
        ) from exc
    return candidate


def utcnow() -> datetime:
    return datetime.now(UTC)


class LocalDatasetStore:
    def __init__(self, runs_root: Path) -> None:
        self._root = Path(runs_root).resolve()

    @property
    def runs_root(self) -> Path:
        return self._root

    def _dataset_dir(self, session_id: str, dataset_id: str) -> Path:
        _validate_uuid(session_id, label="session_id")
        _validate_uuid(dataset_id, label="dataset_id")
        return _safe_join(self._root, session_id, "datasets", dataset_id)

    def save(self, dataset: ImportedDataset, session_id: str) -> str:
        dataset_id = dataset.manifest.dataset_id
        d = self._dataset_dir(session_id, dataset_id)
        d.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(d / "manifest.json", dataset.manifest.model_dump(mode="json"))
        _atomic_write_bytes(d / "normalized.csv", _normalize_csv(dataset))
        return dataset_id

    def get(self, dataset_id: str, session_id: str) -> ImportedDataset:
        from datetime import date as _date

        from quantlab_agent.domain.models import DatasetManifest, PricePoint

        d = self._dataset_dir(session_id, dataset_id)
        manifest_path = d / "manifest.json"
        if not manifest_path.exists():
            raise QuantLabError(
                ErrorCode.UNKNOWN_REFERENCE,
                "Dataset is not registered in the current session.",
                details={"dataset_id": dataset_id},
            )
        manifest = DatasetManifest.model_validate(_read_json(manifest_path))
        csv_path = d / "normalized.csv"
        points: list[PricePoint] = []
        for line in csv_path.read_text(encoding="utf-8").splitlines()[1:]:
            if not line:
                continue
            date_str, close_str = line.split(",", 1)
            points.append(PricePoint(date=_date.fromisoformat(date_str), close=float(close_str)))
        return ImportedDataset(manifest=manifest, points=tuple(points))

    def get_normalized_csv_path(self, dataset_id: str, session_id: str) -> str:
        d = self._dataset_dir(session_id, dataset_id)
        return str((d / "normalized.csv").resolve(strict=False))

    def delete(self, dataset_id: str, session_id: str) -> None:
        d = self._dataset_dir(session_id, dataset_id)
        if not d.exists():
            raise QuantLabError(
                ErrorCode.UNKNOWN_REFERENCE,
                "Dataset is not registered in the current session.",
                details={"dataset_id": dataset_id},
            )
        shutil.rmtree(d)

    def list_in_session(self, session_id: str) -> list[dict[str, object]]:
        """Return a summary of every dataset stored in the session."""
        _validate_uuid(session_id, label="session_id")
        sessions_root = _safe_join(self._root, session_id, "datasets")
        if not sessions_root.exists():
            return []
        items: list[dict[str, object]] = []
        for ds_dir in sorted(sessions_root.iterdir()):
            if not ds_dir.is_dir():
                continue
            manifest_path = ds_dir / "manifest.json"
            if not manifest_path.exists():
                continue
            manifest = _read_json(manifest_path)
            items.append(
                {
                    "dataset_id": manifest["dataset_id"],
                    "asset_id": manifest["metadata"]["asset_id"],
                    "date_min": manifest["date_min"],
                    "date_max": manifest["date_max"],
                    "row_count": manifest["row_count"],
                }
            )
        return sorted(items, key=lambda item: (str(item["asset_id"]), str(item["dataset_id"])))


_TERMINAL_STATUS_VALUES = frozenset({"succeeded", "failed", "cancelled"})


class LocalRunStore:
    def __init__(self, runs_root: Path) -> None:
        self._root = Path(runs_root).resolve()

    @property
    def runs_root(self) -> Path:
        return self._root

    def _run_dir(self, run_id: str, session_id: str) -> Path:
        _validate_uuid(run_id, label="run_id")
        _validate_uuid(session_id, label="session_id")
        return _safe_join(self._root, session_id, "runs", run_id)

    def create(self, run: Run) -> None:
        d = self._run_dir(run.run_id, run.session_id)
        d.mkdir(parents=True, exist_ok=True)
        self._write_manifest(d, run)

    def get(self, run_id: str, session_id: str) -> Run:
        d = self._run_dir(run_id, session_id)
        manifest_path = d / "manifest.json"
        if not manifest_path.exists():
            raise QuantLabError(
                ErrorCode.UNKNOWN_REFERENCE,
                "Run is not registered in the current session.",
                details={"run_id": run_id},
            )
        return Run.model_validate(_read_json(manifest_path))

    def session_for(self, run_id: str) -> str:
        """Locate the session that owns the given run by scanning session dirs."""
        _validate_uuid(run_id, label="run_id")
        if not self._root.exists():
            raise QuantLabError(
                ErrorCode.UNKNOWN_REFERENCE,
                "Runs directory does not exist.",
                details={"run_id": run_id},
            )
        for session_dir in self._root.iterdir():
            if not session_dir.is_dir():
                continue
            run_dir = session_dir / "runs" / run_id
            if (run_dir / "manifest.json").exists():
                return session_dir.name
        raise QuantLabError(
            ErrorCode.UNKNOWN_REFERENCE,
            "Run is not registered in any session.",
            details={"run_id": run_id},
        )

    def transition(
        self,
        run_id: str,
        session_id: str,
        *,
        expected_status: RunStatus,
        new_status: RunStatus,
        failure: dict | None = None,
        completed_at: datetime | None = None,
    ) -> Run:
        current = self.get(run_id, session_id)
        if current.status is not expected_status:
            raise QuantLabError(
                ErrorCode.STALE_RUN,
                "Run is not in the expected state for this transition.",
                details={
                    "expected_status": expected_status.value,
                    "actual_status": current.status.value,
                    "requested_status": new_status.value,
                },
            )
        now = datetime.now(UTC)
        new_completed = (
            completed_at
            if completed_at is not None
            else (now if new_status.value in _TERMINAL_STATUS_VALUES else current.completed_at)
        )
        updated = current.model_copy(
            update={
                "status": new_status,
                "failure": failure if failure is not None else current.failure,
                "completed_at": new_completed,
            }
        )
        d = self._run_dir(run_id, session_id)
        self._write_manifest(d, updated)
        return self.get(run_id, session_id)

    def bind_analysis(self, run_id: str, session_id: str, analysis_id: str) -> Run:
        return self._bind(run_id, session_id, {"analysis_id": analysis_id})

    def bind_metrics(self, run_id: str, session_id: str, metrics_id: str) -> Run:
        return self._bind(run_id, session_id, {"metrics_id": metrics_id})

    def bind_chart(self, run_id: str, session_id: str, chart_id: str) -> Run:
        current = self.get(run_id, session_id)
        if chart_id in current.chart_ids:
            return current
        return self._bind(run_id, session_id, {"chart_ids": current.chart_ids + (chart_id,)})

    def bind_report(self, run_id: str, session_id: str, report_id: str) -> Run:
        return self._bind(run_id, session_id, {"report_id": report_id})

    def add_dataset(self, run_id: str, session_id: str, dataset_id: str) -> Run:
        current = self.get(run_id, session_id)
        if dataset_id in current.dataset_ids:
            return current
        return self._bind(run_id, session_id, {"dataset_ids": current.dataset_ids + (dataset_id,)})

    def update_context_snapshot(
        self, run_id: str, session_id: str, context_snapshot: dict[str, Any]
    ) -> Run:
        return self._bind(run_id, session_id, {"context_snapshot": dict(context_snapshot)})

    def increment_tool_executions(self, run_id: str, session_id: str) -> Run:
        current = self.get(run_id, session_id)
        updated = current.model_copy(
            update={
                "counters": current.counters.model_copy(
                    update={"tool_executions_used": current.counters.tool_executions_used + 1}
                )
            }
        )
        self._write_manifest(self._run_dir(run_id, session_id), updated)
        return self.get(run_id, session_id)

    def increment_model_interactions(self, run_id: str, session_id: str) -> Run:
        current = self.get(run_id, session_id)
        updated = current.model_copy(
            update={
                "counters": current.counters.model_copy(
                    update={"model_interactions_used": current.counters.model_interactions_used + 1}
                )
            }
        )
        self._write_manifest(self._run_dir(run_id, session_id), updated)
        return self.get(run_id, session_id)

    def append_tool_call(self, run_id: str, session_id: str, record: ToolCallRecord) -> None:
        d = self._run_dir(run_id, session_id)
        d.mkdir(parents=True, exist_ok=True)
        path = d / "tool_calls.jsonl"
        line = json.dumps(record.model_dump(mode="json"), ensure_ascii=False) + "\n"
        with path.open("ab") as fh:
            fh.write(line.encode("utf-8"))
            fh.flush()
            os.fsync(fh.fileno())

    def list_tool_calls(self, run_id: str, session_id: str) -> tuple[ToolCallRecord, ...]:
        d = self._run_dir(run_id, session_id)
        path = d / "tool_calls.jsonl"
        if not path.exists():
            return ()
        records: list[ToolCallRecord] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line:
                continue
            records.append(ToolCallRecord.model_validate(json.loads(line)))
        return tuple(records)

    # -- internal ---------------------------------------------------------

    def _bind(self, run_id: str, session_id: str, fields: dict[str, Any]) -> Run:
        current = self.get(run_id, session_id)
        updated = current.model_copy(update=fields)
        self._write_manifest(self._run_dir(run_id, session_id), updated)
        return self.get(run_id, session_id)

    def _write_manifest(self, d: Path, run: Run) -> None:
        d.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(d / "manifest.json", run.model_dump(mode="json"))


class LocalChartStore:
    """Charts are nested under the run directory:

    ``<root>/<session_id>/runs/<run_id>/charts/<chart_id>.png``
    ``<root>/<session_id>/runs/<run_id>/charts/<chart_id>.json``
    """

    def __init__(self, runs_root: Path) -> None:
        self._root = Path(runs_root).resolve()

    def _chart_dir(self, run_id: str, session_id: str, chart_id: str) -> Path:
        _validate_uuid(run_id, label="run_id")
        _validate_uuid(session_id, label="session_id")
        _validate_uuid(chart_id, label="chart_id")
        return _safe_join(self._root, session_id, "runs", run_id, "charts", chart_id)

    def save(
        self,
        chart: ChartArtifact,
        *,
        session_id: str,
        png_bytes: bytes,
        data_payload: dict,
    ) -> None:
        d = self._chart_dir(chart.run_id, session_id, chart.chart_id)
        d.mkdir(parents=True, exist_ok=True)
        _atomic_write_bytes(d / f"{chart.kind.value}.png", png_bytes)
        _atomic_write_json(d / f"{chart.kind.value}.json", data_payload)
        _atomic_write_json(d / "chart.json", chart.model_dump(mode="json"))

    def get(self, chart_id: str, session_id: str, run_id: str) -> ChartArtifact:
        d = self._chart_dir(run_id, session_id, chart_id)
        manifest = d / "chart.json"
        if not manifest.exists():
            raise QuantLabError(
                ErrorCode.UNKNOWN_REFERENCE,
                "Chart is not registered in the current run.",
                details={"chart_id": chart_id, "run_id": run_id},
            )
        return ChartArtifact.model_validate(_read_json(manifest))

    def get_png_path(self, chart_id: str, session_id: str, run_id: str) -> str:
        d = self._chart_dir(run_id, session_id, chart_id)
        pngs = sorted(d.glob("*.png"))
        if not pngs:
            raise QuantLabError(
                ErrorCode.UNKNOWN_REFERENCE,
                "Chart PNG is missing.",
                details={"chart_id": chart_id},
            )
        return str(pngs[0].resolve(strict=False))

    def get_data_path(self, chart_id: str, session_id: str, run_id: str) -> str:
        d = self._chart_dir(run_id, session_id, chart_id)
        jsons = sorted(p for p in d.glob("*.json") if p.name != "chart.json")
        if not jsons:
            raise QuantLabError(
                ErrorCode.UNKNOWN_REFERENCE,
                "Chart data file is missing.",
                details={"chart_id": chart_id},
            )
        return str(jsons[0].resolve(strict=False))


class LocalReportStore:
    """Reports are nested under the run directory:

    ``<root>/<session_id>/runs/<run_id>/report.md``
    ``<root>/<session_id>/runs/<run_id>/report.json``
    """

    def __init__(self, runs_root: Path) -> None:
        self._root = Path(runs_root).resolve()

    def _report_dir(self, run_id: str, session_id: str, report_id: str) -> Path:
        _validate_uuid(run_id, label="run_id")
        _validate_uuid(session_id, label="session_id")
        _validate_uuid(report_id, label="report_id")
        return _safe_join(self._root, session_id, "runs", run_id, "reports", report_id)

    def save(self, report: ReportArtifact, *, session_id: str, markdown: str) -> None:
        d = self._report_dir(report.run_id, session_id, report.report_id)
        d.mkdir(parents=True, exist_ok=True)
        _atomic_write_bytes(d / "report.md", markdown.encode("utf-8"))
        _atomic_write_json(d / "report.json", report.model_dump(mode="json"))

    def get(self, report_id: str, session_id: str, run_id: str) -> ReportArtifact:
        d = self._report_dir(run_id, session_id, report_id)
        manifest = d / "report.json"
        if not manifest.exists():
            raise QuantLabError(
                ErrorCode.UNKNOWN_REFERENCE,
                "Report is not registered in the current run.",
                details={"report_id": report_id, "run_id": run_id},
            )
        return ReportArtifact.model_validate(_read_json(manifest))

    def get_markdown_path(self, report_id: str, session_id: str, run_id: str) -> str:
        d = self._report_dir(run_id, session_id, report_id)
        path = d / "report.md"
        if not path.exists():
            raise QuantLabError(
                ErrorCode.UNKNOWN_REFERENCE,
                "Report markdown is missing.",
                details={"report_id": report_id},
            )
        return str(path.resolve(strict=False))

    def _session_for(self, run_id: str) -> str:
        if not self._root.exists():
            raise QuantLabError(
                ErrorCode.UNKNOWN_REFERENCE,
                "Runs directory does not exist.",
                details={"run_id": run_id},
            )
        for session_dir in self._root.iterdir():
            if not session_dir.is_dir():
                continue
            run_dir = session_dir / "runs" / run_id
            if (run_dir / "manifest.json").exists():
                return session_dir.name
        raise QuantLabError(
            ErrorCode.UNKNOWN_REFERENCE,
            "Report references an unknown run.",
            details={"run_id": run_id},
        )


__all__ = [
    "LocalDatasetStore",
    "LocalRunStore",
    "LocalChartStore",
    "LocalReportStore",
    "utcnow",
]
