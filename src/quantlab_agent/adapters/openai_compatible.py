"""OpenAI-compatible HTTP adapter.

Talks to any endpoint that exposes the ``/v1/chat/completions`` schema
used by OpenAI: OpenAI itself, DeepSeek, Moonshot/Kimi, Zhipu/GLM,
Volcengine/Doubao, Alibaba/Qwen, Baidu/Qianfan, etc.

The endpoint is fully configured at construction time via
``base_url``, ``api_key``, and ``model``. The provider does no
retries; the controller is responsible for budget and retry policy
(see ``RunBudgetPolicy.max_retryable_network_errors``).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from quantlab_agent.ports.model_provider import (
    ModelProviderError,
    ModelTurn,
    ToolCall,
)


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout_seconds: float = 30.0,
        temperature: float = 0.0,
        max_tokens: int = 4096,
        client_name: str = "quantlab-agent",
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not api_key:
            raise ValueError("api_key is required")
        if not model:
            raise ValueError("model is required")
        # Strip trailing slash for clean URL composition.
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._client_name = client_name

    @property
    def model_name(self) -> str:
        return self._model

    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        timeout_seconds: float,
    ) -> ModelTurn:
        url = f"{self._base_url}/chat/completions"
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"

        request = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": self._client_name,
            },
            method="POST",
        )
        effective_timeout = timeout_seconds or self._timeout_seconds
        try:
            with urllib.request.urlopen(request, timeout=effective_timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:512]
            raise ModelProviderError(f"HTTP {exc.code} from {url}: {detail}") from exc
        except urllib.error.URLError as exc:
            # Treat connection / timeout errors as a transient tool failure
            # so the controller can retry within its retry budget.
            return ModelTurn(
                error=f"network error: {exc.reason}",
                finish_reason="stop",
                raw={},
            )
        except TimeoutError:
            return ModelTurn(
                error=f"timeout after {effective_timeout}s",
                finish_reason="stop",
                raw={},
            )

        return _parse_response(payload)


def _parse_response(payload: dict[str, Any]) -> ModelTurn:
    """Translate the JSON response into a ``ModelTurn``."""
    if not payload.get("choices"):
        err = payload.get("error") or payload
        return ModelTurn(
            error=str(err),
            finish_reason="stop",
            raw=payload,
        )

    choice = payload["choices"][0]
    message = choice.get("message") or {}
    finish_reason = choice.get("finish_reason") or "stop"
    raw = payload

    tool_calls = message.get("tool_calls") or []
    if tool_calls:
        first = tool_calls[0]
        function = first.get("function") or {}
        name = function.get("name", "")
        arguments = function.get("arguments", "") or ""
        # OpenAI returns arguments as a JSON string; normalise.
        if isinstance(arguments, dict):
            arguments = json.dumps(arguments)
        return ModelTurn(
            tool_call=ToolCall(id=first.get("id") or "", name=name, arguments=arguments),
            finish_reason=_normalise_finish_reason(finish_reason),
            raw=raw,
        )

    content = message.get("content")
    return ModelTurn(
        text="" if content is None else str(content),
        finish_reason=_normalise_finish_reason(finish_reason),
        raw=raw,
    )


_VALID_FINISH_REASONS = {"stop", "tool_calls", "length", "content_filter"}


def _normalise_finish_reason(reason: str) -> str:
    return reason if reason in _VALID_FINISH_REASONS else "stop"


__all__ = ["OpenAICompatibleProvider"]
