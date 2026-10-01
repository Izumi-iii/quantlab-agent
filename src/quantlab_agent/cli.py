"""Command-line entry point for local demos."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from quantlab_agent.agent.demo import DemoController, default_demo_controller
from quantlab_agent.domain.models import Run


def _report_path(runs_dir: Path, run: Run) -> str | None:
    if run.report_id is None:
        return None
    return str(
        (
            runs_dir
            / run.session_id
            / "runs"
            / run.run_id
            / "reports"
            / run.report_id
            / "report.md"
        ).resolve(strict=False)
    )


def _run_scenario(controller: DemoController, scenario: str, session_id: str) -> tuple[Run, ...]:
    if scenario == "two-asset":
        return (controller.run_two_asset(session_id=session_id),)
    if scenario == "single-asset":
        return (controller.run_single_asset(session_id=session_id),)
    if scenario == "duplicate-date":
        return (controller.run_duplicate_date_failure(session_id=session_id),)
    return controller.run_all(session_id=session_id)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="quantlab-agent")
    subcommands = parser.add_subparsers(dest="command", required=True)

    demo = subcommands.add_parser("demo", help="run deterministic local demo scenarios")
    demo.add_argument(
        "--scenario",
        choices=("all", "two-asset", "single-asset", "duplicate-date"),
        default="all",
        help="which demo scenario to run",
    )
    demo.add_argument(
        "--runs-dir",
        default="runs",
        help="directory where run manifests, charts, and reports are written",
    )
    demo.add_argument(
        "--session-id",
        default=DemoController.DEFAULT_SESSION_ID,
        help="UUID-shaped session id for the demo run",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "demo":
        runs_dir = Path(args.runs_dir).resolve()
        controller = default_demo_controller(runs_dir)
        runs = _run_scenario(controller, args.scenario, args.session_id)
        payload = [
            {
                "run_id": run.run_id,
                "session_id": run.session_id,
                "status": run.status.value,
                "analysis_id": run.analysis_id,
                "metrics_id": run.metrics_id,
                "chart_ids": list(run.chart_ids),
                "report_id": run.report_id,
                "report_path": _report_path(runs_dir, run),
                "failure": run.failure,
            }
            for run in runs
        ]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
