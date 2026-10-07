# Configuration

Conclave separates **provider metadata** from **provider secrets**.

- Provider definitions live in `conclave.json` (or the path named by `CONCLAVE_CONFIG_PATH`).
- API keys stay in environment variables referenced by `api_key_env`.
- Workspaces and run history live in SQLite at `CONCLAVE_DB_PATH`.

## Provider example

```json
{
  "providers": [
    {
      "name": "openai",
      "kind": "openai_compatible",
      "base_url": "https://api.openai.com/v1",
      "model": "gpt-5.6",
      "api_key_env": "OPENAI_API_KEY",
      "capabilities": ["general", "reasoning", "code"],
      "priority": 20,
      "input_cost_per_million": 0.0,
      "output_cost_per_million": 0.0
    }
  ]
}
```

Replace the pricing values with the actual current API rates for the exact model/provider combination you configure. If either pricing field is omitted, Conclave will still record provider-reported token usage but will not estimate that portion of cost.

## Capability tags

Capability tags are deliberately lightweight. Current request analysis can infer these tags:

- `general`
- `reasoning`
- `critical`
- `research`
- `code`
- `creative`
- `fast`
- `privacy`

They are hints for deterministic workspace routing, not claims about a model's objective intelligence.

## Priority

Lower numeric `priority` values are preferred when two providers match the requested capabilities equally well. Workspace order is used as the final stable tie breaker.

## Gateways

A provider entry may point directly to an OpenAI-compatible vendor API or to a gateway such as LiteLLM Proxy or OpenRouter. Conclave's orchestration behavior remains the same either way.

## Connectivity test

The web console exposes an explicit **Test** button for each configured provider. It sends a tiny request to that provider. This can incur a small API charge on paid endpoints.
