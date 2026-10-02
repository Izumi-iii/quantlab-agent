"""Smoke tests for the Streamlit UI entry point.

We use Streamlit's ``AppTest`` to exercise the module without launching
a browser. Behavioural coverage of the underlying tool pipeline lives
in ``tests/integration/test_demo_flow.py``.
"""

from __future__ import annotations

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
