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

## Independent sources and `router_alias`

Agreement only means something when the answers come from different underlying models, so Conclave counts independent sources, not raw answers. Quorum (`minimum_successes`) is measured against that count. Two delegates are one source when any of these holds:

- Their configured identity is equal: the same `base_url` (scheme and host are case-insensitive, trailing slashes ignored) and the same `model`.
- The model each one *reported* in its response is equal, after lowercasing, dropping a leading `vendor/` segment, and dropping a trailing date suffix such as `-2026-08-06` or `-20260806`. So `openai/gpt-x` and `gpt-x-2026-08-06` are the same model.

- Their answers are copies or near-copies of each other (`near_duplicate_text`). Both answers are normalized (Unicode NFKC, lowercase, invisible characters and punctuation removed, whitespace collapsed), then compared as sets of 5-word sequences. They match when the texts are equal, when the Jaccard similarity is at least 0.50, or when one contains at least 90% of the other's sequences. The score is saved on the group as `similarity`. Han and kana characters count as one word each, since those scripts have no spaces. Matching is by connected group: if A resembles B and B resembles C, all three count as one source even when A and C share little, because each is a copy of the one before it. Answers under 20 normalized words are never compared, because short answers ("Yes.") coincide legitimately. This catches a gateway serving one model under two names, cached replies, and a deterministic model asked twice. Matching text is not agreement: two answers that overlap are **not** merged when their stated `Conclusion:` lines differ, when they carry different numbers, or when they contain a different number of negations (so the same background with "do it" and "do not do it" stays two sources and the dissent is kept). A merge by text is described to the judges as nearly identical text that may be copying, never as proof of a shared origin; only known shared configuration or reported model is called "the same underlying source". The thresholds are constants in `sources.py`, checked against `tests/fixtures/near_duplicates.json` (30 labelled pairs, including unspaced Chinese: copies, light edits, padded copies, paraphrases by different models, and unrelated answers). The Jaccard threshold is 0.50 rather than a stricter value because a handful of changed words in a short answer removes many sequences; paraphrases score near 0 and shared boilerplate about 0.3.

An empty or whitespace-only answer is a failure (`error_kind: "empty_response"`) and never counts.

A gateway name that picks a model per call, such as `openrouter/free`, should be marked `"router_alias": true`. Such a provider is identified only by the model it reports. If it reports nothing, or only repeats its own alias name, it is an unresolved alias, and unresolved aliases on one host count as one source.

A workspace may hold two delegates of one configured model (sampling a model twice can be deliberate). It saves with a warning, and the two answers count as one source. Each run records the grouping in `panel.sources` and the count in `panel.independent_source_count`, and the Critic and Arbiter prompts say which responses share a source. The direct endpoints `POST /api/deliberate` and `POST /api/panel` apply the same validation as workspaces: duplicate or unknown provider names are rejected with HTTP 422.

An optional `family` field on a provider (for example `"openai"`, `"meta"`, `"mistral"`) records which model family it belongs to. It never changes source counting. Where known, each run stores `panel.families` and `panel.distinct_families`, the console shows a line such as "3 independent sources from 2 model families", and the Critic and Arbiter are told by label which responses share a family (never the family name). Both judge prompts and the console always carry one fixed sentence: "Agreement between responses is not evidence of correctness."

Limits: text similarity catches copies. This is based on configuration, the reported model name and text overlap. It cannot detect correlation from shared training data or common sources, and no Conclave label claims independent verification.

## Quorum, automatic selection and single-source runs

`minimum_successes` is the number of **independent sources** a run needs, and it is never lowered.

- **Automatic selection tops up.** If a workspace uses automatic delegate selection and the question picks fewer delegates than the quorum needs, Conclave adds delegates from the workspace pool, in preference order, until the sources they represent reach the quorum. A candidate that would only repeat a source already chosen (same configured model) is skipped, providers that are not configured or lack credentials are never added, and only as many as needed are added. The saved request records `selection.auto_selected` and `selection.topped_up`. There is no per-run spending limit in Conclave yet, so top-up is bounded only by the quorum and by the pool you configured.
- **If the quorum cannot be reached, the run does not start.** The server answers HTTP 422 with `code: "quorum_unmet"`, the number of sources required and available, which delegates were selected, which providers were unavailable and why, and which delegates share a source. No provider is called and no run is stored. The same check applies to `POST /api/deliberate`, which runs exactly the delegates you list.
- **The final check uses the answers that arrived.** Choosing enough sources does not guarantee enough answers. After the panel runs, `panel.quorum` reports `met`, `unmet` or `single_source_override`, counting only non-empty answers grouped into independent sources. When it is `unmet` the Critic and Arbiter are not run, and the report names each delegate that timed out, failed or returned nothing, and any answers that collapsed into one source.
- **Single-source runs are opt-in.** A workspace (or a direct request) may set `allow_single_source: true`. Then, when exactly one independent source is available or answers, the run proceeds with one delegate and is labelled `single_source_override`: it states that the quorum was not met and is not a consensus. It never covers two sources when three are required. Without the setting, such a run stops as described above.

## What the judges are told, and single-source runs

**Missing answers are disclosed.** The Critic and Arbiter prompts begin their response section with `k of n delegates answered; m independent sources.`, then one line per slot that did not answer, giving only the failure kind (`timed out`, `empty` or `failed`). They never include a delegate name, a model name or an error body for a missing slot, so a partial panel cannot be mistaken for a full one.

**One independent source is not a panel.** When exactly one independent source answered, the result has `single_source: true`, the Critic is never called (there is nothing to compare), and the workspace's `single_source_mode` decides how the run ends:

- `return_answer`: no Arbiter. The delegate's answer is returned in `single_source_answer`, labelled as a single-source result. One call.
- `arbiter_single_source`: the Arbiter runs with a prompt that says only one source answered and asks it to *assess* the answer, not to synthesise or describe agreement. Two calls.

`single_source_mode` must be chosen explicitly whenever a workspace is saved (the API refuses a missing value). Workspaces created before this setting existed read as `return_answer`.

**Two settings, two different questions.**

| Setting | Question it answers | Default |
|---|---|---|
| `allow_single_source` | May a run start or proceed when the quorum asks for more sources than are available or answered? | `false` |
| `single_source_mode` | When only one source answered, does the run return the answer or have the Arbiter assess it? | none; must be chosen |

`single_source_mode` can never permit a below-quorum run: only `allow_single_source` does, and the quorum check runs before the mode is consulted. A workspace with a quorum of 1 is not below its quorum, so a single answer there is a single-source run but not an override.

**One label everywhere.** A single-source run carries one sentence, `single_source_label`, which the console shows verbatim, the saved result stores, and the Arbiter prompt quotes. For an explicitly permitted run it reads `SINGLE-SOURCE RUN, explicitly permitted by this workspace (allow_single_source). The configured quorum of N independent sources was NOT met. This is not a consensus.` For a quorum of 1 that was met it reads `Single source: only 1 independent source answered ...`. A single-source run has no Critic to retry, and a `return_answer` run has no Arbiter to retry; those endpoints answer HTTP 409.

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


## History, the database and upgrades

**History is bounded.** `GET /api/runs` and `GET /api/workspaces/{id}/runs` return summaries, not whole runs: id, the question (cut at 300 characters, with a flag), created time, status, retry-chain fields, delegate counts, `independent_source_count`, quorum, Critic and Arbiter status, single-source and insufficient-evidence flags, and cost totals. They never contain a prompt or an answer, so a list does not grow with their size. `limit` (default 50, at most 200) sets the page size, and `before` (a run id) returns the runs older than it, so a client pages with the last id it has seen; paging never repeats or skips a run, even while new runs arrive. Add `all_attempts=true` to include every retry attempt. The full run, with every prompt and answer, is `GET /api/runs/{id}`.

**Schema version and upgrades.** The database records the newest numbered migration step that has been applied (table `schema_version`; the current schema is version 3: original tables, the call ledger, retry lineage), and each stored result carries `schema_version` too (a result saved before versioning reads as null). On start, a database that is already current is not touched. Any existing file with content that needs upgrading is first copied to `<database>.bak-<schema>-<timestamp>` (for example `conclave.db.bak-0-20261113T101500Z`, where 0 means it had no version yet), using SQLite's online backup, and the copy is checked with `PRAGMA integrity_check`. If the copy cannot be made or does not verify, nothing is migrated and the start fails with the reason. A database written by a newer Conclave is refused unchanged. The version check, the backup and every step happen while holding SQLite's write lock, in a single transaction: two starts at once migrate once (the second waits, then finds the database current), and a step that fails rolls back all of them, leaving the file as it was. Each step is also idempotent. Backups are claimed atomically, so two never share a name, and a database in WAL mode is backed up with its pending changes. Keep the backup until you have used the new version for a while; it is a plain SQLite file you can open or copy back.

**Connections.** Every database connection is opened and closed within the operation that needs it.

## Choosing a Critic

A workspace must say whether it uses a Critic: `critic` is required when a workspace is saved or replaced, as a provider name or as an explicit `null` for none (HTTP 422 if it is left out). There is no default because the Critic's value has not been measured: `bench/judge/` is a benchmark that compares the Arbiter alone with the Critic then the Arbiter on real judge models, with a decision rule fixed in advance. It has been run to completion on two judge models (`qwen/qwen3.7-flash`, `deepseek/deepseek-chat-v3-0324` and `anthropic/claude-sonnet-4.6`; every set is "default off", the Critic arm between -1.3 and +1.3 points after the scorer was repaired), and is incomplete on a third (6 of 144 trials), so there is still no default. Workspaces saved before this rule are not changed. In the console the Critic field is a required choice between "No Critic" and "Use a Critic" with a provider name. The single-source mode follows the same rule.

## Retry chains

A retry (of a delegate, the Critic or the Arbiter) is saved as a new run, and the runs are linked. Each run has `parent_run_id` (the run it retried; none for a run that is not a retry) and `chain_root_id` (the first run of the chain; a run that is not a retry is its own root). A retry reuses the chain's seed, so the response labels and their order, and the markers in the prompts, stay the same across the chain. Runs saved before this change read as their own root. Every run is reachable from its root: `GET /api/runs/{id}/chain` lists the whole chain, oldest first.

Every attempt is stored, so history stays truthful, but `GET /api/runs` and `GET /api/workspaces/{id}/runs` list only the newest run of each chain by default (the console marks it "retry"); add `?all_attempts=true` for every attempt.

A new retry's row is created, as `running`, before any provider is called, and is marked `interrupted` if the retry is cancelled or fails, so what it spent stays attached to it. A retry that is refused before it starts (an unknown delegate, a run with no Critic) leaves nothing behind.

Only one retry runs at a time per chain: a second retry in a chain that already has one in progress gets HTTP 409 ("A retry is already running for this run's chain") instead of both spending and writing conflicting histories. Chains do not block each other. Retrying a delegate that already succeeded in the run is also refused with 409 unless you pass `?force=true`, so a successful answer is not paid for again by accident. The check looks at the run you retry from, because the retry builds on that run's panel (retrying from an older run in which the delegate had failed needs no force).

## The call ledger and cost

Cost used to be recomputed from the stage results that survived a run, so retries, fallbacks, HTTP-level retries, failed calls, timeouts and connectivity tests disappeared from it, and one number mixed estimate with fact. Conclave now keeps a call ledger: the `provider_calls` table holds **one row per HTTP request** a provider adapter makes, plus one row for each call a timeout or cancellation abandoned. Rows are written as calls end, so a cancelled or crashed run keeps what it already spent. The table is new; an older database simply gains it and nothing existing is rewritten.

A row records the run and retry chain it belongs to (`run_id` is null for connectivity tests), the stage (`delegate`, `critic`, `arbiter`, `connectivity_test`), the provider, the configured model and the model the provider reported, the attempt number, the outcome (`ok`, `http_error`, `transport_error`, `timeout`, `cancelled`), HTTP status, start time and latency, token counts and the raw usage, the prices in force at the time, and the three cost fields below. It never holds a prompt, a header or a key. Read it with `GET /api/runs/{id}/calls` (add `?chain=true` for the whole retry chain).

Three terms are kept apart and never mixed:

- **Estimated**: tokens x the price configured at the time (`input_cost_per_million`, `output_cost_per_million`; the prices are stored on the row, so a later price change cannot rewrite history). It is unknown, not zero, when usage is missing or a needed price is not configured.
- **Provider-reported**: an amount the provider or gateway states for that call. It is read only from where you tell Conclave to look, with `reported_cost_field` (a dotted path into the JSON reply, for example `usage.cost`) and/or `reported_cost_header`. Conclave never guesses where a cost is; with neither set, none is recorded. A value that is not a finite, non-negative number is ignored.
- **Billed**: what appears on the provider's invoice. Conclave never shows or claims it. Reconcile it by hand against the invoice.

Totals are per run (the calls that run made, in `result.cost`; `estimated_cost_usd` is the estimated total) and per retry chain (every call in every run of the chain, in `chain_cost` on a run). Each has the estimated total, the number of priced and unpriced calls, how many unpriced calls were possibly billed, and the provider-reported total with how many calls it covers. The console shows, for example, "Estimated $0.012 (2 calls unpriced). Provider-reported $0.012 for 5 of 7 calls.", and when nothing can be priced it says "Cost unknown", never $0.

`possibly_billed` is true for a call that may have been charged: a success, a timeout or cancellation, a transport failure after the request may have been accepted, or a 5xx. It is false for a refused connection and for a 4xx the provider rejected before generating anything.

Providers that make no HTTP request (the built-in demo providers) get one row per call written from the result, with whatever cost the result carried.

## Output length, temperature and prompt size

Three optional settings per provider keep cost and behaviour in hand. Each is used only when set; leaving it out keeps the provider's own default and sends nothing extra.

| key | effect |
| --- | --- |
| `max_output_tokens` | sent as `max_tokens`, bounding the length of every answer from this provider |
| `temperature` | sent as `temperature` (0 to 2; 0 is sent when set to 0) |
| `max_prompt_chars` | a local check, not sent to the provider: a prompt longer than this (system prompt included) is not sent at all |

A Critic or Arbiter prompt grows with the number and length of the delegate answers, so it can exceed a model's context window. With `max_prompt_chars` set to a safe figure for that model, an oversized prompt fails the stage at once with error kind `prompt_too_large` (no request, no cost) and the next configured fallback is tried; the failed primary is recorded in `prior_attempts`. If every provider for the stage is too small, the stage fails with that kind and a message saying the prompt was not sent. A provider with `max_prompt_chars` set never receives a longer prompt. Characters are a rough proxy for tokens (about four characters per English token); choose the limit with margin.

## Error kinds and the retry policy

Every failed provider call is classified, and the kind is saved as `error_kind` on the result (and shown in the console as, for example, `failed (auth)`):

| kind | what it is | retried |
| --- | --- | --- |
| `auth` | HTTP 401 or 403 | no |
| `quota` | a 429 whose body contains `insufficient_quota`, `quota` or `billing`, or whose `Retry-After` is over 60 seconds (unless the body says the provider is *temporarily rate-limited* or to *retry shortly*, as OpenRouter does when a shared upstream pool is busy: that is a rate limit) | no |
| `rate_limit` | any other 429 | yes |
| `capacity` | HTTP 502, 503 or 504 | yes |
| `bad_request` | any other 4xx | no |
| `server_error` | any other 5xx (for example 500) | no |
| `transport` | the request failed on the way | only a refused or unreachable connection |
| `malformed` | the reply was not a usable chat completion | no |
| `empty_response` | the reply held no text | no |
| `timeout` | the stage timeout expired | no |
| `prompt_too_large` | the prompt is over the provider's `max_prompt_chars`; nothing was sent | no |

Only `rate_limit`, `capacity` and a refused connection are ever sent twice. A quota or a bad key fails at once instead of spending retries (and, for a quota, time). A refused connection never reached the provider, so a repeat cannot double-bill; any other transport failure may have been accepted, so it is not replayed.

The defaults are two retries with exponential backoff starting at one second. Numeric and HTTP-date `Retry-After` values are supported with a ten-second cap on the wait between retries; past dates become zero delay, and invalid or non-finite values use exponential backoff. The cap can cause a retry earlier than a provider's requested wait, so long rate limits can still exhaust retries (a wait over 60 seconds is treated as a quota and not retried at all).

Completed failures retain the number of HTTP attempts in saved results and provider connectivity tests, including transport or malformed-response failures after a transient retry. Timeout results still use the existing default attempt count; they do not report an exact count of interrupted HTTP attempts. Error text and kinds are never put in a Critic or Arbiter prompt.

When a Critic or Arbiter fallback answers (or also fails), the final result carries `prior_attempts`: for each earlier provider that failed, its name, status, error kind, latency and attempt count, oldest first. The fallback no longer erases the primary's failure.

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


## Optional run controls (all off by default)

These are fields on `POST /api/deliberate` (and, where noted, on `POST /api/workspaces/{id}/deliberate`). Each is saved with the run's request, so retries keep it.

- **`max_estimated_cost_usd`: a per-run cost ceiling.** It is checked against *estimated* cost (tokens x the prices you configured), not against what a provider invoices. Before every provider call Conclave computes a deliberately pessimistic bound for that call, `(transient_max_retries + 1) x (prompt bytes x input price + max_output_tokens x output price)`, counting one token per prompt byte and including the provider's system prompt. The call is refused unless spend so far, plus the bounds of calls still in flight, plus this bound, fits under the ceiling. So concurrent delegates cannot overshoot it together. A refused call is recorded as a failed result with `error_kind` `cost_ceiling` (never silently dropped) and the run's `stopped_reason` is `cost_ceiling`; answers already received are kept. The ceiling **fails closed**: a provider without both prices, `max_output_tokens` and a retry limit has an unknowable cost, so the API refuses the whole run (422, naming the providers) and the orchestrator refuses its calls; a possibly billed call with no usable usage counts as the ceiling being used up. A retry is its own run with its own ceiling. The ledger, not the saved result, is the authoritative record of spend. Pricing mistakes in your configuration are not detected.
- **`shared_stage_deadline`.** Off: each fallback provider of the Critic or Arbiter gets the stage's full timeout, so a stage can take timeout x (1 + fallbacks). On: the primary and its fallbacks share one budget of that stage's timeout; each attempt gets what is left, and no further fallback starts once it is spent (the last failure is returned with its earlier attempts).
- **`reserve_delegates` (workspace runs: `use_reserves`).** Providers held back for one replacement wave. If the first panel leaves the quorum unmet, at most as many reserves as independent sources are missing are called once, together; a reserve that is the same configured model as an answer already in hand is skipped because it could not add a source. Every answer already received is kept, nothing is re-run, reserve answers are marked `reserve: true`, and the quorum is judged as for any panel; if it is still unmet the run stops with the usual explicit quorum report. Reserves are not used to reach a quorum that is unreachable before the run starts. With `use_reserves`, the reserves are the workspace's delegates not picked for the run.
- **Background mode: `?background=true`** (both deliberate endpoints). The request returns `202` with `{"run_id", "status": "running"}` at once. The run saves each stage as it finishes, so delegate answers can be read from `GET /api/runs/{id}` as soon as the panel stage is saved while the Critic and Arbiter still run; poll the same URL until `status` is `complete` (or `interrupted`). `POST /api/runs/{id}/cancel` stops it and keeps what was already paid for (`409` if it is not running here). This works in one server process only: the run lives in that process, and a restart marks an unfinished run `interrupted`. The web console does not use it yet.

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

## Local access (`CONCLAVE_ALLOWED_HOSTS`)

Conclave has no login and must stay on loopback. By default the server only answers requests whose `Host` header is `127.0.0.1`, `localhost` or `[::1]` (any port). Requests other than `GET` and `HEAD` are also refused with HTTP 403 when they carry an `Origin` header that differs from `Host`; browser pages on other sites cannot trigger provider calls.

To reach the server under another name, list it, comma-separated:

```text
CONCLAVE_ALLOWED_HOSTS=conclave.lan
```

Only do this on a network you trust. `extra_headers` in `conclave.json` can hold secrets, and prompts and responses are stored in plain text.

### Secrets in stored errors

Provider error bodies and transport errors are saved with the run, and some providers echo the credential they rejected. Before an error is stored or returned, Conclave replaces these values with `[redacted]`: the provider's API key (always, whatever its length), and every `extra_headers` value whose header name contains `auth`, `key`, `token`, `secret`, `cookie`, `password` or `credential`, or whose value is at least 8 characters. A short value under a harmless-looking header name (for example `X-Feature: true`) is left alone, because redacting it would garble ordinary text; put anything secret under a header name that says so, or make it at least 8 characters. Model *responses* are never altered: they are stored exactly as received.

### Structured Arbiter output

Disagreement and uncertainty are checked, not just requested. The Arbiter is asked to write exactly four headings, each alone on its own line, once, in this order: `## Common ground`, `## Disagreements`, `## Uncertainty`, `## Synthesis`. Each point under the first three ends with the labels of the responses it rests on, such as `[A]` or `[A, C]`; `None.` is allowed under Disagreements; the Synthesis begins "Insufficient evidence" when the responses do not support an answer.

The reading is strict and applies only to the Arbiter's own answer (never a delegate's or the Critic's). A heading counts only when a whole line equals it (trailing spaces are fine). A missing, repeated or out-of-order heading, a fifth heading at level 1 or 2 (deeper `###` headings are ordinary text), or any text before the first heading, gives `format_ok: false` with fixed-wording `problems`, no sections, and a console notice; the raw answer is shown as written. Otherwise the result stores `arbiter_structure`: the four `sections`, the `points` in each with their `citations`, `unknown_citations` (labels cited that were not shown to the Arbiter in this run) and `uncited_points` (points under the first three sections that cite nothing and are not "None."). Uncited points and unknown citations are shown as notices; they do not make the format fail. The raw answer in `arbiter.raw_response` is never altered, and the console shows the sections separately with the raw answer one click away.

A single-source assessment is written under a different instruction and is not read as sections (`arbiter_structure` is empty). Runs saved before this change have no structure and still load. When the structured Synthesis begins "Insufficient evidence", `insufficient_evidence` is set (see below).

### Each delegate's own position

Dissent should not depend on the Arbiter choosing to report it. Every delegate is asked to end its answer with two lines, `Conclusion: <one sentence>` and `Confidence: high | medium | low | insufficient evidence`. Conclave reads the last occurrence of each line from that delegate's own raw answer (markdown decoration and capitals are tolerated; the line must start with the key) and stores one row per delegate in `positions`: label, delegate, source number, conclusion and confidence. A missing line is shown as "not stated"; the confidence is shown as the delegate wrote it (cut at 120 characters), with a note when it is not one of the four levels. The console shows these rows in a table above the synthesis, escaped and verbatim, whatever the Arbiter wrote. A conclusion longer than 600 characters is cut and marked in the table (the raw answer is never changed).

Positions are display data. They never change source counts, quorum or any decision (the two closing lines are removed before answers are compared for near-duplication), they are never put in a prompt, and a delegate's text can only fill its own row. `insufficient_evidence` is true when every independent source says "insufficient evidence" (all its members, for a merged source), or when the Arbiter's `## Synthesis` section begins "Insufficient evidence" (read only from a well-formed four-section answer). The console then says so above the table. Runs saved before this change have no rows.

### Blind judging

The Critic and Arbiter see each delegate answer only as `Response A`, `Response B` and so on. Their prompts carry no provider name, model name (configured or provider-reported), latency, token count, cost, attempt count or error text, so a hostile or merely vain model name cannot reach a judge and a judge cannot weight by reputation. Failed slots are described by position and kind only (`Slot 2 did not answer: failed.`).

The labels are a permutation of the successful answers derived from the run seed, so the order differs between runs and never follows the workspace order. Every retry in a chain reuses the stored seed, so the order is the same; the permutation covers every delegate in the request, so a delegate keeps its label whoever else answers (a failed delegate leaves its letter unused, and a successful retry fills it without relabelling anyone). Source groups are given by label (`Responses A and C come from the same underlying source...`).

The label-to-delegate mapping is stored on the result as `label_map`, and the console shows next to each delegate which response label the judges saw. When the Critic or Arbiter is the same source as a delegate (the same configured endpoint and model, or the same reported model), the result records those labels as `judge_overlaps` and the console shows a notice. The judge is not told which response is its own, since that would undo the blinding.

Limit: an answer can still identify its author ("As an OpenAI model..."). Raw text is never edited, so blinding hides the configuration, not the writing.
