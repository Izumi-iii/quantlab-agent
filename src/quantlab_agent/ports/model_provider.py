"""Model-provider Protocol used by AgentController.

The Protocol is intentionally narrow: one ``complete_with_tools`` call
that takes the current message history plus the tool catalog and
returns a ``ModelTurn``. The provider adapter is responsible for
mapping our tool format to whatever wire protocol its model expects
(OpenAI-compatible, Anthropic, etc.).

We deliberately do not depend on any third-party SDK here. Adapters
use ``urllib`` (stdlib) so the project keeps no provider-specific
dependency and tests can mock the HTTP boundary without extra fixtures.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol


@dataclass(frozen=True, slots=True)
class ToolCall:
    """One tool invocation requested by the model.

    ``arguments`` is a JSON string per OpenAI convention; the agent
    controller parses it before passing to ToolRegistry.
    """

    id: str
    name: str
    arguments: str


@dataclass(frozen=True, slots=True)
class ModelTurn:
    """One assistant message returned by the model.

    Exactly one of ``text`` / ``tool_call`` / ``error`` is populated per
    turn. ``finish_reason`` mirrors the OpenAI vocabulary
    (``"stop"`` / ``"tool_calls"`` / ``"length"`` / ``"content_filter"``)
    so callers can branch predictably.
    """

    text: str | None = None
    tool_call: ToolCall | None = None
    error: str | None = None
    finish_reason: Literal["stop", "tool_calls", "length", "content_filter"] = "stop"
    raw: dict[str, Any] = field(default_factory=dict)


class ModelProvider(Protocol):
    """Adapter that talks to one concrete LLM endpoint.

    Implementations must:
    - Send a chat-completions request with the supplied messages and tools.
    - Translate the response into a ``ModelTurn``.
    - Classify failures into a short ``error`` string suitable for
      surfacing in a tool-result envelope; do not raise for transient
      HTTP errors. Persistent bugs should still raise ``ModelProviderError``.
    """

    def complete_with_tools(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        timeout_seconds: float,
    ) -> ModelTurn: ...


class ModelProviderError(RuntimeError):
    """Raised when the provider cannot continue (e.g. 4xx other than 429)."""
