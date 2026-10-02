"""Streamlit UI for the deterministic demo.

Execution model reminder: every user interaction reruns this script
from the top. Anything that must persist across reruns lives in
``st.session_state``. The composition root (``default_demo_controller``)
is built once via ``@st.cache_resource`` so we don't rebuild the store
graph on every click.
"""

from __future__ import annotations

from datetime import date as _date
from pathlib import Path
from uuid import uuid4

import pandas as pd
import streamlit as st

from quantlab_agent.agent.demo import DemoController, default_demo_controller
from quantlab_agent.domain.models import (
    DatasetMetadata,
    MetricName,
    PriceBasis,
    Run,
    RunMode,
    RunStatus,
)

RUNS_DIR = Path("runs")


@st.cache_resource(show_spinner=False)
def _build_controller(runs_dir: str) -> DemoController:
    """Build the demo controller exactly once per Streamlit session."""
    return default_demo_controller(Path(runs_dir))


def _ensure_session_state() -> str:
    """Return the per-browser session id, initializing on first rerun."""
    if "session_uuid" not in st.session_state:
        st.session_state.session_uuid = str(uuid4())
    return st.session_state.session_uuid


def _render_sidebar(session_id: str) -> None:
    with st.sidebar:
        st.markdown("### Session")
        st.code(session_id, language="text")
        if st.session_state.get("active_run_id"):
            st.markdown("### Active run")
            st.code(st.session_state.active_run_id, language="text")
        st.divider()
        if st.button("Reset UI", help="Clear current view. Background runs keep their state."):
            for key in ("active_run_id", "last_run"):
                st.session_state.pop(key, None)
            st.rerun()


def _render_data_form() -> tuple[list, list, _date, _date, list[MetricName]]:
    """Render the left pane and return validated user inputs."""
    st.subheader("Data")
    asset_count = st.radio(
        "Number of assets",
        options=[1, 2],
        horizontal=True,
        key="asset_count",
    )

    files: list = []
    metas: list = []
    for i in range(asset_count):
        with st.container(border=True):
            st.markdown(f"**Asset {i + 1}**")
            uploaded = st.file_uploader(
                "CSV with columns: `date`,`close`",
                type=["csv"],
                key=f"upload_{i}",
            )
            asset_id = st.text_input(
                "asset_id",
                value=f"ASSET_{i + 1}",
                key=f"asset_id_{i}",
                help="Stable identifier used in reports and tool calls.",
            )
            price_basis = st.selectbox(
                "price_basis",
                options=[b.value for b in PriceBasis],
                index=[b.value for b in PriceBasis].index("forward_adjusted"),
                key=f"basis_{i}",
            )
            files.append(uploaded)
            metas.append(
                DatasetMetadata(
                    asset_id=asset_id.strip() or f"ASSET_{i + 1}",
                    source_name="user upload",
                    price_basis=PriceBasis(price_basis),
                    currency="CNY",
                    frequency="daily",
                    calendar_label="user provided",
                    daily_series_complete=True,
                    is_synthetic=False,
                )
            )

    st.subheader("Request")
    col1, col2 = st.columns(2)
    start = col1.date_input("Start date", value=_date(2024, 1, 2), key="start")
    end = col2.date_input("End date", value=_date(2024, 1, 15), key="end")
    if start > end:
        st.error("Start date must be on or before end date.")
        st.stop()

    metrics = st.multiselect(
        "Metrics to compute",
        options=list(MetricName),
        default=[MetricName.PERIOD_RETURN, MetricName.MAX_DRAWDOWN],
        format_func=lambda m: m.value,
        key="metrics",
    )
    if not metrics:
        st.error("Select at least one metric.")
        st.stop()

    return files, metas, start, end, metrics


def _import_user_datasets(
    controller: DemoController,
    session_id: str,
    metas: list[DatasetMetadata],
    files: list,
) -> tuple[list[str] | None, str | None]:
    """Import each uploaded CSV. Returns ``(dataset_ids, error_message)``.

    On any quality error we return ``(None, message)`` instead of calling
    ``st.stop()``: ``st.stop()`` halts execution before the ``finally``
    block in the submit handler runs, which would leave
    ``st.session_state.running`` set to True and lock the submit button
    until the page is refreshed.
    """
    dataset_ids: list[str] = []
    for meta, uploaded in zip(metas, files):
        if uploaded is None:
            return None, f"Missing CSV upload for asset `{meta.asset_id}`."
        bytes_data = uploaded.getvalue()
        result = controller._datasets.import_csv(bytes_data, metadata=meta, session_id=session_id)
        if result.dataset is None:
            issues = [
                f"- **{issue.code}**: {issue.message}" for issue in result.quality_report.issues
            ]
            return None, (
                f"Dataset `{meta.asset_id}` was rejected by the quality gate:\n"
                + "\n".join(issues)
            )
        controller._dataset_store.save(result.dataset, session_id)
        dataset_ids.append(result.dataset.manifest.dataset_id)
    return dataset_ids, None


def _run_user_analysis(
    controller: DemoController,
    session_id: str,
    metas: list[DatasetMetadata],
    files: list,
    start: _date,
    end: _date,
    metrics: list[MetricName],
) -> Run | None:
    """Drive the same tool pipeline as the CLI demo, with user-supplied inputs.

    Returns ``None`` if any dataset was rejected; the caller displays the
    error message and skips the rest of the run.
    """
    dataset_ids, error = _import_user_datasets(controller, session_id, metas, files)
    if error is not None:
        st.error(error)
        return None

    run = controller._runs.create_run(
        session_id=session_id,
        mode=RunMode.DEMO,
        user_request=(
            f"User analysis of {[m.asset_id for m in metas]} "
            f"from {start.isoformat()} to {end.isoformat()}"
        ),
    )
    for ds_id in dataset_ids:
        controller._runs.add_dataset(run.run_id, session_id, ds_id)

    controller._execute_pipeline(
        run_id=run.run_id,
        session_id=session_id,
        dataset_ids=dataset_ids,
        requested_start=start.isoformat(),
        requested_end=end.isoformat(),
        requested_metrics=tuple(m.value for m in metrics),
    )
    return controller._runs.get_run(run.run_id, session_id)


def _recompute_metric_rows(controller: DemoController, run: Run) -> pd.DataFrame:
    """Re-derive MetricResult for display — the pipeline is deterministic so
    re-running it on the same inputs yields the same numbers.
    """
    from datetime import date as _d

    from quantlab_agent.application.analyses import AnalysisService

    datasets = [controller._dataset_store.get(ds_id, run.session_id) for ds_id in run.dataset_ids]
    metrics = tuple(MetricName(m) for m in run.context_snapshot["requested_metrics"])
    prepared = AnalysisService().prepare(
        datasets,
        session_id=run.session_id,
        requested_start=_d.fromisoformat(run.context_snapshot["requested_start"]),
        requested_end=_d.fromisoformat(run.context_snapshot["requested_end"]),
        requested_metrics=metrics,
        analysis_id=run.analysis_id,
    )
    result = AnalysisService().compute_metrics(prepared)

    rows = []
    for asset in result.assets:
        for metric_name, metric in asset.metrics.items():
            value = "n/a" if metric.value is None else f"{metric.value * 100:.2f}%"
            note = (
                metric.unavailable_reason
                if metric.value is None
                else "; ".join(metric.assumptions) or "—"
            )
            rows.append(
                {
                    "asset": asset.asset_id,
                    "metric": metric_name.value,
                    "value": value,
                    "observations": metric.observations,
                    "notes": note,
                }
            )
    return pd.DataFrame(rows)


def _render_results(controller: DemoController, run: Run) -> None:
    st.subheader(f"Run `{run.run_id[:8]}…`")
    if run.status == RunStatus.SUCCEEDED:
        st.success(f"Status: **{run.status.value}**")
    elif run.status == RunStatus.FAILED:
        st.error(f"Status: **{run.status.value}**")
        if run.failure:
            with st.expander("Failure details"):
                st.json(run.failure)
        return
    else:
        st.info(f"Status: **{run.status.value}**")
        return

    if run.metrics_id:
        st.markdown("### Metrics")
        df = _recompute_metric_rows(controller, run)
        st.dataframe(df, use_container_width=True, hide_index=True)

    if run.chart_ids:
        st.markdown("### Charts")
        chart_store = controller._chart_store
        for chart_id in run.chart_ids:
            chart = chart_store.get(chart_id, run.session_id, run.run_id)
            png_path = chart_store.get_png_path(chart_id, run.session_id, run.run_id)
            st.image(str(png_path), caption=chart.title)

    if run.report_id:
        st.markdown("### Report")
        md_path = controller._report_store.get_markdown_path(
            run.report_id, run.session_id, run.run_id
        )
        markdown = Path(md_path).read_text(encoding="utf-8")
        st.download_button(
            "Download report.md",
            data=markdown,
            file_name="report.md",
            mime="text/markdown",
        )
        with st.expander("View report"):
            st.markdown(markdown)


def _render_process(controller: DemoController, run: Run) -> None:
    st.subheader("Tool calls")
    records = controller._runs.list_tool_calls(run.run_id, run.session_id)
    if not records:
        st.info("No tool calls recorded.")
        return
    for record in records:
        label = f"`{record.tool_name}` → {record.status.value}"
        if record.error_code:
            label += f" — {record.error_code}"
        with st.expander(label):
            st.json(
                {
                    "tool_call_id": record.tool_call_id,
                    "started_at": record.started_at.isoformat(),
                    "completed_at": (
                        record.completed_at.isoformat() if record.completed_at else None
                    ),
                    "arguments": record.arguments_redacted,
                }
            )


def main() -> None:
    st.set_page_config(
        page_title="QuantLab Agent",
        page_icon="📊",
        layout="wide",
    )
    st.title("QuantLab Agent — Demo Mode")
    st.caption(
        "No model API required. The same Tool Registry and run state machine "
        "as the CLI demo, with user-supplied CSV inputs."
    )

    session_id = _ensure_session_state()
    controller = _build_controller(str(RUNS_DIR))
    _render_sidebar(session_id)

    tab_data, tab_results, tab_process = st.tabs(["Data & Request", "Results", "Process"])

    with tab_data:
        files, metas, start, end, metrics = _render_data_form()
        submitted = st.button(
            "Run Analysis",
            type="primary",
            disabled=st.session_state.get("running", False),
            use_container_width=True,
        )
        if submitted and not st.session_state.get("running", False):
            st.session_state.running = True
            try:
                run = _run_user_analysis(controller, session_id, metas, files, start, end, metrics)
                if run is not None:
                    st.session_state.last_run = run
                    st.session_state.active_run_id = run.run_id
            finally:
                st.session_state.running = False
            st.rerun()

    last_run: Run | None = st.session_state.get("last_run")
    with tab_results:
        if last_run is None:
            st.info("Submit a request on the left to see results here.")
        else:
            _render_results(controller, last_run)

    with tab_process:
        if last_run is None:
            st.info("No tool calls yet.")
        else:
            _render_process(controller, last_run)


if __name__ == "__main__":
    main()
