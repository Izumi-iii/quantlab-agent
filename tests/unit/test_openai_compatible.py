"""Tests for OpenAICompatibleProvider using urllib mocks."""

from __future__ import annotations

import io
import json
import urllib.error
from typing import Any
from unittest.mock import patch

import pytest

from quantlab_agent.adapters.openai_compatible import OpenAICompatibleProvider
from quantlab_agent.ports.model_provider import ModelProviderError, ModelTurn


def _http_response(body: bytes, status: int = 200) -> Any:
    """Build a context manager that yields a fake http response."""

    class _Resp:
        def __init__(self):
            pass

        def read(self) -> bytes:
            return body

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    class _Ctx:
        def __enter__(self):
            return _Resp()

        def __exit__(self, *_):
            return False

    return _Ctx()


def _openai_payload(content: str | None = None, tool_calls: list | None = None) -> bytes:
    message: dict[str, Any] = {"role": "assistant"}
    if content is not None:
        message["content"] = content
    if tool_calls:
        message["tool_calls"] = tool_calls
        message["content"] = None
    return json.dumps(
        {
            "choices": [
                {
                    "message": message,
                    "finish_reason": "tool_calls" if tool_calls else "stop",
                }
            ]
        }
    ).encode("utf-8")


def _provider() -> OpenAICompatibleProvider:
    return OpenAICompatibleProvider(
        base_url="https://api.example.com/v1",
        api_key="sk-test",
        model="example-model",
    )


def test_text_response_returns_model_turn_with_text() -> None:
    payload = _openai_payload(content="hello")
    with patch(
        "quantlab_agent.adapters.openai_compatible.urllib.request.urlopen",
        return_value=_http_response(payload),
    ):
        turn = _provider().complete_with_tools([], [], timeout_seconds=5)
    assert isinstance(turn, ModelTurn)
    assert turn.text == "hello"
    assert turn.tool_call is None
    assert turn.finish_reason == "stop"


def test_tool_call_response_is_parsed() -> None:
    payload = _openai_payload(
        tool_calls=[
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "inspect_dataset",
                    "arguments": json.dumps({"dataset_id": "0" * 36}),
                },
            }
        ]
    )
    with patch(
        "quantlab_agent.adapters.openai_compatible.urllib.request.urlopen",
        return_value=_http_response(payload),
    ):
        turn = _provider().complete_with_tools([], [], timeout_seconds=5)
    assert turn.tool_call is not None
    assert turn.tool_call.name == "inspect_dataset"
    assert json.loads(turn.tool_call.arguments) == {"dataset_id": "0" * 36}
    assert turn.finish_reason == "tool_calls"


def test_http_error_raises_provider_error() -> None:
    err = urllib.error.HTTPError(
        "https://api.example.com/v1/chat/completions",
        401,
        "Unauthorized",
        {},
        io.BytesIO(b'{"error": "bad key"}'),
    )
    with patch(
        "quantlab_agent.adapters.openai_compatible.urllib.request.urlopen",
        side_effect=err,
    ):
        with pytest.raises(ModelProviderError) as exc:
            _provider().complete_with_tools([], [], timeout_seconds=5)
    assert "HTTP 401" in str(exc.value)


def test_network_error_returns_turn_with_error_field() -> None:
    """Transient network errors must surface as a turn with ``error`` so
    the controller can retry within its budget rather than crash."""
    with patch(
        "quantlab_agent.adapters.openai_compatible.urllib.request.urlopen",
        side_effect=urllib.error.URLError("Connection refused"),
    ):
        turn = _provider().complete_with_tools([], [], timeout_seconds=5)
    assert turn.text is None
    assert turn.tool_call is None
    assert turn.error is not None
    assert "Connection refused" in turn.error


def test_missing_required_args_raises() -> None:
    with pytest.raises(ValueError):
        OpenAICompatibleProvider(base_url="", api_key="k", model="m")
    with pytest.raises(ValueError):
        OpenAICompatibleProvider(base_url="u", api_key="", model="m")
    with pytest.raises(ValueError):
        OpenAICompatibleProvider(base_url="u", api_key="k", model="")
