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

from quantlab_agent.agent.controller import SUPPORTED_REQUEST_HINT, is_supported_analysis_request
from quantlab_agent.agent.demo import DemoController, default_demo_controller
from quantlab_agent.config import ModelConfig, load_config
from quantlab_agent.domain.models import (
    DatasetMetadata,
    MetricName,
    PriceBasis,
    Run,
    RunMode,
    RunStatus,
)

RUNS_DIR = Path("runs")

MODEL_PROVIDER_PRESETS = {
    "DeepSeek": {
        "base_url": "https://api.deepseek.com/v1",
        "models": ("deepseek-chat", "deepseek-reasoner"),
    },
    "OpenAI": {
        "base_url": "https://api.openai.com/v1",
        "models": ("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1"),
    },
    "Moonshot / Kimi": {
        "base_url": "https://api.moonshot.cn/v1",
        "models": ("moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k"),
    },
    "Zhipu / GLM": {
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": ("glm-4-flash", "glm-4-plus", "glm-4-air"),
    },
    "Alibaba / Qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": ("qwen-plus", "qwen-turbo", "qwen-max", "qwen-long"),
    },
}


@st.cache_resource(show_spinner=False)
def _build_controller(runs_dir: str) -> DemoController:
    """Build the demo controller exactly once per Streamlit session."""
    return default_demo_controller(Path(runs_dir))


def _ensure_session_state() -> str:
    """Return the per-browser session id, initializing on first rerun."""
    if "session_uuid" not in st.session_state:
        st.session_state.session_uuid = str(uuid4())
    return st.session_state.session_uuid


def _effective_model_config() -> ModelConfig | None:
    """Resolve the active ``ModelConfig``: UI override (if all three fields
    are filled) takes precedence over env vars.

    The session-scoped UI values are stored as plain strings in
    ``st.session_state``; the API key is kept in the per-browser session
    only and never written to disk.
    """
    env_config = load_config().model
    ui_base = (st.session_state.get("ui_model_base_url") or "").strip()
    ui_key = (st.session_state.get("ui_model_api_key") or "").strip()
    ui_model = (st.session_state.get("ui_model_name") or "").strip()
    if ui_base and ui_key and ui_model:
        return ModelConfig(
            base_url=ui_base,
            api_key=ui_key,
            model=ui_model,
            timeout_seconds=env_config.timeout_seconds,
            temperature=env_config.temperature,
            max_tokens=env_config.max_tokens,
        )
    if env_config.configured:
        return env_config
    return None


def _reset_ui() -> None:
    for key in ("active_run_id", "last_run"):
        st.session_state.pop(key, None)


def _render_page_header() -> None:
    title_col, action_col = st.columns([0.86, 0.14], vertical_alignment="center")
    title_col.title("QuantLab Agent")
    if action_col.button("Reset UI", help="Clear current view. Background runs keep their state."):
        _reset_ui()
        st.rerun()
    st.caption(
        "Local demo analysis and real model tool-calling share the same "
        "Tool Registry and run state machine."
    )


def _render_data_form() -> tuple[list, list, _date, _date, list[MetricName]]:
    """Render the left pane and return validated user inputs."""
    st.subheader("Data")
    files, metas = _render_dataset_inputs(key_prefix="demo", default_asset_prefix="ASSET")

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


def _render_dataset_inputs(
    *,
    key_prefix: str,
    default_asset_prefix: str,
) -> tuple[list, list[DatasetMetadata]]:
    """Render reusable dataset upload controls."""
    asset_count = st.radio(
        "Number of assets",
        options=[1, 2],
        horizontal=True,
        key=f"{key_prefix}_asset_count",
    )

    files: list = []
    metas: list[DatasetMetadata] = []
    for i in range(asset_count):
        with st.container(border=True):
            st.markdown(f"**Asset {i + 1}**")
            uploaded = st.file_uploader(
                "CSV with columns: `date`,`close`",
                type=["csv"],
                key=f"{key_prefix}_upload_{i}",
            )
            asset_id = st.text_input(
                "asset_id",
                value=f"{default_asset_prefix}_{i + 1}",
                key=f"{key_prefix}_asset_id_{i}",
                help="Stable identifier used in reports and tool calls.",
            )
            price_basis = st.selectbox(
                "price_basis",
                options=[b.value for b in PriceBasis],
                index=[b.value for b in PriceBasis].index("forward_adjusted"),
                key=f"{key_prefix}_basis_{i}",
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
    return files, metas


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
                f"Dataset `{meta.asset_id}` was rejected by the quality gate:\n" + "\n".join(issues)
            )
        controller.dataset_store.save(result.dataset, session_id)
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

    datasets = [controller.dataset_store.get(ds_id, run.session_id) for ds_id in run.dataset_ids]
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
    elif run.status == RunStatus.NEEDS_CLARIFICATION:
        st.warning("Status: **needs clarification**")
        if run.failure:
            text = str(run.failure.get("details", {}).get("model_text") or "")
            if text:
                st.markdown("### Agent question")
                st.markdown(text)
            with st.expander("Raw clarification details"):
                st.json(run.failure)
        return
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
        chart_store = controller.chart_store
        for chart_id in run.chart_ids:
            chart = chart_store.get(chart_id, run.session_id, run.run_id)
            png_path = chart_store.get_png_path(chart_id, run.session_id, run.run_id)
            st.image(str(png_path), caption=chart.title)

    if run.report_id:
        st.markdown("### Report")
        md_path = controller.report_store.get_markdown_path(
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


def _list_session_datasets(controller: DemoController, session_id: str) -> list[dict[str, object]]:
    """Return current-session dataset summaries when the local store supports it."""
    list_in_session = getattr(controller.dataset_store, "list_in_session", None)
    if list_in_session is None:
        return []
    return list(list_in_session(session_id))


def _render_real_dataset_import(controller: DemoController, session_id: str) -> None:
    st.markdown("### Data")
    files, metas = _render_dataset_inputs(key_prefix="real", default_asset_prefix="DEMO")
    imported = st.button(
        "Import datasets",
        disabled=st.session_state.get("importing_real_data", False),
        use_container_width=True,
    )
    if imported and not st.session_state.get("importing_real_data", False):
        st.session_state.importing_real_data = True
        try:
            dataset_ids, error = _import_user_datasets(controller, session_id, metas, files)
            if error is not None:
                st.error(error)
            else:
                st.session_state.real_dataset_ids = dataset_ids
                st.success(f"Imported {len(dataset_ids)} dataset(s).")
        finally:
            st.session_state.importing_real_data = False

    datasets = _list_session_datasets(controller, session_id)
    if datasets:
        st.dataframe(pd.DataFrame(datasets), use_container_width=True, hide_index=True)


def _clarification_text(run: Run | None) -> str | None:
    if run is None or run.status is not RunStatus.NEEDS_CLARIFICATION or not run.failure:
        return None
    text = run.failure.get("details", {}).get("model_text")
    return str(text) if text else None


def _provider_options() -> dict[str, dict[str, object]]:
    custom = st.session_state.get("custom_model_providers") or {}
    return {**MODEL_PROVIDER_PRESETS, **custom}


def _render_add_provider_form() -> None:
    with st.container(border=True):
        st.markdown("### Add provider")
        name = st.text_input("Provider name", key="new_provider_name")
        base_url = st.text_input(
            "OpenAI-compatible base_url",
            key="new_provider_base_url",
            placeholder="https://api.example.com/v1",
        )
        models_text = st.text_area(
            "Model names",
            key="new_provider_models",
            placeholder="model-a\nmodel-b",
            height=100,
        )
        col_save, col_cancel = st.columns([1, 1])
        if col_save.button("Save provider", type="primary"):
            model_names = tuple(
                item.strip()
                for line in models_text.splitlines()
                for item in line.split(",")
                if item.strip()
            )
            if not name.strip() or not base_url.strip() or not model_names:
                st.error("Provider name, base_url, and at least one model name are required.")
            else:
                providers = dict(st.session_state.get("custom_model_providers") or {})
                providers[name.strip()] = {
                    "base_url": base_url.strip(),
                    "models": model_names,
                }
                st.session_state.custom_model_providers = providers
                st.session_state.show_add_provider = False
                st.rerun()
        if col_cancel.button("Cancel"):
            st.session_state.show_add_provider = False
            st.rerun()


def _render_model_settings_page() -> None:
    st.markdown("### Model Settings")
    st.caption("API keys are kept in this browser session only and are not written to disk.")

    env_config = load_config().model
    if env_config.configured:
        st.info(f"Environment default: `{env_config.base_url}` · `{env_config.model}`")

    providers = _provider_options()
    provider_names = list(providers)
    current_provider = st.session_state.get("model_provider_choice") or "DeepSeek"
    if current_provider not in providers:
        current_provider = provider_names[0]
    provider_name = st.selectbox(
        "Provider",
        provider_names,
        index=provider_names.index(current_provider),
        key="model_provider_choice",
    )
    provider = providers[provider_name]
    base_url = str(provider["base_url"])
    model_names = tuple(str(item) for item in provider["models"])

    st.text_input("base_url", value=base_url, disabled=True)
    model_default = st.session_state.get("ui_model_name")
    model_index = model_names.index(model_default) if model_default in model_names else 0
    model_name = st.selectbox("Model", model_names, index=model_index, key="settings_model_name")
    api_key = st.text_input(
        "API key",
        value=st.session_state.get("ui_model_api_key", ""),
        type="password",
        key="settings_api_key",
    )

    col_save, col_clear, col_back = st.columns([1, 1, 1])
    if col_save.button("Save configuration", type="primary"):
        if not api_key.strip():
            st.error("API key is required before saving this provider configuration.")
        else:
            st.session_state.ui_model_base_url = base_url
            st.session_state.ui_model_api_key = api_key.strip()
            st.session_state.ui_model_name = model_name
            st.session_state.model_settings_open = False
            st.success("Model configuration saved for this browser session.")
            st.rerun()

    if col_clear.button("Clear saved config"):
        for key in ("ui_model_base_url", "ui_model_api_key", "ui_model_name"):
            st.session_state.pop(key, None)
        st.rerun()

    if col_back.button("Back"):
        st.session_state.model_settings_open = False
        st.rerun()

    if st.button("Add provider"):
        st.session_state.show_add_provider = True
    if st.session_state.get("show_add_provider"):
        _render_add_provider_form()


def _render_real_header(model_config: ModelConfig | None) -> None:
    title_col, settings_col = st.columns([0.88, 0.12], vertical_alignment="center")
    title_col.subheader("Natural Language Agent")
    if settings_col.button("⚙", help="Open model settings", use_container_width=True):
        st.session_state.model_settings_open = True
        st.rerun()

    if model_config is None:
        st.warning("Configure a model provider before sending requests.")
    else:
        st.caption(f"Provider: `{model_config.base_url}` · Model: `{model_config.model}`")


def _render_real_mode(
    controller: DemoController,
    session_id: str,
    model_config: ModelConfig | None,
) -> None:
    """Render the Natural Language Agent tab: a chat-style interface that drives the
    AgentController with the user's natural-language request.
    """
    _render_real_header(model_config)
    if st.session_state.get("model_settings_open"):
        _render_model_settings_page()
        return

    _render_real_dataset_import(controller, session_id)
    st.markdown("### Request")
    st.info(
        "Supported scope: uploaded CSV historical price analysis, metrics, charts, and reports."
    )
    previous_run: Run | None = st.session_state.get("last_run")
    clarification = _clarification_text(previous_run)
    if clarification:
        st.markdown("### Clarification needed")
        st.markdown(clarification)
        reply = st.text_area(
            "Reply to agent",
            value="确认，按默认方案继续：全区间、period_return、max_drawdown、annualized_volatility，并生成图表和报告。",
            key="clarification_reply",
            height=100,
        )
        if st.button(
            "Send clarification",
            type="primary",
            disabled=model_config is None or st.session_state.get("running_real", False),
            use_container_width=True,
        ):
            if model_config is None:
                st.error("Configure a model provider before sending requests.")
                return
            user_request = (
                f"Original request:\n{previous_run.user_request}\n\n"
                f"Agent clarification question:\n{clarification}\n\n"
                f"User clarification / confirmation:\n{reply}\n\n"
                "Continue the analysis now. Use the uploaded datasets in this session, "
                "then compute metrics, create charts, and build the report."
            )
            _run_real_agent_request(model_config, session_id, user_request)
        st.divider()

    user_request = st.text_area(
        "Natural-language request",
        placeholder=(
            "e.g. Compare DEMO_A and DEMO_B for January 2024 and tell me "
            "which one had the worse drawdown."
        ),
        height=120,
    )
    submitted = st.button(
        "Send to model",
        type="primary",
        disabled=model_config is None or st.session_state.get("running_real", False),
        use_container_width=True,
    )
    if (
        submitted
        and model_config is not None
        and user_request.strip()
        and not st.session_state.get("running_real", False)
    ):
        if not is_supported_analysis_request(user_request):
            st.error(SUPPORTED_REQUEST_HINT)
            return
        _run_real_agent_request(model_config, session_id, user_request)


def _run_real_agent_request(
    model_config: ModelConfig,
    session_id: str,
    user_request: str,
) -> None:
    from quantlab_agent.agent.controller import build_real_agent_stack

    st.session_state.running_real = True
    try:
        with st.spinner("Driving AgentController..."):
            controller = build_real_agent_stack(RUNS_DIR, model_config)
            run = controller.run_service.create_run(
                session_id=session_id,
                mode=RunMode.REAL_AGENT,
                user_request=user_request,
            )
            final = controller.execute(
                run_id=run.run_id,
                session_id=session_id,
                user_request=user_request,
            )
        st.session_state.last_run = final
        st.session_state.active_run_id = final.run_id
    finally:
        st.session_state.running_real = False
    st.rerun()


def _render_debug_details(session_id: str) -> None:
    with st.expander("Debug details"):
        st.markdown("Session")
        st.code(session_id, language="text")
        if st.session_state.get("active_run_id"):
            st.markdown("Active run")
            st.code(st.session_state.active_run_id, language="text")


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
    session_id = _ensure_session_state()
    controller = _build_controller(str(RUNS_DIR))
    _render_page_header()

    effective_model = _effective_model_config()
    tab_labels = ["Natural Language Agent", "Manual Run", "Results", "Process"]
    tabs = st.tabs(tab_labels)
    tab_real = tabs[0]
    tab_data = tabs[1]
    tab_results = tabs[2]
    tab_process = tabs[-1]

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

    with tab_real:
        _render_real_mode(controller, session_id, effective_model)

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
        _render_debug_details(session_id)


if __name__ == "__main__":
    main()
