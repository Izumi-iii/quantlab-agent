"""Tests for the OpenAI tool-schema converter."""

from __future__ import annotations

from pydantic import BaseModel, Field

from quantlab_agent.agent.tool_format import tool_definition_to_openai
from quantlab_agent.agent.tools import ToolDefinition


class _SampleInput(BaseModel):
    model_config = {"extra": "forbid"}
    dataset_id: str = Field(min_length=36, max_length=36)
    count: int = 0


def _dummy_handler(ctx, args):  # noqa: ANN001
    return {}


def test_tool_definition_to_openai_shape() -> None:
    defn = ToolDefinition(
        name="inspect_dataset",
        description="Return metadata for a dataset.",
        input_model=_SampleInput,
        output_description="dataset summary",
        handler=_dummy_handler,
    )
    payload = tool_definition_to_openai(defn)
    assert payload["type"] == "function"
    assert payload["function"]["name"] == "inspect_dataset"
    assert payload["function"]["description"] == "Return metadata for a dataset."
    params = payload["function"]["parameters"]
    assert params["type"] == "object"
    assert params["required"] == ["dataset_id"]
    assert params["properties"]["dataset_id"]["type"] == "string"
    assert params["additionalProperties"] is False


def test_strips_pydantic_meta_keys() -> None:
    defn = ToolDefinition(
        name="t",
        description="d",
        input_model=_SampleInput,
        output_description="o",
        handler=_dummy_handler,
    )
    params = tool_definition_to_openai(defn)["function"]["parameters"]
    assert "$schema" not in params
    assert "title" not in params
    assert "title" not in params["properties"]
