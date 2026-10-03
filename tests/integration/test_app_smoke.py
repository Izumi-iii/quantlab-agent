"""Smoke tests for the Streamlit UI entry point.

We use Streamlit's ``AppTest`` to exercise the module without launching
a browser. Behavioural coverage of the underlying tool pipeline lives
in ``tests/integration/test_demo_flow.py``.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

APP_PATH = Path(__file__).parents[2] / "app.py"


def test_app_module_imports() -> None:
    import app  # noqa: F401 - smoke import

    assert hasattr(app, "main")
    assert hasattr(app, "_build_controller")
    assert hasattr(app, "_render_data_form")
    assert hasattr(app, "_render_results")
    assert hasattr(app, "_render_process")


def test_build_controller_is_cached() -> None:
    import app

    cache_func = app._build_controller
    assert "cache_resource" in str(type(cache_func)) or hasattr(cache_func, "__wrapped__")


@pytest.fixture
def redirected_runs_dir(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("app.RUNS_DIR", tmp_path)
    return tmp_path


def test_app_renders_without_exception(redirected_runs_dir: Path) -> None:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP_PATH), default_timeout=30)
    at.run()

    assert not at.exception, f"App raised: {at.exception}"
    titles = [h.value for h in at.title]
    assert any("QuantLab Agent" in t for t in titles)


def test_app_generates_session_uuid(redirected_runs_dir: Path) -> None:
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP_PATH), default_timeout=30)
    at.run()

    assert "session_uuid" in at.session_state
    session_id = at.session_state["session_uuid"]
    assert isinstance(session_id, str)
    assert len(session_id) == 36  # UUID4 length


def test_app_run_button_visible(redirected_runs_dir: Path) -> None:
    """Verify the Run Analysis button is present on first render."""
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP_PATH), default_timeout=30)
    at.run()

    assert not at.exception, f"App raised: {at.exception}"
    labels = [b.label for b in at.button]
    assert "Run Analysis" in labels
    assert "Reset UI" in labels


def test_run_button_unlocks_after_failed_submission(
    redirected_runs_dir: Path,
) -> None:
    """Regression test: clicking Run Analysis without uploading a CSV must
    leave ``st.session_state.running`` cleared so the button becomes
    clickable again. The previous implementation called ``st.stop()``
    inside the import path, which prevented the ``finally`` block from
    clearing the flag and locked the button until the page was refreshed.
    """
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(APP_PATH), default_timeout=30)
    at.run()

    run_buttons = [b for b in at.button if b.label == "Run Analysis"]
    assert run_buttons, "Expected a Run Analysis button"
    run_buttons[0].click()
    at.run()

    assert not at.exception, f"App raised after failed click: {at.exception}"
    # The critical invariant: the running flag must be cleared so the
    # button is no longer permanently disabled.
    assert at.session_state.get("running") is False, (
        f"running flag stuck at {at.session_state.get('running')!r}; "
        "this would lock the submit button forever."
    )


def test_demo_controller_exposes_all_stores() -> None:
    """Regression test: the UI reads chart/report/dataset stores directly
    off the controller. If any of these attributes disappear, the
    results tab crashes with AttributeError when rendering charts.
    """
    from quantlab_agent.agent.demo import default_demo_controller

    controller = default_demo_controller(Path(tempfile.mkdtemp()))
    for attr in ("dataset_store", "chart_store", "report_store"):
        assert hasattr(controller, attr), f"DemoController missing {attr!r}"
        assert getattr(controller, attr) is not None


def test_run_service_exposes_list_tool_calls() -> None:
    """Regression test: the Process tab in the UI calls
    ``controller._runs.list_tool_calls(...)``. The method must be exposed
    on ``RunService`` (the public surface), not require callers to
    reach through two layers of private attributes into ``RunStore``.
    """
    from quantlab_agent.application.runs import RunService

    assert hasattr(RunService, "list_tool_calls"), (
        "RunService.list_tool_calls is missing — the UI Process tab will "
        "crash with AttributeError. Either add the method or update the UI."
    )
