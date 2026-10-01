"""CLI smoke tests."""

from __future__ import annotations

import json
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
