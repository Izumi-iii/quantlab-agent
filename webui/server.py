"""Minimal stdlib HTTP server for the QuantLab Agent demo UI.

Serves the static ``index.html`` (plus any sibling assets) and exposes
a small JSON API the page calls to drive ``AgentController`` /
``DemoController``:

    POST /api/sessions/{sid}/datasets        — upload a CSV (multipart)
    GET  /api/sessions/{sid}/datasets        — list imported datasets
    GET  /api/sessions/{sid}/datasets/{dsid}.csv — normalized CSV (text)
    POST /api/sessions/{sid}/messages        — send user text, run agent
    GET  /api/runs/{rid}                     — get run state + tool calls
    GET  /api/runs/{rid}/chart/{cid}.png     — chart PNG (binary)
    GET  /api/runs/{rid}/report/{rid2}.md    — report markdown (text)
    GET  /api/runs/{rid}/dataset/{dsid}.csv  — normalized CSV (text)
    GET  /api/healthz                        — liveness check
    GET  /                                    — serve index.html

No third-party deps. All routes are synchronous and the agent loop is
driven inside the request thread (the loop is fast for the demo
controller; for real models it still returns within the configured
budget). For multi-user workloads, swap this out for Starlette /
FastAPI; the JSON contracts here are the contract.
"""

from __future__ import annotations

import json
import logging
import mimetypes
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import date as _date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from quantlab_agent.adapters.local_stores import LocalDatasetStore
from quantlab_agent.agent.demo import DemoController, default_demo_controller
from quantlab_agent.application.datasets import DatasetService
from quantlab_agent.config import ModelConfig, load_config
from quantlab_agent.domain.errors import QuantLabError
from quantlab_agent.domain.models import (
    DatasetMetadata,
    MetricName,
    PriceBasis,
    RunMode,
)

log = logging.getLogger("quantlab_agent.webui")

STATIC_DIR = Path(__file__).parent / "static"

# --- regexes for path routing --------------------------------------------

_SID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_RID = _SID
_CID = _SID
_RE_DATASETS = re.compile(rf"^/api/sessions/({_SID})/datasets/?$")
_RE_SESSION_CSV = re.compile(rf"^/api/sessions/({_SID})/datasets/({_SID})\.csv$")
_RE_MESSAGES = re.compile(rf"^/api/sessions/({_SID})/messages/?$")
_RE_RUN = re.compile(rf"^/api/runs/({_RID})/?$")
_RE_CHART = re.compile(rf"^/api/runs/({_RID})/chart/({_CID})\.png$")
_RE_REPORT = re.compile(rf"^/api/runs/({_RID})/report/({_RID})\.md$")
_RE_CSV = re.compile(rf"^/api/runs/({_RID})/dataset/({_SID})\.csv$")

CONTENT_TYPE_JSON = "application/json; charset=utf-8"


# --- minimal multipart/form-data parser ---------------------------------


@dataclass
class _FormFile:
    filename: str
    content_type: str
    data: bytes


def _parse_multipart(body: bytes, content_type_header: str) -> dict[str, Any]:
    """Parse ``multipart/form-data`` without external deps.

    Only enough for the upload endpoint: text fields and one file field.
    Returns a dict keyed by field name. File values are ``_FormFile``
    instances; text values are plain ``str``.
    """
    # Extract boundary from Content-Type (e.g. "multipart/form-data; boundary=----abc").
    match = re.search(r"boundary=(?:\"([^\"]+)\"|([^\s;]+))", content_type_header)
    if not match:
        raise BadRequest("Content-Type missing boundary")
    boundary = (match.group(1) or match.group(2)).encode("ascii")
    sep = b"--" + boundary
    # Split body into parts. The first item (before the first boundary)
    # is the preamble; the last item (after the closing boundary) is the
    # epilogue. Both are discarded.
    raw_parts = body.split(sep)
    fields: dict[str, Any] = {}
    for raw in raw_parts[1:-1]:
        # Each part starts with \r\n after the boundary marker (the boundary
        # line itself ends with \r\n); strip that leading CRLF.
        if raw.startswith(b"\r\n"):
            raw = raw[2:]
        if raw.endswith(b"\r\n"):
            raw = raw[:-2]
        if not raw:
            continue
        # Split headers from body on CRLFCRLF.
        try:
            head_blob, body_blob = raw.split(b"\r\n\r\n", 1)
        except ValueError as exc:
            raise BadRequest("malformed multipart part") from exc
        headers = _parse_message_headers(head_blob.decode("ascii", errors="replace"))
        disposition = headers.get("content-disposition", "")
        name, filename = _parse_content_disposition(disposition)
        if name is None:
            continue
        if filename is not None:
            fields[name] = _FormFile(
                filename=filename,
                content_type=headers.get("content-type", "application/octet-stream"),
                data=body_blob,
            )
        else:
            fields[name] = body_blob.decode("utf-8", errors="replace")
    return fields


def _parse_message_headers(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.split("\r\n"):
        if not line or ":" not in line:
            continue
        key, _, value = line.partition(":")
        out[key.strip().lower()] = value.strip()
    return out


def _parse_content_disposition(value: str) -> tuple[str | None, str | None]:
    name: str | None = None
    filename: str | None = None
    for part in value.split(";"):
        part = part.strip()
        if part.startswith("name="):
            v = part[5:]
            name = v[1:-1] if v.startswith(('"', "'")) else v
        elif part.startswith("filename="):
            v = part[9:]
            filename = v[1:-1] if v.startswith(('"', "'")) else v
    return name, filename


# --- shared state ---------------------------------------------------------


@dataclass
class WebState:
    """Per-server state shared across request threads.

    Holds the demo controller and a small per-session model override.
    The override lives in-process; restart the server to clear it.
    """

    runs_dir: Path
    controller: DemoController
    dataset_service: DatasetService
    dataset_store: LocalDatasetStore
    ui_model_overrides: dict[str, ModelConfig] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


def build_state(runs_dir: Path) -> WebState:
    runs_dir = Path(runs_dir).resolve()
    controller = default_demo_controller(runs_dir)
    return WebState(
        runs_dir=runs_dir,
        controller=controller,
        dataset_service=DatasetService(),
        dataset_store=controller.dataset_store,
    )


# --- serialization helpers -----------------------------------------------


def _serialize_run(run) -> dict[str, Any]:
    """Convert a Run to a JSON-safe dict. Tool-call records are loaded
    separately via the ``include_tool_calls`` path.
    """
    payload: dict[str, Any] = {
        "run_id": run.run_id,
        "session_id": run.session_id,
        "mode": run.mode.value,
        "status": run.status.value,
        "user_request": run.user_request,
        "dataset_ids": list(run.dataset_ids),
        "analysis_id": run.analysis_id,
        "metrics_id": run.metrics_id,
        "chart_ids": list(run.chart_ids),
        "report_id": run.report_id,
        "failure": run.failure,
        "counters": {
            "tool_executions_used": run.counters.tool_executions_used,
            "model_interactions_used": run.counters.model_interactions_used,
            "same_validation_retries_used": run.counters.same_validation_retries_used,
            "retryable_network_errors_used": run.counters.retryable_network_errors_used,
        },
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
    }
    return payload


def _serialize_tool_call(record) -> dict[str, Any]:
    envelope = record.result_envelope
    return {
        "tool_call_id": record.tool_call_id,
        "tool_name": record.tool_name,
        "status": record.status.value,
        "error_code": record.error_code,
        "started_at": record.started_at.isoformat() if record.started_at else None,
        "completed_at": (record.completed_at.isoformat() if record.completed_at else None),
        "arguments": record.arguments_redacted,
        "ok": envelope.ok if envelope else None,
        "data": envelope.data if envelope else None,
        "warnings": list(envelope.warnings) if envelope else [],
        "error": envelope.error if envelope else None,
        "provenance": envelope.provenance.model_dump(mode="json")
        if envelope and envelope.provenance
        else None,
    }


def _serialize_dataset(summary: dict[str, object]) -> dict[str, object]:
    return {
        "dataset_id": summary["dataset_id"],
        "asset_id": summary["asset_id"],
        "date_min": summary["date_min"],
        "date_max": summary["date_max"],
        "row_count": summary["row_count"],
    }


# --- request handlers -----------------------------------------------------


class _Handler(BaseHTTPRequestHandler):
    server_version = "QuantLabAgentWebUI/1.0"

    # Silence the default per-request stderr access log; we'll log via the
    # module logger instead.
    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        log.debug(format, *args)

    # ----- low-level helpers -----

    @property
    def state(self) -> WebState:
        return self.server.state  # type: ignore[attr-defined]

    def _write_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", CONTENT_TYPE_JSON)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _write_error(self, status: int, code: str, message: str) -> None:
        self._write_json(status, {"error": {"code": code, "message": message}})

    def _write_bytes(self, status: int, body: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            return {}
        raw = self.rfile.read(length)
        try:
            data = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise BadRequest(f"invalid JSON body: {exc}") from exc
        if not isinstance(data, dict):
            raise BadRequest("request body must be a JSON object")
        return data

    # ----- dispatch -----

    def do_GET(self) -> None:  # noqa: N802 - stdlib name
        try:
            self._dispatch_get()
        except BadRequest as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, "BAD_REQUEST", str(exc))
        except NotFound as exc:
            self._write_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", str(exc))
        except QuantLabError as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, exc.code.value, exc.message)
        except Exception as exc:  # noqa: BLE001
            log.exception("GET %s failed", self.path)
            self._write_error(
                HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL", f"{type(exc).__name__}: {exc}"
            )

    def do_POST(self) -> None:  # noqa: N802 - stdlib name
        try:
            self._dispatch_post()
        except BadRequest as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, "BAD_REQUEST", str(exc))
        except NotFound as exc:
            self._write_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", str(exc))
        except QuantLabError as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, exc.code.value, exc.message)
        except Exception as exc:  # noqa: BLE001
            log.exception("POST %s failed", self.path)
            self._write_error(
                HTTPStatus.INTERNAL_SERVER_ERROR, "INTERNAL", f"{type(exc).__name__}: {exc}"
            )

    # ----- GET dispatch -----

    def _dispatch_get(self) -> None:
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            self._serve_index()
            return
        if path == "/api/healthz":
            self._write_json(HTTPStatus.OK, {"status": "ok", "ts": time.time()})
            return
        if path == "/api/config":
            self._handle_get_config()
            return
        m = _RE_DATASETS.match(path)
        if m:
            self._handle_list_datasets(m.group(1))
            return
        m = _RE_SESSION_CSV.match(path)
        if m:
            self._handle_get_session_csv(m.group(1), m.group(2))
            return
        m = _RE_RUN.match(path)
        if m:
            self._handle_get_run(m.group(1))
            return
        m = _RE_CHART.match(path)
        if m:
            self._handle_get_chart(m.group(1), m.group(2))
            return
        m = _RE_REPORT.match(path)
        if m:
            self._handle_get_report(m.group(1), m.group(2))
            return
        m = _RE_CSV.match(path)
        if m:
            self._handle_get_csv(m.group(1), m.group(2))
            return
        # Fall back to static file serving (e.g. /static/foo.js).
        if path.startswith("/static/"):
            self._serve_static(path.removeprefix("/static/"))
            return
        raise NotFound(f"no route for GET {path}")

    # ----- POST dispatch -----

    def _dispatch_post(self) -> None:
        path = urlparse(self.path).path
        ctype = self.headers.get("Content-Type", "")
        m = _RE_DATASETS.match(path)
        if m:
            if "multipart/form-data" not in ctype:
                raise BadRequest("Content-Type must be multipart/form-data for upload")
            self._handle_upload_dataset(m.group(1))
            return
        m = _RE_MESSAGES.match(path)
        if m:
            self._handle_post_message(m.group(1))
            return
        raise NotFound(f"no route for POST {path}")

    # ----- concrete endpoints -----

    def _serve_index(self) -> None:
        html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
        self._write_bytes(HTTPStatus.OK, html.encode("utf-8"), "text/html; charset=utf-8")

    def _serve_static(self, rel: str) -> None:
        # Reject any traversal attempts.
        if ".." in rel or rel.startswith(("/", "\\")):
            raise NotFound("invalid static path")
        target = (STATIC_DIR / rel).resolve()
        try:
            target.relative_to(STATIC_DIR.resolve())
        except ValueError as exc:
            raise NotFound("static path escapes root") from exc
        if not target.is_file():
            raise NotFound(f"no such file: {rel}")
        content_type, _ = mimetypes.guess_type(str(target))
        self._write_bytes(
            HTTPStatus.OK, target.read_bytes(), content_type or "application/octet-stream"
        )

    def _handle_get_config(self) -> None:
        env = load_config().model
        overrides = {
            sid: {
                "base_url": m.base_url,
                "model": m.model,
                "configured": True,
            }
            for sid, m in self.state.ui_model_overrides.items()
        }
        self._write_json(
            HTTPStatus.OK,
            {
                "env_configured": env.configured,
                "env_model": env.model if env.configured else None,
                "ui_overrides": overrides,
            },
        )

    def _handle_list_datasets(self, session_id: str) -> None:
        items = self.state.dataset_store.list_in_session(session_id)
        self._write_json(HTTPStatus.OK, {"datasets": [_serialize_dataset(i) for i in items]})

    def _handle_upload_dataset(self, session_id: str) -> None:
        """Parse multipart/form-data, save the CSV, return dataset summary."""
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length <= 0:
            raise BadRequest("empty multipart body")
        body = self.rfile.read(length)
        fields = _parse_multipart(body, self.headers.get("Content-Type", ""))
        csv_field = fields.get("file")
        asset_id = (fields.get("asset_id") or "").strip()
        price_basis_raw = (fields.get("price_basis") or "forward_adjusted").strip()
        if csv_field is None or csv_field.data is None or csv_field.filename is None:
            raise BadRequest("missing 'file' part in multipart body")
        if not asset_id:
            raise BadRequest("missing 'asset_id' field")
        try:
            price_basis = PriceBasis(price_basis_raw)
        except ValueError as exc:
            raise BadRequest(f"invalid price_basis: {price_basis_raw}") from exc
        bytes_data = csv_field.data
        metadata = DatasetMetadata(
            asset_id=asset_id,
            source_name="web upload",
            price_basis=price_basis,
            currency="CNY",
            frequency="daily",
            calendar_label="user provided",
            daily_series_complete=True,
            is_synthetic=False,
        )
        result = self.state.dataset_service.import_csv(
            bytes_data, metadata=metadata, session_id=session_id
        )
        if result.dataset is None:
            issues = [f"{issue.code}: {issue.message}" for issue in result.quality_report.issues]
            raise BadRequest("quality gate rejected the upload: " + "; ".join(issues))
        dataset = result.dataset
        self.state.dataset_store.save(dataset, session_id)
        self._write_json(
            HTTPStatus.CREATED,
            {
                "dataset": _serialize_dataset(
                    {
                        "dataset_id": dataset.manifest.dataset_id,
                        "asset_id": dataset.manifest.metadata.asset_id,
                        "date_min": dataset.manifest.date_min.isoformat(),
                        "date_max": dataset.manifest.date_max.isoformat(),
                        "row_count": dataset.manifest.row_count,
                    }
                ),
            },
        )

    def _handle_post_message(self, session_id: str) -> None:
        body = self._read_json_body()
        text = (body.get("text") or "").strip()
        if not text:
            raise BadRequest("'text' field is required and must be non-empty")
        start = body.get("start") or "2024-01-02"
        end = body.get("end") or "2024-01-15"
        metrics_raw = body.get("metrics") or ["period_return", "max_drawdown"]
        try:
            metrics = tuple(MetricName(m) for m in metrics_raw)
        except ValueError as exc:
            raise BadRequest(f"invalid metric name: {exc}") from exc
        # Validate dates.
        try:
            _date.fromisoformat(start)
            _date.fromisoformat(end)
        except ValueError as exc:
            raise BadRequest(f"invalid date: {exc}") from exc

        run_service = self.state.controller._runs  # type: ignore[attr-defined]
        datasets = self.state.dataset_store.list_in_session(session_id)
        if not datasets:
            raise BadRequest("no datasets imported in this session — upload at least one CSV first")
        dataset_ids = [d["dataset_id"] for d in datasets]  # type: ignore[index]

        run = run_service.create_run(
            session_id=session_id,
            mode=RunMode.DEMO,
            user_request=text,
        )
        try:
            for ds_id in dataset_ids:
                run_service.add_dataset(run.run_id, session_id, ds_id)
            self.state.controller._execute_pipeline(  # type: ignore[attr-defined]
                run_id=run.run_id,
                session_id=session_id,
                dataset_ids=dataset_ids,
                requested_start=start,
                requested_end=end,
                requested_metrics=tuple(m.value for m in metrics),
            )
        except QuantLabError:
            # Pipeline errors are reflected in the run state; don't fail the
            # request — the client will see them in the returned envelope.
            pass
        final = run_service.get_run(run.run_id, session_id)
        records = run_service.list_tool_calls(run.run_id, session_id)
        self._write_json(
            HTTPStatus.OK,
            {
                "run": _serialize_run(final),
                "tool_calls": [_serialize_tool_call(r) for r in records],
            },
        )

    def _handle_get_run(self, run_id: str) -> None:
        run_service = self.state.controller._runs  # type: ignore[attr-defined]
        # Locate the owning session by scanning.
        session_id = self.state.controller._runs._runs.session_for(run_id)  # type: ignore[attr-defined]
        run = run_service.get_run(run_id, session_id)
        records = run_service.list_tool_calls(run_id, session_id)
        self._write_json(
            HTTPStatus.OK,
            {
                "run": _serialize_run(run),
                "tool_calls": [_serialize_tool_call(r) for r in records],
            },
        )

    def _handle_get_chart(self, run_id: str, chart_id: str) -> None:
        session_id = self.state.controller._runs._runs.session_for(run_id)  # type: ignore[attr-defined]
        png_path = self.state.controller.chart_store.get_png_path(chart_id, session_id, run_id)
        self._write_bytes(HTTPStatus.OK, Path(png_path).read_bytes(), "image/png")

    def _handle_get_report(self, run_id: str, report_id: str) -> None:
        session_id = self.state.controller._runs._runs.session_for(run_id)  # type: ignore[attr-defined]
        md_path = self.state.controller.report_store.get_markdown_path(
            report_id, session_id, run_id
        )
        body = Path(md_path).read_text(encoding="utf-8")
        self._write_bytes(HTTPStatus.OK, body.encode("utf-8"), "text/markdown; charset=utf-8")

    def _handle_get_csv(self, run_id: str, dataset_id: str) -> None:
        session_id = self.state.controller._runs._runs.session_for(run_id)  # type: ignore[attr-defined]
        csv_path = self.state.dataset_store.get_normalized_csv_path(dataset_id, session_id)
        body = Path(csv_path).read_text(encoding="utf-8")
        self._write_bytes(HTTPStatus.OK, body.encode("utf-8"), "text/csv; charset=utf-8")

    def _handle_get_session_csv(self, session_id: str, dataset_id: str) -> None:
        csv_path = self.state.dataset_store.get_normalized_csv_path(dataset_id, session_id)
        body = Path(csv_path).read_text(encoding="utf-8")
        self._write_bytes(HTTPStatus.OK, body.encode("utf-8"), "text/csv; charset=utf-8")


class BadRequest(Exception):
    """Raised inside a handler to return HTTP 400 with a message."""


class NotFound(Exception):
    """Raised inside a handler to return HTTP 404 with a message."""


# --- server bootstrap -----------------------------------------------------


class _ThreadingServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that carries a ``state`` attribute."""

    def __init__(self, addr: tuple[str, int], handler: type[_Handler], state: WebState):
        self.state = state
        super().__init__(addr, handler)


def serve(
    *,
    host: str = "127.0.0.1",
    port: int = 8765,
    runs_dir: Path = Path("runs"),
    block: bool = True,
) -> _ThreadingServer:
    """Start the web UI server. Returns the running server.

    When ``block=True`` (the default) this call does not return until
    the server is shut down. Pass ``block=False`` to start it in the
    background and run ``server.shutdown()`` from another thread.
    """
    state = build_state(runs_dir)
    server = _ThreadingServer((host, port), _Handler, state)
    log.info("QuantLab web UI listening on http://%s:%d (runs=%s)", host, port, runs_dir)
    if block:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            log.info("shutting down")
        finally:
            server.server_close()
    return server


__all__ = ["serve", "WebState", "build_state"]


if __name__ == "__main__":  # pragma: no cover
    import argparse

    parser = argparse.ArgumentParser(description="QuantLab Agent demo web UI")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--runs-dir", default="runs", type=Path)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    serve(host=args.host, port=args.port, runs_dir=args.runs_dir)
