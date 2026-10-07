import json

import pytest

from conclave.config import ProviderConfig, load_config, read_api_key
from conclave.providers.factory import build_providers
from conclave.providers.openai_compatible import OpenAICompatibleProvider


def test_load_config_and_build_provider(tmp_path, monkeypatch):
    config_path = tmp_path / "conclave.json"
    config_path.write_text(
        json.dumps(
            {
                "providers": [
                    {
                        "name": "gateway",
                        "base_url": "http://localhost:4000/v1",
                        "model": "example-model",
                        "api_key_env": "TEST_GATEWAY_KEY",
                        "capabilities": ["research", "general"],
                        "priority": 25,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("TEST_GATEWAY_KEY", "secret")

    config = load_config(config_path)
    providers = build_providers(config.providers)

    assert list(providers) == ["gateway"]
    assert isinstance(providers["gateway"], OpenAICompatibleProvider)
    assert config.providers[0].capabilities == ["research", "general"]
    assert config.providers[0].priority == 25


def test_read_api_key_requires_declared_environment_variable(monkeypatch):
    monkeypatch.delenv("MISSING_TEST_KEY", raising=False)
    config = ProviderConfig(
        name="missing",
        base_url="http://localhost:1234/v1",
        model="local",
        api_key_env="MISSING_TEST_KEY",
    )

    with pytest.raises(RuntimeError, match="MISSING_TEST_KEY"):
        read_api_key(config)


def test_missing_config_is_empty(tmp_path):
    config = load_config(tmp_path / "does-not-exist.json")
    assert config.providers == []
