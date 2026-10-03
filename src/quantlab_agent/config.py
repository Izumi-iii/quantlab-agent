"""Environment-driven configuration.

Reads the model provider settings needed for M3 (real-model
integration). All settings are optional; if ``QUANTLAB_MODEL_API_KEY``
is unset, the CLI/UI run in demo mode. See README.md for the list of
supported providers (anything with an OpenAI-compatible
``/v1/chat/completions`` endpoint).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class ModelConfig:
    """Provider-agnostic model configuration.

    ``base_url`` is the root of the chat-completions endpoint; the
    provider appends ``/chat/completions`` at call time. Examples:

    - OpenAI:    https://api.openai.com/v1
    - DeepSeek:  https://api.deepseek.com/v1
    - Moonshot:  https://api.moonshot.cn/v1
    - Zhipu/GLM: https://open.bigmodel.cn/api/paas/v4
    - Volcengine Doubao: https://ark.cn-beijing.volces.com/api/v3
    - Alibaba Qwen: https://dashscope.aliyuncs.com/compatible-mode/v1
    """

    base_url: str = ""
    api_key: str = ""
    model: str = ""
    timeout_seconds: float = 30.0
    temperature: float = 0.0
    max_tokens: int = 4096

    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)


@dataclass(frozen=True, slots=True)
class AppConfig:
    app_mode: str = "demo"
    runs_dir: Path = Path("runs")
    matplotlib_backend: str = "Agg"
    model: ModelConfig = ModelConfig()


def load_config() -> AppConfig:
    runs_dir = Path(os.environ.get("QUANTLAB_RUNS_DIR", "runs"))
    model = ModelConfig(
        base_url=os.environ.get("QUANTLAB_MODEL_BASE_URL", ""),
        api_key=os.environ.get("QUANTLAB_MODEL_API_KEY", ""),
        model=os.environ.get("QUANTLAB_MODEL_NAME", ""),
        timeout_seconds=float(os.environ.get("QUANTLAB_MODEL_TIMEOUT", "30")),
        temperature=float(os.environ.get("QUANTLAB_MODEL_TEMPERATURE", "0")),
        max_tokens=int(os.environ.get("QUANTLAB_MODEL_MAX_TOKENS", "4096")),
    )
    return AppConfig(
        app_mode=os.environ.get("QUANTLAB_APP_MODE", "demo"),
        runs_dir=runs_dir,
        matplotlib_backend=os.environ.get("QUANTLAB_MATPLOTLIB_BACKEND", "Agg"),
        model=model,
    )


__all__ = ["AppConfig", "ModelConfig", "load_config"]
