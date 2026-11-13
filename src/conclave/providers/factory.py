from __future__ import annotations

from collections.abc import Iterable

from ..config import ProviderConfig, read_api_key
from .base import Provider
from .openai_compatible import OpenAICompatibleProvider
from .unavailable import UnavailableProvider


def build_providers(configs: Iterable[ProviderConfig]) -> dict[str, Provider]:
    providers: dict[str, Provider] = {}

    for config in configs:
        if config.name in providers:
            raise ValueError(f"Duplicate provider name: {config.name}")

        if config.kind == "openai_compatible":
            try:
                api_key = read_api_key(config)
            except RuntimeError as exc:
                providers[config.name] = UnavailableProvider(str(exc))
                continue

            providers[config.name] = OpenAICompatibleProvider(
                base_url=config.base_url,
                model=config.model,
                api_key=api_key,
                system_prompt=config.system_prompt,
                extra_headers=config.extra_headers,
                input_cost_per_million=config.input_cost_per_million,
                output_cost_per_million=config.output_cost_per_million,
                transient_max_retries=config.transient_max_retries,
                retry_backoff_seconds=config.retry_backoff_seconds,
            )
            continue

        raise ValueError(f"Unsupported provider kind: {config.kind}")

    return providers
