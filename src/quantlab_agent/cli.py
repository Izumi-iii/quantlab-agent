"""Command-line entry point for local demos and real-model chat."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from quantlab_agent.agent.controller import build_real_agent_stack
from quantlab_agent.agent.demo import DemoController, default_demo_controller
from quantlab_agent.config import ModelConfig, load_config
from quantlab_agent.domain.models import Run, RunMode


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


def _summarize(runs_dir: Path, run: Run) -> dict[str, object]:
    return {
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

    chat = subcommands.add_parser(
        "chat",
        help="run a real-model analysis (requires QUANTLAB_MODEL_* env vars)",
    )
    chat.add_argument(
        "request",
        help="natural-language request for the model (e.g. 'compare DEMO_A and DEMO_B in Jan 2024')",
    )
    chat.add_argument(
        "--runs-dir",
        default="runs",
        help="directory where run manifests, charts, and reports are written",
    )
    chat.add_argument(
        "--session-id",
        default=DemoController.DEFAULT_SESSION_ID,
        help="UUID-shaped session id for the chat run",
    )
    return parser


def _check_model_config(model: ModelConfig) -> None:
    missing = [
        name
        for name, value in (
            ("QUANTLAB_MODEL_BASE_URL", model.base_url),
            ("QUANTLAB_MODEL_API_KEY", model.api_key),
            ("QUANTLAB_MODEL_NAME", model.model),
        )
        if not value
    ]
    if missing:
        print(
            "error: the 'chat' command needs the following environment "
            f"variables set: {', '.join(missing)}",
            file=sys.stderr,
        )
        print(
            "  example (DeepSeek):\n"
            "    set QUANTLAB_MODEL_BASE_URL=https://api.deepseek.com/v1\n"
            "    set QUANTLAB_MODEL_API_KEY=sk-...\n"
            "    set QUANTLAB_MODEL_NAME=deepseek-chat",
            file=sys.stderr,
        )
        raise SystemExit(2)


def _build_real_agent(runs_dir: Path, model: ModelConfig):
    """Build the real-model stack via the shared helper and expose
    ``controller.run_service`` so the CLI can create the Run before
    driving the loop.
    """
    controller = build_real_agent_stack(runs_dir, model)
    return controller, controller.run_service


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "demo":
        runs_dir = Path(args.runs_dir).resolve()
        controller = default_demo_controller(runs_dir)
        runs = _run_scenario(controller, args.scenario, args.session_id)
        payload = [_summarize(runs_dir, run) for run in runs]
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    if args.command == "chat":
        config = load_config()
        _check_model_config(config.model)
        runs_dir = Path(args.runs_dir).resolve()
        controller, run_service = _build_real_agent(runs_dir, config.model)

        run = run_service.create_run(
            session_id=args.session_id,
            mode=RunMode.REAL_AGENT,
            user_request=args.request,
        )
        final = controller.execute(
            run_id=run.run_id,
            session_id=run.session_id,
            user_request=args.request,
        )
        payload = _summarize(runs_dir, final)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if final.status.value == "succeeded" else 1

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
