"""Deterministic in-memory ``ModelProvider`` for tests and offline demos.

The fake plays back a scripted list of ``ModelTurn`` values in
response to successive ``complete_with_tools`` calls, so a test can
verify the AgentController's loop without hitting any network.

Typical usage:

    provider = FakeProvider([
        ModelTurn(tool_call=ToolCall(id="t1", name="inspect_dataset",
                                     arguments='{"dataset_id": "..."}')),
        ModelTurn(text="Analysis complete."),
    ])
    controller = AgentController(provider=provider, ...)
    controller.execute(...)

When the script is exhausted the fake returns a ``ModelTurn(error=...)``
so the controller stops with a clear failure rather than hanging.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from quantlab_agent.ports.model_provider import ModelProvider, ModelTurn


class FakeProvider(ModelProvider):
    def __init__(
        self,
        scripted_turns: Iterable[ModelTurn],
        *,
        echo_calls: bool = False,
    ) -> None:
        self._scripted = list(scripted_turns)
        self._echo_calls = echo_calls
        self.calls: list[dict[str, Any]] = []

    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        timeout_seconds: float,
    ) -> ModelTurn:
        if self._echo_calls:
            self.calls.append(
                {
                    "messages": list(messages),
                    "tools": list(tools),
                    "timeout_seconds": timeout_seconds,
                }
            )
        if not self._scripted:
            return ModelTurn(
                error="FakeProvider: scripted turns exhausted.",
                finish_reason="stop",
            )
        return self._scripted.pop(0)

    @property
    def remaining(self) -> int:
        return len(self._scripted)


__all__ = ["FakeProvider"]
