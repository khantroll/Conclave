# Conclave

**Multi-model deliberation and synthesis for people who are tired of being the message bus between AIs.**

Conclave is a personal, single-user, local AI orchestration console. A user asks one question; Conclave sends it to several language models in parallel, keeps every raw answer, counts which of those answers are genuinely independent, and has an optional Critic and an Arbiter judge them without knowing which model wrote which. The result shows each model's own position, the agreement and disagreement, what is missing or uncertain, and what it all cost.

The goal is not to create an autonomous swarm. Conclave is intentionally a **deterministic, inspectable pipeline**, and every model output is treated as untrusted data.

## Why Conclave?

Using several AI systems can produce better perspective, but the human often ends up doing the tedious work:

1. Ask one model.
2. Carry the useful context to another model.
3. Reword the question for that model.
4. Repeat.
5. Compare several long answers.
6. Decide which claims conflict.
7. Carry the responses back to a preferred model for synthesis.

Conclave exists to automate that plumbing without hiding the underlying reasoning products from the user. It also tries not to flatter itself: three answers that are copies of one answer are one answer, and agreement between models is not evidence that they are right.

## Core workflow

```text
User question
    |
    v
Request analyzer (deterministic) ---> delegate choice within the workspace
    |
    v
Quorum check: enough INDEPENDENT sources? (before any provider is called)
    |
    +----> Delegate A  \
    +----> Delegate B   > concurrent, each with its own timeout; failures are data
    +----> Delegate C  /
    |
    v
Source counting: same configuration, same reported model, unresolved router alias,
or near-identical text merge into one source
    |
    v
Critic (optional)  ->  Arbiter      both see "Response A, B, C" in a seeded order:
    |                                no provider, model, timing or cost
    v
Final answer in four checked sections, each delegate's own position, the raw answers,
the exact prompts, and a call ledger of what every request cost
```

## Design principles

- **Visible deliberation.** Raw model responses and exact prompts stay available and untouched.
- **Evidence over majority vote.** Three models agreeing does not make a claim true; judges are told so every time.
- **Independence is counted, not assumed.** Quorum is measured in independent sources, never in raw answers.
- **Partial failure is normal, and disclosed.** One failed provider must not kill a useful run, and the judges are told how many answered.
- **Model output is data, never authority.** It is escaped, bounded, wrapped in per-run markers, never parsed to decide what Conclave does, and tested against a corpus of hostile text.
- **Deterministic before autonomous.** A clear pipeline, not agents endlessly talking to one another.
- **Provider independence.** OpenAI-compatible endpoints, gateways and local models are all first-class.
- **Cost honesty.** Estimated and provider-reported cost are kept apart, and unknown is never shown as $0.

## What exists today

Conclave is a FastAPI service with a vanilla HTML/JS console and a SQLite store. It runs one user, on loopback.

**Running a panel**
- A provider-neutral delegate abstraction and a generic OpenAI-compatible adapter (direct APIs, OpenRouter, LiteLLM Proxy, LM Studio and similar).
- Concurrent delegates with independent timeouts; partial success; isolated retry of one delegate, the Critic or the Arbiter without rerunning what already succeeded; ordered Critic and Arbiter fallbacks.
- Workspaces with default delegates, roles, Critic, Arbiter, fallbacks and project context, plus deterministic request analysis that can pick a smaller panel.
- Optional per-provider `max_output_tokens`, `temperature` and `max_prompt_chars` (a prompt over the limit is never sent).

**Independence and honesty about absence**
- Quorum counts independent sources: same configured endpoint and model, same reported model, an unresolved router alias, or near-identical text all merge. A run that cannot reach its quorum of independent sources stops before any call, with a structured error. A single-source run happens only when a workspace explicitly allows it and is labelled everywhere.
- Judges are told "k of n delegates answered; m independent sources", never the reason a slot failed, and always that agreement is not evidence of correctness.

**Judging**
- Blind judging: answers are `Response A`, `B`, ... in an order permuted by the run seed and stable across retries; the label-to-delegate mapping is stored and shown. If a judge is the same source as a delegate, the result records it (the judge is not told).
- Each delegate's own `Conclusion:` and `Confidence:` lines are shown in a positions table above the synthesis whatever the Arbiter wrote, and a run where every source says "insufficient evidence" is flagged.
- The Arbiter must write four headings (common ground, disagreements, uncertainty, synthesis) with points citing response labels. The structure is parsed strictly; anything else is shown raw with a notice, and citations to responses that do not exist are listed.
- There is no Critic default: a workspace must state whether it uses one (see below).

**Failures and cost**
- Provider errors are classified (`auth`, `quota`, `rate_limit`, `capacity`, `bad_request`, `server_error`, `transport`, `malformed`, `empty_response`, `timeout`, `prompt_too_large`). Only rate limits, capacity errors and refused connections are retried. A fallback keeps the failed primary's trail.
- A call ledger records every provider request. Run and retry-chain totals keep **estimated** cost (tokens times the configured price) apart from **provider-reported** cost (read only from a field or header you name in the provider's config), and never show an unknown amount as zero.

**History and storage**
- Every retry is a linked run in a chain; history lists the newest of each chain and pages 50 summaries at a time; one retry runs at a time per chain.
- The database has a schema version and numbered migrations, and any existing file is backed up and verified before it is upgraded.

**Safety and testing**
- Loopback-only guard, secret redaction in stored provider errors, per-run marker tokens, bounded and escaped model text, and a console that renders model text as inert text.
- An adversarial suite (about 50 hostile texts in 11 classes through every route model text can take), a mock benchmark of thirteen invariants, unit and API tests, and CI. The Python tests and a Node test of the console's rendering all run in CI.

**Not built yet**: native provider adapters, a spending ceiling, a shared stage deadline, live progress while a run is going, a measured Critic default, and any measurement of whether a panel beats a single model. See [Status](#status) and [Limitations](#limitations).

## The Critic has no default

Whether adding a Critic stage improves the Arbiter's answer is unmeasured, so Conclave does not choose for you. Saving a workspace requires an explicit `critic`: a provider name, or `null` for no Critic (the API returns 422 otherwise, and the console form requires a choice). Existing workspaces keep working unchanged. [`bench/judge/`](bench/judge/README.md) holds a paid benchmark (24 cases, real judge models, two arms, a decision rule fixed in advance) that will settle it. Screening runs on two judge models from different families (`qwen/qwen3.7-flash` and `deepseek/deepseek-chat-v3-0324`, 144 of 144 trials each, run twice: under the original Arbiter prompt, Critic arm -1.4 and +0.7 points, and under the current prompt, +2.1 and +0.0) are all "default off" by the fixed rule: the Critic did not help on these cases. They are small, inexpensive models and a screening result, so Conclave still has no default and the workspace must choose. A third judge (groq, free tier) has 6 of 144 trials and no decision. See [`bench/judge/RESULTS.md`](bench/judge/RESULTS.md).

## Development

Requires Python 3.11+ (CI runs on 3.11 and 3.14).

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
node --test web/render.test.mjs
uvicorn conclave.api:app --reload
```

Then open the Conclave web console at `http://127.0.0.1:8000/` or the FastAPI docs at `http://127.0.0.1:8000/docs`.

The built-in `demo-*` providers exist only to exercise orchestration before real provider configuration is added. See [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for provider setup and every setting, [docs/MVP.md](docs/MVP.md) for the first-release definition, [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the pieces fit, and [docs/MANUAL_TEST.md](docs/MANUAL_TEST.md) for the human test procedure.

### Running safely

- **Loopback only.** Conclave has no login. By default it answers only requests whose `Host` is `127.0.0.1`, `localhost` or `[::1]`, and refuses state-changing requests whose `Origin` differs from its `Host`, so a web page open in your browser cannot make it spend provider calls. If you deliberately reach it under another name, list that host in `CONCLAVE_ALLOWED_HOSTS` (comma-separated); that widens who can use it, so do it only on a network you trust.
- **What is stored in plain text**, in `conclave.db` and the `run_logs/` directory: every question, every prompt, every model response, error messages, run results and the call ledger. Treat those files like the conversations they contain. Provider error bodies are redacted of your API key and of credential-like `extra_headers` values before they are stored; model answers are stored exactly as received.
- **Where keys live.** API keys are read from environment variables (or a local `.env`) named in `conclave.json` by `api_key_env`, and are never written to the database. A secret placed in `extra_headers` in `conclave.json` is a secret in that file. Keep `.env`, `conclave.json`, `conclave.db` and `run_logs/` out of version control.
- **Back up before you upgrade.** On start, Conclave copies an existing database that needs upgrading to `conclave.db.bak-<schema>-<timestamp>` and verifies the copy before it changes anything, but a copy you made yourself before pulling a new version is still the safest.

### Untrusted model output

Everything a model returns is treated as data. It is wrapped in per-run markers before a later model sees it, with marker sequences and control or bidirectional characters escaped and each response capped in length; it is never parsed to decide what Conclave does (the Arbiter's answer is read for its sections and nothing else, and a delegate's closing lines for its own table row and nothing else); and the console shows it as escaped text. An adversarial suite (`tests/adversarial/` and `web/render.test.mjs`, about 50 hostile texts in 11 classes run through every route model text can take, including retries and fallback judges) checks that none of it changes which providers are called, how many calls are made, any count, status or flag, or what is saved, that it stays inside its markers, that a fake API key never reaches a prompt, stored run, run log or response, and that the console renders it inertly.

What this shows is that Conclave grants model text **no authority**. It does **not** show that a real judge model ignores persuasion: a judge may still be swayed by a convincing lie placed inside its own marked block. That is a property of the model, not of this code, and it is measured separately by the judge benchmark, which has so far been run on two small judge models (see above). Add a hostile text by appending an entry to `tests/adversarial/corpus.json`; no code change is needed.

**Blind judging.** The Critic and Arbiter see answers as `Response A`, `Response B`... in an order permuted by the run seed, with no provider name, model name, latency, cost or error text. The mapping is saved and shown in the console, and if a judge is the same source as a delegate the console says so (`judge_overlaps`) without telling the judge. Limitation: answer text can still name its author, and raw text is never edited, so this hides configuration, not writing style.

### The mock benchmark

`tests/benchmark/` holds a fixed, free benchmark that runs with the rest of the suite (about six seconds). `fixtures.json` scripts 33 panels with fake providers (agreement, dissent, partial failure, empty answers, single sources, duplicate sources by configuration, reported model, router alias and copied text, malformed and insufficient-evidence Arbiter answers, fallbacks and very long answers) plus 5 scripted HTTP failure sequences, and `test_invariants.py` checks thirteen invariants against them: dissent reaches the Arbiter inside its own block; a failure is disclosed as "k of n"; a single source is labelled and the Critic skipped; an empty answer is not a success; duplicate sources collapse and different models stay separate; judging is blind and the order varies by seed but is stable across retries; call counts and prompt sizes match; nothing paid for is lost when a run is cancelled at the panel, Critic or Arbiter stage; ledger totals equal the sum of the rows and unpriced calls are never $0; a position is shown for every delegate whatever the Arbiter wrote; structured output parses or says it did not; prompts rebuilt from a stored run are byte-identical; and no delegate prompt contains any other model's output. Every fixture passes, with no expected failures. It measures that the pipeline keeps these properties with scripted providers. It does not measure whether a real model judges well.

## Architecture

```text
Console (web/)  ----  FastAPI (api.py)  ----  SQLite (store.py: workspaces, runs, call ledger)
                          |
                   Orchestrator (orchestrator.py)
        +-----------------+------------------------------+
   quorum.py          sources.py                    prompts.py
   (independent       (which answers are one        (blind labels, markers,
    sources,           source; near-duplicates;      escaping, caps, the
    delegate plan)     families)                     "k of n" note)
        |                                                 |
   providers/  (OpenAI-compatible adapter, fake, unavailable)      positions.py, synthesis.py
   error kinds, retries, ledger rows                  (a delegate's own position; the Arbiter's four sections)
```

Conclave owns orchestration, failure isolation, source counting, blinding, the Critic and Arbiter pipeline, cost accounting and persistence, even when a gateway such as LiteLLM or OpenRouter handles provider-specific API differences. A configured provider can declare capability tags (`general`, `reasoning`, `critical`, `research`, `code`, `creative`, `fast`, `privacy`) and a priority; with automatic selection on, Conclave analyzes the question, picks a panel size and ranks only that workspace's delegates, deterministically and without another model call.

## Failure behavior

A central requirement is graceful degradation, and honesty about it.

```text
OpenAI   OK   8.2s
Claude   FAIL timeout
Gemini   OK   5.9s

2 of 3 delegates answered; 2 independent sources.

[Retry Claude]      (a new run in the same chain; successful delegates are not rerun)
```

A failed provider never fails the session, and the Critic and Arbiter are told exactly that two of three answered, so a partial panel cannot be mistaken for a full one. If too few independent sources answered to meet the quorum, no Critic or Arbiter runs and the run says so.

## Vocabulary

- **Delegate**: a participating model asked for an independent answer.
- **Independent source**: a group of answers that count as one, because they come from the same configured model, the same reported model, an unresolved router alias, or near-identical text.
- **Critic**: examines the answers for unsupported claims, contradictions, assumptions and blind spots. Optional.
- **Arbiter**: produces the final synthesis in four checked sections while preserving meaningful disagreement.
- **Position**: a delegate's own conclusion and confidence, read from its own answer.
- **Workspace**: persistent project context, preferences, constraints and model configuration.
- **Chain**: a run and its retries.

## Status

**Pre-alpha. Not released, and no version has been tagged.**

The orchestration, source counting, blinding, structured output, ledger, retry chains and storage described above are implemented and covered by the tests and benchmarks in this repository. What has **not** happened:

- **No real-provider run since the earlier changes.** The last live run against real providers was on 2026-10-09 (Groq and OpenRouter answering; Gemini and Mistral not), before most of the work above. A real-provider acceptance run on at least three providers from two model families is still to be done (`docs/TEST_LOG.md` records the earlier runs and what is outstanding).
- **The Critic's value is unmeasured**, and so is whether a panel beats a single strong model. Both need paid benchmarks that have not been run.
- Costs have never been reconciled against a provider's own usage or billing page.

## Limitations

- **Agreement is not evidence of correctness.** Several models can be wrong in the same way. Conclave tells the judges and shows you the same sentence for that reason.
- **Similarity detection catches copies, not shared bias.** Near-duplicate and same-model checks merge copies of one answer. They cannot detect correlated errors from shared training data or common sources, and no label Conclave shows claims independent verification.
- **Answer text can reveal its author** ("As an OpenAI model...") even though judges are blind to names. Raw text is never edited, so blinding hides configuration, not writing style.
- **The injection suite proves no authority, not immunity.** It shows model text cannot change what Conclave does; it does not show a judge model cannot be persuaded by a convincing lie. On the two judge models measured so far, no injection text was ever asserted in the synthesis (qwen 24 of 24 checks with and without a Critic; deepseek quoted the target while rejecting it in 4 of 48 trials, which the strict check counts as failures). That is four injection texts and two small models, not a general rate.
- **Costs are estimates or provider-reported, never billed.** Estimated cost is tokens times the price you configured; provider-reported cost is what a provider states, where you told Conclave to look. Conclave never shows an invoice amount, and an unknown cost is shown as unknown.
- **Whether a panel is better than one model has not been measured.** If you are deciding whether to rely on a panel, that is the open question.
- **Single user, no authentication.** It is built to run on your own machine.

## Research notes and roadmap

- [November 13, 2026 research roadmap](docs/RESEARCH_ROADMAP_2026-11-13.md): coordination fixtures, contribution-aware Critic evaluation, bounded harness changes, and verified newsletter leads on evaluation, routing, and supervised tools. Includes evidence limits and measurable proposals; no implementation is claimed.
- [October 23, 2026 research roadmap](docs/RESEARCH_ROADMAP_2026-10-23.md): proposed experiments for runtime-enforced delegate scope, evidence-backed Critic verification, and a capped shared findings buffer, with sources, limitations, prerequisites, and measurable acceptance targets. These are proposals, not completed implementation or an expansion of MVP execution authority.
- [Release evidence](docs/RELEASE_EVIDENCE.md): what is implemented, verified, partial, blocked and deferred, with the evidence for each.
- [Development status and next steps](docs/DEVELOPMENT_NEXT_STEPS.md): what is done, what remains, and the decisions that are still open.

## License

No license has been selected yet.
