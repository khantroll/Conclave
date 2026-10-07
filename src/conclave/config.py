from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Literal

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


class ConclaveConfig(BaseModel):
    providers: list[ProviderConfig] = Field(default_factory=list)


def load_config(path: str | Path | None = None) -> ConclaveConfig:
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
