"""CLI smoke tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from quantlab_agent.cli import main


def test_cli_demo_single_asset_outputs_report_path(tmp_path: Path, capsys) -> None:  # noqa: ANN001
    exit_code = main(["demo", "--scenario", "single-asset", "--runs-dir", str(tmp_path)])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload) == 1
    assert payload[0]["status"] == "succeeded"
    report_path = Path(payload[0]["report_path"])
    assert report_path.exists()
    assert report_path.name == "report.md"


def test_cli_chat_requires_env(tmp_path: Path, monkeypatch) -> None:
    """Without QUANTLAB_MODEL_* env vars the chat command must fail with
    exit 2 and print a clear error listing the missing variables.
    """
    for var in (
        "QUANTLAB_MODEL_BASE_URL",
        "QUANTLAB_MODEL_API_KEY",
        "QUANTLAB_MODEL_NAME",
    ):
        monkeypatch.delenv(var, raising=False)

    # Re-invoke the CLI subprocess so env does not leak from the test
    # runner's own environment.
    env = {k: v for k, v in os.environ.items() if not k.startswith("QUANTLAB_MODEL_")}
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "quantlab_agent.cli",
            "chat",
            "compare DEMO_A and DEMO_B",
            "--runs-dir",
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 2
    assert "QUANTLAB_MODEL_BASE_URL" in proc.stderr


def test_cli_help_lists_chat_subcommand() -> None:
    proc = subprocess.run(
        [sys.executable, "-m", "quantlab_agent.cli", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert "chat" in proc.stdout
