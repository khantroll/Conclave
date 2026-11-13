from conclave.models import DelegateResult, DelegateStatus
from conclave.sources import (
    SAME_CONFIG,
    SAME_REPORTED_MODEL,
    UNRESOLVED_ROUTER_ALIAS,
    ProviderIdentity,
    group_sources,
    normalize_base_url,
    normalize_reported_model,
    sharing_config,
)


def ok(name, model=None):
    return DelegateResult(name=name, status=DelegateStatus.SUCCEEDED, raw_response="x", model=model)


def failed(name):
    return DelegateResult(name=name, status=DelegateStatus.FAILED, error="boom")


def ident(model, base_url="https://api.example.com/v1", alias=False):
    return ProviderIdentity(base_url=base_url, model=model, router_alias=alias)


def names(groups):
    return [g.delegates for g in groups]


def test_base_url_normalization_lowercases_scheme_and_host_and_strips_slashes():
    assert normalize_base_url("HTTPS://API.Example.COM/v1/") == "https://api.example.com/v1"
    assert normalize_base_url("https://api.example.com/V1//") == "https://api.example.com/V1"
    assert normalize_base_url(" http://localhost:1234/v1 ") == "http://localhost:1234/v1"


def test_reported_model_normalization():
    assert normalize_reported_model("openai/gpt-x") == "gpt-x"
    assert normalize_reported_model("gpt-x-2026-08-06") == "gpt-x"
    assert normalize_reported_model("GPT-X-20260806") == "gpt-x"
    assert normalize_reported_model("openai/GPT-X-2026-08-06") == "gpt-x"
    assert normalize_reported_model("gpt-x-mini") == "gpt-x-mini"
    assert normalize_reported_model("gpt-4") == "gpt-4"
    assert normalize_reported_model("") is None
    assert normalize_reported_model("  ") is None
    assert normalize_reported_model(None) is None


def test_same_base_url_and_model_is_one_source():
    identities = {"a": ident("m1"), "b": ident("m1", "HTTPS://API.EXAMPLE.COM/v1/")}
    groups = group_sources([ok("a", "m1"), ok("b", "m1")], identities)
    assert names(groups) == [["a", "b"]]
    assert groups[0].reason == SAME_CONFIG


def test_different_models_are_separate_sources():
    identities = {"a": ident("m1"), "b": ident("m2")}
    groups = group_sources([ok("a", "m1"), ok("b", "m2")], identities)
    assert names(groups) == [["a"], ["b"]]
    assert all(g.reason is None for g in groups)


def test_different_gateways_reporting_one_model_are_one_source():
    identities = {
        "direct": ident("gpt-x", "https://api.one.com/v1"),
        "other": ident("gpt-x-latest", "https://api.two.com/v1"),
    }
    groups = group_sources(
        [ok("direct", "openai/gpt-x"), ok("other", "gpt-x-2026-08-06")], identities
    )
    assert names(groups) == [["direct", "other"]]
    assert groups[0].reason == SAME_REPORTED_MODEL


def test_two_unresolved_router_aliases_on_one_host_are_one_source():
    identities = {
        "r1": ident("openrouter/free", "https://openrouter.ai/api/v1", alias=True),
        "r2": ident("openrouter/auto", "https://openrouter.ai/api/v1", alias=True),
    }
    # One reports nothing, one only echoes its own alias name: neither revealed a model.
    groups = group_sources([ok("r1", None), ok("r2", "openrouter/auto")], identities)
    assert names(groups) == [["r1", "r2"]]
    assert groups[0].reason == UNRESOLVED_ROUTER_ALIAS


def test_router_aliases_are_identified_by_what_they_report():
    identities = {
        "r1": ident("openrouter/free", "https://openrouter.ai/api/v1", alias=True),
        "r2": ident("openrouter/free", "https://openrouter.ai/api/v1", alias=True),
    }
    # Same config, but the router picked different models, so they are different sources.
    groups = group_sources([ok("r1", "meta/llama-3"), ok("r2", "qwen/qwen-3")], identities)
    assert names(groups) == [["r1"], ["r2"]]
    # The router picked the same model twice: one source.
    groups = group_sources([ok("r1", "meta/llama-3-2026-01-02"), ok("r2", "llama-3")], identities)
    assert names(groups) == [["r1", "r2"]]
    assert groups[0].reason == SAME_REPORTED_MODEL


def test_a_resolved_alias_matches_a_direct_provider_serving_the_same_model():
    identities = {
        "direct": ident("llama-3", "https://api.groq.com/v1"),
        "router": ident("openrouter/free", "https://openrouter.ai/api/v1", alias=True),
    }
    groups = group_sources([ok("direct", "llama-3"), ok("router", "meta/llama-3")], identities)
    assert names(groups) == [["direct", "router"]]


def test_unresolved_alias_never_merges_with_a_real_model():
    identities = {
        "direct": ident("openrouter/free", "https://openrouter.ai/api/v1"),
        "router": ident("openrouter/free", "https://openrouter.ai/api/v1", alias=True),
    }
    groups = group_sources([ok("direct", "x-model"), ok("router", None)], identities)
    assert names(groups) == [["direct"], ["router"]]


def test_failed_delegates_are_not_sources():
    identities = {"a": ident("m1"), "b": ident("m1")}
    groups = group_sources([ok("a", "m1"), failed("b")], identities)
    assert names(groups) == [["a"]]


def test_providers_without_identity_are_never_merged():
    groups = group_sources([ok("demo-a", "fake-model"), ok("demo-b", "fake-model")], {})
    assert names(groups) == [["demo-a"], ["demo-b"]]


def test_merges_are_transitive_and_same_config_wins_as_the_reason():
    identities = {
        "a": ident("m1", "https://one.com/v1"),
        "b": ident("m1", "https://one.com/v1"),
        "c": ident("other", "https://two.com/v1"),
    }
    groups = group_sources([ok("a", "m1"), ok("b", "m1"), ok("c", "M1-2026-01-01")], identities)
    assert names(groups) == [["a", "b", "c"]]
    assert groups[0].reason == SAME_CONFIG


def test_sharing_config_lists_only_non_alias_duplicates():
    identities = {
        "a": ident("m1"),
        "b": ident("m1"),
        "c": ident("m2"),
        "r1": ident("free", alias=True),
        "r2": ident("free", alias=True),
    }
    assert sharing_config(["a", "b", "c", "r1", "r2", "unknown"], identities) == [["a", "b"]]
