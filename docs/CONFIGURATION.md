# Configuration

Conclave separates **provider metadata** from **provider secrets**.

- Provider definitions live in `conclave.json` (or the path named by `CONCLAVE_CONFIG_PATH`).
- API keys stay in environment variables referenced by `api_key_env`.
- A local `.env` file is loaded automatically and is ignored by Git.
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


## Local .env support

For a local single-user install, copy `.env.example` to `.env` and fill only the variables you actually use. Both `.env` and the local `conclave.json` are ignored by Git.

Conclave does not return API keys through its web API. Provider descriptors expose model/capability/pricing metadata only.

## Local-only security assumption

The pre-alpha has no multi-user authentication layer. Run it on localhost unless you intentionally place it behind your own authenticated reverse proxy. Workspace context, exact prompts, and model responses are persisted locally in SQLite and may contain sensitive material.


## Restart required after provider changes

Provider configuration is loaded when Conclave starts. After editing `conclave.json` or changing values in `.env`, restart the uvicorn process before using the provider test buttons. The web console shows whether Conclave is currently running in **demo only** mode or has real configured providers available.


## First real three-model panel

The current generic OpenAI-compatible adapter can talk directly to all three of the first real providers:

- **Gemini** via Google's OpenAI-compatible endpoint at `https://generativelanguage.googleapis.com/v1beta/openai`
- **Mistral** via `https://api.mistral.ai/v1`
- **Groq** via `https://api.groq.com/openai/v1`

That means Conclave does not need separate native SDK adapters to begin real multi-model testing. `conclave.example.json` now includes working provider shapes for all three, plus optional OpenRouter and local-model examples.

For a first real workspace, start with:

- Delegates: `gemini, mistral, groq`
- Critic: `mistral`
- Arbiter: `gemini`
- Minimum successes: `2`
- Automatic subset selection: off for the first comparison run

Suggested roles:

```text
gemini = Broad-context analyst. Explore alternatives and important external assumptions.
mistral = Skeptical technical reviewer. Look for failure modes, scope creep, and weak reasoning.
groq = Independent fast generalist. Solve the problem independently and challenge obvious consensus.
```

Once that fixed three-model path is proven, enable automatic delegate selection and let simpler questions use fewer models.

Model availability can change. If a provider Test button reports a model-not-found error, update only that provider's `model` value in `conclave.json`, restart Conclave, and test again.


## Transient retry policy

OpenAI-compatible providers now retry a small set of transient HTTP failures automatically:

- 429 Too Many Requests
- 502 Bad Gateway
- 503 Service Unavailable
- 504 Gateway Timeout

The defaults are two retries with exponential backoff starting at one second. Numeric and HTTP-date `Retry-After` values are supported with a ten-second cap; past dates become zero delay, and invalid or non-finite values use exponential backoff. The cap can cause a retry earlier than a provider's requested wait, so long rate limits can still exhaust retries. Authentication, authorization, model-not-found, and other non-transient errors are not retried.

Completed failures retain the number of HTTP attempts in saved results and provider connectivity tests, including transport or malformed-response failures after a transient retry. Transport failures are not automatically replayed because the provider may already have accepted the request. Timeout results still use the existing default attempt count; they do not report an exact count of interrupted HTTP attempts.

Per-provider settings may override the defaults:

```json
{
  "transient_max_retries": 2,
  "retry_backoff_seconds": 1.0
}
```

The orchestrator's timeout bounds each provider invocation, including its retries and backoff. Each configured Critic/Arbiter fallback receives its own timeout; a stage with multiple fallbacks can therefore take longer than one timeout interval.


## Critic and Arbiter fallbacks

Workspaces may define ordered fallback providers for the downstream stages.

Example:

```text
Critic: mistral
Critic fallbacks: openrouter-free, groq

Arbiter: gemini
Arbiter fallbacks: groq, openrouter-free
```

Conclave always tries the primary provider first. A fallback is tried only if the preceding provider fails or times out. The first successful result becomes the Critic or Arbiter result and retains the actual provider name that produced it.

This is intended for provider resilience, not silent majority voting. The fallback order is explicit and deterministic.


## Automatic run audit logs

Every workspace deliberation and every saved retry now writes a pretty-printed JSON audit file in addition to the SQLite history.

By default the files are written to:

```text
run_logs/
```

Set a different directory with:

```text
CONCLAVE_RUN_LOG_DIR=run_logs
```

Each filename contains the UTC run timestamp and run UUID. The JSON envelope includes:

- a schema version;
- export timestamp;
- a snapshot of the workspace as it existed for that saved run;
- the complete saved run;
- the original question and request snapshot;
- selected Delegates and role instructions;
- workspace context;
- exact Delegate, Critic, and Arbiter prompts;
- untouched model responses;
- actual provider/model names;
- stage status, latency, token usage, cost estimates, and retry-attempt telemetry;
- Critic and Arbiter results, including whichever fallback provider actually succeeded.

The directory is ignored by Git because these logs can contain private workspace context, prompts, model responses, or other sensitive material. Treat them with the same care as the SQLite database.

The browser's existing **Download run JSON** control remains available for manual export; the automatic audit log means a human-testing run does not depend on remembering to click it.

