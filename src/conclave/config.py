from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field


class ProviderConfig(BaseModel):
    name: str = Field(min_length=1)
    kind: Literal["openai_compatible"] = "openai_compatible"
    base_url: str = Field(min_length=1)
    model: str = Field(min_length=1)
    api_key_env: str | None = None
    system_prompt: str | None = None
    extra_headers: dict[str, str] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)
    priority: int = 100
    input_cost_per_million: float | None = Field(default=None, ge=0)
    output_cost_per_million: float | None = Field(default=None, ge=0)
    # A gateway name that picks a model per call (for example openrouter/free). Such a
    # provider is identified only by the model it reports.
    router_alias: bool = False
    transient_max_retries: int = Field(default=2, ge=0, le=5)
    retry_backoff_seconds: float = Field(default=1.0, ge=0, le=30)


class ConclaveConfig(BaseModel):
    providers: list[ProviderConfig] = Field(default_factory=list)


def load_config(path: str | Path | None = None, *, load_env: bool = True) -> ConclaveConfig:
    if load_env:
        load_dotenv()
    resolved = Path(path or os.getenv("CONCLAVE_CONFIG_PATH", "conclave.json"))
    if not resolved.exists():
        return ConclaveConfig()
    data = json.loads(resolved.read_text(encoding="utf-8"))
    return ConclaveConfig.model_validate(data)


def read_api_key(config: ProviderConfig) -> str | None:
    if not config.api_key_env:
        return None
    value = os.getenv(config.api_key_env)
    if not value:
        raise RuntimeError(
            f"Provider '{config.name}' requires environment variable "
            f"{config.api_key_env}"
        )
    return value
