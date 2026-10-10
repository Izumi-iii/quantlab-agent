"""Integration tests for the stdlib HTTP web UI server.

The server is started in a background thread on an ephemeral port and
torn down at the end of the test. Each test gets a fresh runs directory.
"""

from __future__ import annotations

import json
import socket
import threading
import time
import urllib.request
from pathlib import Path

import pytest

from webui.server import build_state

SESSION = "00000000-0000-4000-8000-000000000099"


def _free_port() -> int:
    """Bind a socket, learn the port, release it. The race window is
    short enough that re-binding succeeds on every test runner we ship.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class _ServerThread:
    def __init__(self, runs_dir: Path):
        from webui.server import _Handler, _ThreadingServer

        self.state = build_state(runs_dir)
        port = _free_port()
        self.server = _ThreadingServer(("127.0.0.1", port), _Handler, self.state)
        self.port = port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.url = f"http://127.0.0.1:{port}"

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def __enter__(self) -> "_ServerThread":
        self.start()
        # Wait for server to actually be accepting.
        deadline = time.time() + 2.0
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", self.port), timeout=0.1):
                    return self
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("server did not start accepting within 2s")

    def __exit__(self, *exc_info: object) -> None:
        self.stop()


@pytest.fixture
def server(tmp_path: Path):
    s = _ServerThread(tmp_path)
    with s:
        yield s


# --- low-level helpers ----------------------------------------------------


def _http_get(url: str) -> tuple[int, bytes, dict[str, str]]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
        return exc.code, exc.read(), dict(exc.headers)


def _http_post_json(url: str, body: dict[str, object]) -> tuple[int, bytes, dict[str, str]]:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
        return exc.code, exc.read(), dict(exc.headers)


def _http_delete(url: str) -> tuple[int, bytes, dict[str, str]]:
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status, resp.read(), dict(resp.headers)
    except urllib.error.HTTPError as exc:  # type: ignore[attr-defined]
        return exc.code, exc.read(), dict(exc.headers)


def _build_multipart_csv(file_field: str, csv_bytes: bytes, fields: dict[str, str]) -> bytes:
    """Construct a minimal multipart/form-data body without external libs.

    Hand-rolled because the project's stdlib 3.14 drops ``cgi``. Layout
    matches RFC 7578: each part has headers, then a blank line, then the
    body; parts are separated by ``--<boundary>``.
    """
    boundary = "----qlTestBoundary1234567890"
    parts: list[bytes] = []
    # File part.
    file_header = (
        f'Content-Disposition: form-data; name="{file_field}"; filename="upload.csv"\r\n'
        f"Content-Type: text/csv\r\n\r\n"
    ).encode("ascii")
    parts.append(b"--" + boundary.encode("ascii") + b"\r\n" + file_header + csv_bytes + b"\r\n")
    # Text fields.
    for k, v in fields.items():
        text_header = (
            f'Content-Disposition: form-data; name="{k}"\r\n'
            f'Content-Type: text/plain; charset="utf-8"\r\n\r\n'
        ).encode("ascii")
        body_value = v.encode("utf-8")
        parts.append(
            b"--" + boundary.encode("ascii") + b"\r\n" + text_header + body_value + b"\r\n"
        )
    # Closing boundary.
    parts.append(b"--" + boundary.encode("ascii") + b"--\r\n")
    return b"".join(parts)


# --- tests ----------------------------------------------------------------


def test_healthz_returns_ok(server: _ServerThread) -> None:
    status, body, _ = _http_get(f"{server.url}/api/healthz")
    assert status == 200
    assert json.loads(body)["status"] == "ok"


def test_index_serves_demo_html(server: _ServerThread) -> None:
    status, body, headers = _http_get(f"{server.url}/")
    assert status == 200
    assert b"<title>QuantLab Agent" in body
    assert "text/html" in headers.get("Content-Type", "")


def test_static_asset_served(server: _ServerThread) -> None:
    # The static dir only ships index.html by default; hitting a
    # non-existent file must return 404 instead of crashing.
    status, _, _ = _http_get(f"{server.url}/static/missing.js")
    assert status == 404


def test_empty_session_returns_no_datasets(server: _ServerThread) -> None:
    status, body, _ = _http_get(f"{server.url}/api/sessions/{SESSION}/datasets")
    assert status == 200
    assert json.loads(body) == {"datasets": []}


def test_upload_then_list_dataset(server: _ServerThread) -> None:
    csv = b"date,close\n2024-01-02,100\n2024-01-03,101\n"
    body = _build_multipart_csv(
        "file", csv, {"asset_id": "DEMO_A", "price_basis": "forward_adjusted"}
    )
    req = urllib.request.Request(
        f"{server.url}/api/sessions/{SESSION}/datasets",
        data=body,
        method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=----qlTestBoundary1234567890"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        assert resp.status == 201
        payload = json.loads(resp.read())
    assert payload["dataset"]["asset_id"] == "DEMO_A"
    assert payload["dataset"]["row_count"] == 2

    status, body, _ = _http_get(f"{server.url}/api/sessions/{SESSION}/datasets")
    items = json.loads(body)["datasets"]
    assert len(items) == 1
    assert items[0]["asset_id"] == "DEMO_A"

    dataset_id = items[0]["dataset_id"]
    status, csv_body, headers = _http_get(
        f"{server.url}/api/sessions/{SESSION}/datasets/{dataset_id}.csv"
    )
    assert status == 200
    assert "text/csv" in headers.get("Content-Type", "")
    assert b"date,close" in csv_body


def test_delete_dataset_removes_it_from_session(server: _ServerThread) -> None:
    csv = b"date,close\n2024-01-02,100\n2024-01-03,101\n"
    body = _build_multipart_csv(
        "file", csv, {"asset_id": "DEMO_DELETE", "price_basis": "forward_adjusted"}
    )
    req = urllib.request.Request(
        f"{server.url}/api/sessions/{SESSION}/datasets",
        data=body,
        method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=----qlTestBoundary1234567890"},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        dataset_id = json.loads(resp.read())["dataset"]["dataset_id"]

    status, body, _ = _http_delete(f"{server.url}/api/sessions/{SESSION}/datasets/{dataset_id}")
    assert status == 200
    assert json.loads(body)["deleted"] is True

    status, body, _ = _http_get(f"{server.url}/api/sessions/{SESSION}/datasets")
    assert status == 200
    assert json.loads(body)["datasets"] == []

    status, _, _ = _http_get(f"{server.url}/api/sessions/{SESSION}/datasets/{dataset_id}.csv")
    assert status == 404


def test_message_drive_creates_run_with_charts_and_report(server: _ServerThread) -> None:
    # Seed two datasets.
    for asset_id in ("DEMO_A", "DEMO_B"):
        csv = b"date,close\n2024-01-02,100\n2024-01-03,101\n2024-01-04,99\n2024-01-05,103\n"
        body = _build_multipart_csv(
            "file", csv, {"asset_id": asset_id, "price_basis": "forward_adjusted"}
        )
        req = urllib.request.Request(
            f"{server.url}/api/sessions/{SESSION}/datasets",
            data=body,
            method="POST",
            headers={"Content-Type": "multipart/form-data; boundary=----qlTestBoundary1234567890"},
        )
        urllib.request.urlopen(req, timeout=5).read()

    # Send a message — drives the report pipeline (planner maps "生成报告"
    # to intent=report).
    status, body, _ = _http_post_json(
        f"{server.url}/api/sessions/{SESSION}/messages",
        {
            "text": "生成报告 DEMO_A 和 DEMO_B 2024-01-02 2024-01-15",
            "start": "2024-01-02",
            "end": "2024-01-15",
        },
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["run"]["status"] == "succeeded"
    assert payload["run"]["report_id"]
    assert len(payload["run"]["chart_ids"]) >= 1
    # Tool calls should include the full pipeline.
    tool_names = [tc["tool_name"] for tc in payload["tool_calls"]]
    assert "inspect_dataset" in tool_names
    assert "prepare_analysis" in tool_names
    assert "build_report" in tool_names


def test_message_trend_chart_creates_chart_only_run(server: _ServerThread) -> None:
    csv = b"date,close\n2024-01-02,100\n2024-01-03,101\n2024-01-04,99\n2024-01-05,103\n"
    body = _build_multipart_csv(
        "file", csv, {"asset_id": "DEMO_CHART", "price_basis": "forward_adjusted"}
    )
    req = urllib.request.Request(
        f"{server.url}/api/sessions/{SESSION}/datasets",
        data=body,
        method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=----qlTestBoundary1234567890"},
    )
    urllib.request.urlopen(req, timeout=5).read()

    status, body, _ = _http_post_json(
        f"{server.url}/api/sessions/{SESSION}/messages",
        {
            "text": "生成 DEMO_CHART 趋势图表",
            "start": "2024-01-02",
            "end": "2024-01-15",
        },
    )
    assert status == 200
    payload = json.loads(body)
    run = payload["run"]
    assert run["intent"] == "chart"
    assert run["status"] == "succeeded"
    assert run["chart_ids"]
    assert run["report_id"] is None
    assert "图表已生成" in run["summary"]
    tool_names = [tc["tool_name"] for tc in payload["tool_calls"]]
    assert tool_names == [
        "inspect_dataset",
        "prepare_analysis",
        "compute_metrics",
        "create_charts",
    ]


def test_chart_png_served(server: _ServerThread) -> None:
    # Seed + drive.
    csv = b"date,close\n2024-01-02,100\n2024-01-03,101\n2024-01-04,99\n"
    body = _build_multipart_csv(
        "file", csv, {"asset_id": "DEMO_A", "price_basis": "forward_adjusted"}
    )
    req = urllib.request.Request(
        f"{server.url}/api/sessions/{SESSION}/datasets",
        data=body,
        method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=----qlTestBoundary1234567890"},
    )
    urllib.request.urlopen(req, timeout=5).read()
    _, resp_body, _ = _http_post_json(
        f"{server.url}/api/sessions/{SESSION}/messages",
        {
            "text": "生成报告 DEMO_A 2024-01-02 2024-01-15",
            "start": "2024-01-02",
            "end": "2024-01-15",
        },
    )
    run = json.loads(resp_body)["run"]
    chart_id = run["chart_ids"][0]
    status, png_bytes, headers = _http_get(
        f"{server.url}/api/runs/{run['run_id']}/chart/{chart_id}.png"
    )
    assert status == 200
    assert headers.get("Content-Type") == "image/png"
    # PNG signature.
    assert png_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png_bytes) > 200


def test_report_markdown_served(server: _ServerThread) -> None:
    csv = b"date,close\n2024-01-02,100\n2024-01-03,101\n2024-01-04,99\n"
    body = _build_multipart_csv(
        "file", csv, {"asset_id": "DEMO_A", "price_basis": "forward_adjusted"}
    )
    req = urllib.request.Request(
        f"{server.url}/api/sessions/{SESSION}/datasets",
        data=body,
        method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=----qlTestBoundary1234567890"},
    )
    urllib.request.urlopen(req, timeout=5).read()
    _, resp_body, _ = _http_post_json(
        f"{server.url}/api/sessions/{SESSION}/messages",
        {
            "text": "生成报告 DEMO_A 2024-01-02 2024-01-15",
            "start": "2024-01-02",
            "end": "2024-01-15",
        },
    )
    run = json.loads(resp_body)["run"]
    status, md, headers = _http_get(
        f"{server.url}/api/runs/{run['run_id']}/report/{run['report_id']}.md"
    )
    assert status == 200
    assert "text/markdown" in headers.get("Content-Type", "")
    assert b"# QuantLab" in md


def test_message_without_datasets_returns_400(server: _ServerThread) -> None:
    status, body, _ = _http_post_json(
        f"{server.url}/api/sessions/{SESSION}/messages",
        {"text": "do something"},
    )
    assert status == 400
    assert "no datasets" in body.decode("utf-8").lower()


def test_message_with_empty_text_returns_400(server: _ServerThread) -> None:
    status, _, _ = _http_post_json(
        f"{server.url}/api/sessions/{SESSION}/messages",
        {"text": ""},
    )
    assert status == 400


def test_get_run_returns_state_and_tool_calls(server: _ServerThread) -> None:
    csv = b"date,close\n2024-01-02,100\n2024-01-03,101\n"
    body = _build_multipart_csv(
        "file", csv, {"asset_id": "DEMO_A", "price_basis": "forward_adjusted"}
    )
    req = urllib.request.Request(
        f"{server.url}/api/sessions/{SESSION}/datasets",
        data=body,
        method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=----qlTestBoundary1234567890"},
    )
    urllib.request.urlopen(req, timeout=5).read()
    _, resp_body, _ = _http_post_json(
        f"{server.url}/api/sessions/{SESSION}/messages",
        {"text": "数据质量怎么样"},
    )
    run_id = json.loads(resp_body)["run"]["run_id"]

    status, body, _ = _http_get(f"{server.url}/api/runs/{run_id}")
    assert status == 200
    payload = json.loads(body)
    assert payload["run"]["run_id"] == run_id
    assert isinstance(payload["tool_calls"], list)
    assert len(payload["tool_calls"]) > 0


def test_unknown_route_returns_404(server: _ServerThread) -> None:
    status, _, _ = _http_get(f"{server.url}/api/nope")
    assert status == 404


def test_config_endpoint_reports_env(server: _ServerThread, monkeypatch) -> None:
    monkeypatch.setenv("QUANTLAB_MODEL_BASE_URL", "https://example.com/v1")
    monkeypatch.setenv("QUANTLAB_MODEL_API_KEY", "x")
    monkeypatch.setenv("QUANTLAB_MODEL_NAME", "fake-model")
    status, body, _ = _http_get(f"{server.url}/api/config")
    assert status == 200
    payload = json.loads(body)
    assert payload["env_configured"] is True
    assert payload["env_model"] == "fake-model"


def test_path_traversal_in_static_rejected(server: _ServerThread) -> None:
    status, _, _ = _http_get(f"{server.url}/static/..%2F..%2Fetc%2Fpasswd")
    # Either 404 (decoded traversal rejected) or 400; never 200 with file body.
    assert status in (400, 404)


# --- Planner-driven paths -------------------------------------------------


def _seed_one(server: _ServerThread, asset_id: str = "DEMO_A") -> None:
    csv = b"date,close\n2024-01-02,100\n2024-01-03,101\n2024-01-04,99\n"
    body = _build_multipart_csv(
        "file", csv, {"asset_id": asset_id, "price_basis": "forward_adjusted"}
    )
    req = urllib.request.Request(
        f"{server.url}/api/sessions/{SESSION}/datasets",
        data=body,
        method="POST",
        headers={"Content-Type": "multipart/form-data; boundary=----qlTestBoundary1234567890"},
    )
    urllib.request.urlopen(req, timeout=5).read()


def test_planner_data_quality_runs_only_inspect(server: _ServerThread) -> None:
    _seed_one(server)
    status, body, _ = _http_post_json(
        f"{server.url}/api/sessions/{SESSION}/messages",
        {"text": "数据质量怎么样"},
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["run"]["intent"] == "data_quality"
    assert payload["run"]["status"] == "succeeded"
    assert "数据质量检查完成" in payload["run"]["summary"]
    assert "DEMO_A" in payload["run"]["summary"]
    assert "未发现质量问题" in payload["run"]["summary"]
    tool_names = [tc["tool_name"] for tc in payload["tool_calls"]]
    assert tool_names == ["inspect_dataset"]


def test_planner_metrics_intent_runs_three_tools(server: _ServerThread) -> None:
    _seed_one(server)
    status, body, _ = _http_post_json(
        f"{server.url}/api/sessions/{SESSION}/messages",
        {
            "text": "DEMO_A 区间收益和最大回撤 2024-01-02 2024-01-15",
            "start": "2024-01-02",
            "end": "2024-01-15",
        },
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["run"]["intent"] == "metrics"
    assert payload["run"]["status"] == "succeeded"
    assert "指标计算完成" in payload["run"]["summary"]
    assert "DEMO_A" in payload["run"]["summary"]
    assert "区间收益" in payload["run"]["summary"]
    assert "最大回撤" in payload["run"]["summary"]
    tool_names = [tc["tool_name"] for tc in payload["tool_calls"]]
    assert tool_names == ["inspect_dataset", "prepare_analysis", "compute_metrics"]


def test_planner_out_of_scope_marks_failed(server: _ServerThread) -> None:
    _seed_one(server)
    status, body, _ = _http_post_json(
        f"{server.url}/api/sessions/{SESSION}/messages",
        {"text": "推荐股票"},
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["run"]["status"] == "failed"
    assert payload["run"]["failure"]["code"] == "OUT_OF_SCOPE"
    assert payload["run"]["intent"] == "out_of_scope"


def test_planner_response_carries_summary_and_intent(server: _ServerThread) -> None:
    _seed_one(server)
    status, body, _ = _http_post_json(
        f"{server.url}/api/sessions/{SESSION}/messages",
        {"text": "数据质量怎么样"},
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["run"]["intent"] == "data_quality"
    assert payload["run"]["summary"]  # non-empty string
    assert payload["run"]["plan_summary"]  # non-empty string


def test_planner_profile_intent_runs_inspect_and_profile(server: _ServerThread) -> None:
    _seed_one(server)
    status, body, _ = _http_post_json(
        f"{server.url}/api/sessions/{SESSION}/messages",
        {"text": "看看 DEMO_A 的概况"},
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["run"]["intent"] == "profile"
    tool_names = [tc["tool_name"] for tc in payload["tool_calls"]]
    assert tool_names == ["inspect_dataset", "profile_dataset"]
    assert payload["run"]["status"] == "succeeded"
    assert "DEMO_A" in payload["run"]["summary"]


def test_planner_describe_intent_runs_describe_after_metrics(
    server: _ServerThread,
) -> None:
    _seed_one(server)
    status, body, _ = _http_post_json(
        f"{server.url}/api/sessions/{SESSION}/messages",
        {
            "text": "DEMO_A 走势怎么样",
            "start": "2024-01-02",
            "end": "2024-01-15",
        },
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["run"]["intent"] == "metrics"
    tool_names = [tc["tool_name"] for tc in payload["tool_calls"]]
    assert tool_names == [
        "inspect_dataset",
        "prepare_analysis",
        "compute_metrics",
        "describe_price_series",
    ]
    assert payload["run"]["extras"] == ["describe_price_series"]
    assert "DEMO_A" in payload["run"]["summary"]


def test_planner_chart_intent_runs_create_charts_only(server: _ServerThread) -> None:
    _seed_one(server)
    status, body, _ = _http_post_json(
        f"{server.url}/api/sessions/{SESSION}/messages",
        {
            "text": "画一下 DEMO_A 的走势图",
            "start": "2024-01-02",
            "end": "2024-01-15",
        },
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["run"]["intent"] == "chart"
    tool_names = [tc["tool_name"] for tc in payload["tool_calls"]]
    assert tool_names == [
        "inspect_dataset",
        "prepare_analysis",
        "compute_metrics",
        "create_charts",
    ]
    assert payload["run"]["report_id"] is None
    assert len(payload["run"]["chart_ids"]) >= 1


def test_planner_anomaly_extra_runs_detect_anomalies(server: _ServerThread) -> None:
    _seed_one(server)
    status, body, _ = _http_post_json(
        f"{server.url}/api/sessions/{SESSION}/messages",
        {"text": "DEMO_A 有没有异常"},
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["run"]["intent"] == "data_quality"
    assert payload["run"]["extras"] == ["anomalies"]
    tool_names = [tc["tool_name"] for tc in payload["tool_calls"]]
    assert "detect_anomalies" in tool_names


def test_planner_risk_extra_runs_compute_risk_metrics(server: _ServerThread) -> None:
    _seed_one(server)
    status, body, _ = _http_post_json(
        f"{server.url}/api/sessions/{SESSION}/messages",
        {
            "text": "DEMO_A 风险怎么样 2024-01-02 2024-01-15",
            "start": "2024-01-02",
            "end": "2024-01-15",
        },
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["run"]["intent"] == "metrics"
    assert payload["run"]["extras"] == ["risk"]
    tool_names = [tc["tool_name"] for tc in payload["tool_calls"]]
    assert "compute_risk_metrics" in tool_names


def test_planner_rolling_extra_runs_compute_rolling_metrics(
    server: _ServerThread,
) -> None:
    _seed_one(server)
    status, body, _ = _http_post_json(
        f"{server.url}/api/sessions/{SESSION}/messages",
        {
            "text": "60 日波动率图 2024-01-02 2024-01-15",
            "start": "2024-01-02",
            "end": "2024-01-15",
        },
    )
    assert status == 200
    payload = json.loads(body)
    assert payload["run"]["intent"] == "chart"
    assert payload["run"]["status"] == "succeeded"
    assert payload["run"]["extras"] == ["rolling"]
    tool_names = [tc["tool_name"] for tc in payload["tool_calls"]]
    assert "compute_rolling_metrics" in tool_names
    assert "create_charts" in tool_names
    assert all(tc["status"] == "succeeded" for tc in payload["tool_calls"])
