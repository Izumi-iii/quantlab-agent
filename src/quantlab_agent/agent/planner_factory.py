"""Pick a Planner based on whether a model is configured."""

from __future__ import annotations

from quantlab_agent.agent.planner import LLMPlanner, Planner, RulePlanner


def build_planner(model_config: object | None) -> Planner:
    """Return the right planner for the environment.

    When ``model_config.configured`` is True, wrap a real provider in
    ``LLMPlanner``; otherwise return the deterministic ``RulePlanner``.
    Used by both the CLI ``ui`` subcommand and the WebUI server.
    """
    if model_config is not None and getattr(model_config, "configured", False):
        from quantlab_agent.adapters.openai_compatible import OpenAICompatibleProvider

        assert hasattr(model_config, "base_url")
        assert hasattr(model_config, "api_key")
        assert hasattr(model_config, "model")
        provider = OpenAICompatibleProvider(
            base_url=model_config.base_url,
            api_key=model_config.api_key,
            model=model_config.model,
            timeout_seconds=getattr(model_config, "timeout_seconds", 30),
            temperature=getattr(model_config, "temperature", 0.0),
            max_tokens=getattr(model_config, "max_tokens", 1024),
        )
        return LLMPlanner(model_provider=provider)
    return RulePlanner()


__all__ = ["build_planner"]
