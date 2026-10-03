"""Convert ``ToolDefinition`` to the OpenAI tools wire format.

OpenAI expects each tool as:
    {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}

We use Pydantic's ``model_json_schema()`` for the parameters block, then
post-process to remove properties that confuse strict JSON Schema
parsers (``additionalProperties: false`` is mandatory for OpenAI).
"""

from __future__ import annotations

from typing import Any

from quantlab_agent.agent.tools import ToolDefinition


def tool_definition_to_openai(definition: ToolDefinition) -> dict[str, Any]:
    schema = definition.input_model.model_json_schema()
    parameters = _normalize_schema(schema)
    return {
        "type": "function",
        "function": {
            "name": definition.name,
            "description": definition.description,
            "parameters": parameters,
        },
    }


def tool_definitions_to_openai(definitions: list[ToolDefinition]) -> list[dict[str, Any]]:
    return [tool_definition_to_openai(d) for d in definitions]


def _normalize_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Make a Pydantic-generated JSON Schema OpenAI-compatible.

    OpenAI requires ``additionalProperties: false`` at every object
    level and rejects ``$schema`` / ``title`` keys. We strip both
    recursively.
    """
    cleaned = _strip_meta(schema)
    cleaned["additionalProperties"] = False
    return cleaned


def _strip_meta(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _strip_meta(v) for k, v in node.items() if k not in {"$schema", "title"}}
    if isinstance(node, list):
        return [_strip_meta(item) for item in node]
    return node


__all__ = ["tool_definition_to_openai", "tool_definitions_to_openai"]
