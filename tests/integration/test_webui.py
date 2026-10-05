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

    # Send a message — drives the demo pipeline.
    status, body, _ = _http_post_json(
        f"{server.url}/api/sessions/{SESSION}/messages",
        {"text": "Compare DEMO_A and DEMO_B in 2024-01"},
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
        {"text": "Describe DEMO_A"},
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
        {"text": "Describe DEMO_A"},
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
        {"text": "x"},
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
