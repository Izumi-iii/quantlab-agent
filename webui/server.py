"""Minimal stdlib HTTP server for the QuantLab Agent demo UI.

Serves the static ``index.html`` (plus any sibling assets) and exposes
a small JSON API the page calls to drive ``AgentController`` /
``DemoController``:

    POST /api/sessions/{sid}/datasets        — upload a CSV (multipart)
    GET  /api/sessions/{sid}/datasets        — list imported datasets
    GET  /api/sessions/{sid}/datasets/{dsid}.csv — normalized CSV (text)
    DELETE /api/sessions/{sid}/datasets/{dsid}  — delete imported dataset
    POST /api/sessions/{sid}/messages        — send user text, run agent
    GET  /api/runs/{rid}                     — get run state + tool calls
    GET  /api/runs/{rid}/chart/{cid}.png     — chart PNG (binary)
    GET  /api/runs/{rid}/chart/{cid}.json    — interactive chart data
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
from quantlab_agent.agent.plan_executor import PlanExecutor
from quantlab_agent.agent.plan_validator import PlanValidator
from quantlab_agent.agent.planner import PlannerContext, RulePlanner
from quantlab_agent.application.datasets import DatasetService
from quantlab_agent.config import ModelConfig, load_config
from quantlab_agent.domain.errors import QuantLabError
from quantlab_agent.domain.models import (
    AnalysisPlan,
    ChartKind,
    DatasetMetadata,
    DateRange,
    Intent,
    MetricName,
    PriceBasis,
    RunMode,
)
from webui.summary_presenters import summarize_run as _summarize_run_presenter

log = logging.getLogger("quantlab_agent.webui")

STATIC_DIR = Path(__file__).parent / "static"

# --- regexes for path routing --------------------------------------------

_SID = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
_RID = _SID
_CID = _SID
_RE_DATASETS = re.compile(rf"^/api/sessions/({_SID})/datasets/?$")
_RE_SESSION_DATASET = re.compile(rf"^/api/sessions/({_SID})/datasets/({_SID})/?$")
_RE_SESSION_CSV = re.compile(rf"^/api/sessions/({_SID})/datasets/({_SID})\.csv$")
_RE_MESSAGES = re.compile(rf"^/api/sessions/({_SID})/messages/?$")
_RE_RUN = re.compile(rf"^/api/runs/({_RID})/?$")
_RE_CHART = re.compile(rf"^/api/runs/({_RID})/chart/({_CID})\.png$")
_RE_CHART_DATA = re.compile(rf"^/api/runs/({_RID})/chart/({_CID})\.json$")
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
    registry: Any = None
    run_service: Any = None
    planner: Any = None
    plan_validator: Any = None
    plan_executor: Any = None
    ui_model_overrides: dict[str, ModelConfig] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)


def build_state(runs_dir: Path, *, model_config: ModelConfig | None = None) -> WebState:
    runs_dir = Path(runs_dir).resolve()
    controller = default_demo_controller(runs_dir)
    # Reach into the demo controller to extract the wired registry and run
    # service — both are reused by the planner pipeline. We deliberately
    # avoid duplicating wiring here; the demo controller already
    # composes the same graph.
    registry = controller._registry  # type: ignore[attr-defined]
    run_service = controller._runs  # type: ignore[attr-defined]
    plan_validator = PlanValidator(resolver=controller.dataset_store)
    plan_executor = PlanExecutor(registry=registry, run_service=run_service)

    # Pick a planner: LLM when configured, otherwise rule-based.
    from quantlab_agent.agent.planner_factory import build_planner

    planner = (
        build_planner(model_config) if model_config and model_config.configured else RulePlanner()
    )

    return WebState(
        runs_dir=runs_dir,
        controller=controller,
        dataset_service=DatasetService(),
        dataset_store=controller.dataset_store,
        registry=registry,
        run_service=run_service,
        planner=planner,
        plan_validator=plan_validator,
        plan_executor=plan_executor,
    )


# --- serialization helpers -----------------------------------------------


def _serialize_run(run, records: tuple[Any, ...] = ()) -> dict[str, Any]:
    """Convert a Run to a JSON-safe dict. Tool-call records are loaded
    separately via the ``include_tool_calls`` path.
    """
    snapshot = dict(run.context_snapshot or {})
    failure_details = (run.failure or {}).get("details") or {}
    intent = snapshot.get("intent") or failure_details.get("intent")
    user_visible_summary = snapshot.get("user_visible_summary") or failure_details.get(
        "user_visible_summary"
    )
    rich_summary = _derive_rich_summary(run, records, intent)
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
        "intent": intent,
        "plan_summary": snapshot.get("plan_summary"),
        "extras": list(snapshot.get("extras") or []),
        "summary": rich_summary
        or failure_details.get("clarifying_question")
        or user_visible_summary
        or _derive_summary(run),
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


def _derive_rich_summary(run, records: tuple[Any, ...], intent: str | None) -> str | None:
    presenter_text = _summarize_run_presenter(run, records)
    if intent == "report" and run.report_id and run.status.value == "succeeded":
        return "\n\n".join(
            text
            for text in (
                "报告已生成，已在右侧报告视图展示。对应图表仍可在图表视图查看。",
                _summarize_metrics(run, records),
                presenter_text,
            )
            if text
        )
    if intent == "metrics" or run.context_snapshot.get("answer_metrics"):
        base = _summarize_metrics(run, records)
        return "\n\n".join(text for text in (base, presenter_text) if text) or None
    if presenter_text is not None:
        return presenter_text
    if intent == "data_quality":
        return _summarize_data_quality(records)
    if intent == "metrics":
        return _summarize_metrics(run, records)
    if intent == "chart":
        return _summarize_chart(run, records)
    return None


_METRIC_LABELS = {
    "period_return": "区间收益",
    "max_drawdown": "最大回撤",
    "annualized_volatility": "年化波动率",
}


def _format_metric_value(metric_name: str, value: object) -> str:
    if value is None:
        return "不可用"
    if not isinstance(value, int | float):
        return str(value)
    if metric_name in {"period_return", "max_drawdown", "annualized_volatility"}:
        return f"{value * 100:.2f}%"
    return f"{value:.6g}"


def _summarize_metrics(run, records: tuple[Any, ...]) -> str | None:
    metrics_payload: dict[str, Any] | None = None
    for record in records:
        if record.tool_name != "compute_metrics" or record.status.value != "succeeded":
            continue
        data = record.result_envelope.data
        if isinstance(data, dict):
            metrics_payload = data
    if metrics_payload is None:
        return None

    snapshot = dict(run.context_snapshot or {})
    effective_start = snapshot.get("effective_start") or snapshot.get("requested_start")
    effective_end = snapshot.get("effective_end") or snapshot.get("requested_end")
    lines = ["指标计算完成。"]
    if effective_start and effective_end:
        lines.append(f"有效区间：{effective_start} 至 {effective_end}。")

    assets = metrics_payload.get("assets") or []
    if not assets:
        return "\n".join(lines)

    for asset in assets:
        asset_id = asset.get("asset_id", "UNKNOWN")
        lines.append(f"- {asset_id}")
        metrics = asset.get("metrics") or {}
        for metric_name, payload in metrics.items():
            label = _METRIC_LABELS.get(metric_name, metric_name)
            if not isinstance(payload, dict):
                lines.append(f"  - {label}: {payload}")
                continue
            value_text = _format_metric_value(metric_name, payload.get("value"))
            observations = payload.get("observations")
            reason = payload.get("unavailable_reason")
            suffix = f"，观测数 {observations}" if observations is not None else ""
            if reason:
                suffix += f"，原因：{reason}"
            lines.append(f"  - {label}: {value_text}{suffix}")
    return "\n".join(lines)


def _summarize_data_quality(records: tuple[Any, ...]) -> str | None:
    inspected: list[dict[str, Any]] = []
    for record in records:
        if record.tool_name != "inspect_dataset" or record.status.value != "succeeded":
            continue
        data = record.result_envelope.data
        if isinstance(data, dict):
            inspected.append(data)
    if not inspected:
        return None

    lines = ["数据质量检查完成。"]
    total_issues = 0
    for item in inspected:
        asset_id = item.get("asset_id", "UNKNOWN")
        row_count = item.get("row_count", "?")
        date_min = item.get("date_min", "?")
        date_max = item.get("date_max", "?")
        issues = item.get("quality_issues") or []
        issue_count = len(issues)
        total_issues += issue_count
        if issue_count:
            lines.append(
                f"- {asset_id}: {row_count} 行，覆盖 {date_min} 至 {date_max}，发现 {issue_count} 个质量问题。"
            )
            for issue in issues[:3]:
                severity = issue.get("severity", "unknown")
                code = issue.get("code", "UNKNOWN")
                message = issue.get("message", "")
                lines.append(f"  - {severity} / {code}: {message}")
            if issue_count > 3:
                lines.append(f"  - 另有 {issue_count - 3} 个问题，可展开工具调用链查看。")
        else:
            lines.append(
                f"- {asset_id}: {row_count} 行，覆盖 {date_min} 至 {date_max}，未发现质量问题。"
            )
    if total_issues == 0:
        lines.append("这些数据可以继续用于收益、回撤、波动率等指标分析。")
    return "\n".join(lines)


def _summarize_chart(run, records: tuple[Any, ...]) -> str | None:
    chart_payload: dict[str, Any] | None = None
    for record in records:
        if record.tool_name != "create_charts" or record.status.value != "succeeded":
            continue
        data = record.result_envelope.data
        if isinstance(data, dict):
            chart_payload = data
    if chart_payload is None:
        return None

    chart_ids = chart_payload.get("chart_ids") or []
    kinds = chart_payload.get("kinds") or []
    snapshot = dict(run.context_snapshot or {})
    effective_start = snapshot.get("effective_start") or snapshot.get("requested_start")
    effective_end = snapshot.get("effective_end") or snapshot.get("requested_end")

    lines = ["图表已生成。"]
    if effective_start and effective_end:
        lines.append(f"有效区间：{effective_start} 至 {effective_end}。")
    if kinds:
        labels = {
            "normalized_prices": "归一化价格走势",
            "drawdown": "回撤曲线",
        }
        kind_text = "、".join(labels.get(str(kind), str(kind)) for kind in kinds)
        lines.append(f"图表类型：{kind_text}。")
    lines.append(f"已生成 {len(chart_ids)} 张图，可在右侧图表查看。")
    return "\n".join(lines)


def _derive_summary(run) -> str | None:
    """Fallback message bubble text when no planner summary exists."""
    if run.status.value == "needs_clarification" and run.failure:
        details = run.failure.get("details") or {}
        question = details.get("clarifying_question") or run.failure.get("message")
        if question:
            return f"需要更多信息：{question}"
    if run.status.value == "failed" and run.failure:
        if run.failure.get("code") == "OUT_OF_SCOPE":
            return "超出范围：我目前只处理已上传 CSV 的历史价格数据分析。"
        msg = run.failure.get("message")
        if msg:
            return f"分析失败：{msg}"
    if run.status.value == "succeeded":
        return "已完成分析。点击此处查看报告。"
    return None


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

    def do_DELETE(self) -> None:  # noqa: N802 - stdlib name
        try:
            self._dispatch_delete()
        except BadRequest as exc:
            self._write_error(HTTPStatus.BAD_REQUEST, "BAD_REQUEST", str(exc))
        except NotFound as exc:
            self._write_error(HTTPStatus.NOT_FOUND, "NOT_FOUND", str(exc))
        except QuantLabError as exc:
            status = (
                HTTPStatus.NOT_FOUND
                if exc.code.value == "UNKNOWN_REFERENCE"
                else HTTPStatus.BAD_REQUEST
            )
            self._write_error(status, exc.code.value, exc.user_message, details=exc.details)
        except Exception as exc:  # noqa: BLE001
            log.exception("DELETE %s failed", self.path)
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
        m = _RE_CHART_DATA.match(path)
        if m:
            self._handle_get_chart_data(m.group(1), m.group(2))
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

    def _dispatch_delete(self) -> None:
        path = urlparse(self.path).path
        m = _RE_SESSION_DATASET.match(path)
        if m:
            self._handle_delete_dataset(m.group(1), m.group(2))
            return
        raise NotFound(f"no route for DELETE {path}")

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

    def _handle_delete_dataset(self, session_id: str, dataset_id: str) -> None:
        self.state.dataset_store.delete(dataset_id, session_id)
        self._write_json(HTTPStatus.OK, {"deleted": True, "dataset_id": dataset_id})

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

        datasets = self.state.dataset_store.list_in_session(session_id)
        if not datasets:
            raise BadRequest("no datasets imported in this session — upload at least one CSV first")

        run = self.state.run_service.create_run(
            session_id=session_id,
            mode=RunMode.DEMO,
            user_request=text,
        )
        try:
            # Planner → Validator → Executor pipeline.
            previous = None
            previous_count = 0
            reference_run_id = body.get("context_run_id")
            if reference_run_id:
                source = self.state.run_service.get_run(reference_run_id, session_id)
                if source.status.value == "succeeded" and source.analysis_id:
                    charts = [
                        self.state.controller.chart_store.get(cid, session_id, source.run_id)
                        for cid in source.chart_ids
                    ]
                    snapshot = source.context_snapshot
                    previous = AnalysisPlan(
                        intent=Intent.METRICS,
                        dataset_refs=source.dataset_ids,
                        date_range=DateRange(
                            start=snapshot["effective_start"], end=snapshot["effective_end"]
                        ),
                        charts=tuple(dict.fromkeys(chart.kind for chart in charts))
                        or tuple(ChartKind(kind) for kind in snapshot.get("requested_charts", [])),
                        metrics=tuple(
                            MetricName(name) for name in snapshot.get("requested_metrics", [])
                        )
                        or (MetricName.PERIOD_RETURN, MetricName.MAX_DRAWDOWN),
                        rolling_windows=tuple(
                            dict.fromkeys(
                                chart.window for chart in charts if chart.window is not None
                            )
                        )
                        or tuple(snapshot.get("rolling_windows", [60])),
                    )
                    previous_count = len(charts)
            ctx = PlannerContext(
                session_id=session_id,
                dataset_summaries=tuple(datasets),
                previous_analysis=previous,
                previous_chart_count=previous_count,
            )
            if previous is not None:
                self.state.run_service.update_context_snapshot(
                    run.run_id, session_id, {"reference_run_id": reference_run_id}
                )
            plan = self.state.planner.plan(text, ctx)
            resolved_or_exc = self.state.plan_validator.validate(plan, session_id=session_id)
            # If the plan needs explicit date/metric params that the user
            # supplied in the JSON body, prefer those (legacy form).
            resolved_or_exc = self._apply_legacy_overrides(resolved_or_exc, body, datasets)
            self.state.plan_executor.execute(
                run_id=run.run_id,
                session_id=session_id,
                plan=resolved_or_exc,
            )
        except QuantLabError as exc:
            # Pipeline errors are reflected in the run state; record them
            # so the UI sees a FAILED status and details.
            try:
                self.state.run_service.mark_failed(
                    run.run_id,
                    session_id,
                    code=exc.code.value,
                    message=str(exc),
                    retryable=exc.retryable,
                    details=exc.details,
                )
            except QuantLabError:
                pass
        except Exception as exc:  # noqa: BLE001 - top-level guard
            log.exception("planner pipeline failed")
            try:
                self.state.run_service.mark_failed(
                    run.run_id,
                    session_id,
                    code="TOOL_FAILURE",
                    message=f"{type(exc).__name__}: {exc}",
                    retryable=False,
                )
            except QuantLabError:
                pass

        final = self.state.run_service.get_run(run.run_id, session_id)
        records = self.state.run_service.list_tool_calls(run.run_id, session_id)
        self._write_json(
            HTTPStatus.OK,
            {
                "run": _serialize_run(final, tuple(records)),
                "tool_calls": [_serialize_tool_call(r) for r in records],
            },
        )

    def _apply_legacy_overrides(self, plan, body, datasets):
        """Allow the JSON body to pin a date range / metric set for the
        legacy form-based path. The planner's output wins by intent; body
        start/end and metrics can refine a resolved plan for old clients.
        """
        from quantlab_agent.domain.models import DateRange, ResolvedPlan

        if not isinstance(plan, ResolvedPlan):
            return plan
        start = body.get("start")
        end = body.get("end")
        metrics_raw = body.get("metrics")
        new_range = plan.date_range
        if start and end:
            try:
                _date.fromisoformat(start)
                _date.fromisoformat(end)
                new_range = DateRange(start=start, end=end)
            except ValueError:
                pass
        new_metrics = plan.metrics
        if metrics_raw:
            try:
                new_metrics = tuple(MetricName(m) for m in metrics_raw)
            except ValueError:
                pass
        effective_start, effective_end = plan.effective_start, plan.effective_end
        if new_range is not plan.date_range:
            effective_start, effective_end = self._resolve_effective_range(
                new_range,
                plan.resolved_dataset_ids,
                datasets,
            )
        return plan.model_copy(
            update={
                "date_range": new_range,
                "effective_start": effective_start,
                "effective_end": effective_end,
                "metrics": new_metrics,
            }
        )

    @staticmethod
    def _resolve_effective_range(date_range, resolved_dataset_ids, datasets):
        by_id = {item["dataset_id"]: item for item in datasets}
        coverage = [by_id[ds_id] for ds_id in resolved_dataset_ids if ds_id in by_id]
        if not coverage:
            return (None, None)
        coverage_min = min(_date.fromisoformat(item["date_min"]) for item in coverage)
        coverage_max = max(_date.fromisoformat(item["date_max"]) for item in coverage)
        if date_range is None:
            return coverage_min, coverage_max
        effective_start = max(date_range.start, coverage_min)
        effective_end = min(date_range.end, coverage_max)
        if effective_start > effective_end:
            return coverage_min, coverage_max
        return effective_start, effective_end

    def _handle_get_run(self, run_id: str) -> None:
        run_service = self.state.controller._runs  # type: ignore[attr-defined]
        # Locate the owning session by scanning.
        session_id = self.state.controller._runs._runs.session_for(run_id)  # type: ignore[attr-defined]
        run = run_service.get_run(run_id, session_id)
        records = run_service.list_tool_calls(run_id, session_id)
        self._write_json(
            HTTPStatus.OK,
            {
                "run": _serialize_run(run, tuple(records)),
                "tool_calls": [_serialize_tool_call(r) for r in records],
            },
        )

    def _handle_get_chart(self, run_id: str, chart_id: str) -> None:
        session_id = self.state.controller._runs._runs.session_for(run_id)  # type: ignore[attr-defined]
        png_path = self.state.controller.chart_store.get_png_path(chart_id, session_id, run_id)
        self._write_bytes(HTTPStatus.OK, Path(png_path).read_bytes(), "image/png")

    def _handle_get_chart_data(self, run_id: str, chart_id: str) -> None:
        session_id = self.state.controller._runs._runs.session_for(run_id)
        run = self.state.controller._runs.get_run(run_id, session_id)
        if chart_id not in run.chart_ids:
            raise NotFound("图表不属于当前分析。")
        store = self.state.controller.chart_store
        chart = store.get(chart_id, session_id, run_id)
        payload = json.loads(
            Path(store.get_data_path(chart_id, session_id, run_id)).read_text(encoding="utf-8")
        )
        # Older drawdown artifacts stored prices rather than the plotted values.
        if chart.kind.value == "drawdown" and payload.get("schema_version", 1) < 2:
            import pandas as pd

            from quantlab_agent.domain.metrics import drawdown_series

            for series in payload["series"]:
                series["y"] = (
                    drawdown_series(pd.Series(series["y"], dtype=float)).tolist()
                    if len(series["y"]) >= 2
                    else [None] * len(series["y"])
                )
            payload["schema_version"] = 2
        self._write_json(
            HTTPStatus.OK,
            {
                "chart_id": chart_id,
                "kind": chart.kind.value,
                "window": chart.window,
                "data": payload,
            },
        )

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
        path = Path(csv_path)
        if not path.exists():
            raise NotFound("dataset CSV not found")
        body = path.read_text(encoding="utf-8")
        self._write_bytes(HTTPStatus.OK, body.encode("utf-8"), "text/csv; charset=utf-8")

    def _handle_get_session_csv(self, session_id: str, dataset_id: str) -> None:
        csv_path = self.state.dataset_store.get_normalized_csv_path(dataset_id, session_id)
        path = Path(csv_path)
        if not path.exists():
            raise NotFound("dataset CSV not found")
        body = path.read_text(encoding="utf-8")
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
