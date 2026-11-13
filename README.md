# Conclave

**Multi-model deliberation and synthesis for people who are tired of being the message bus between AIs.**

Conclave is a personal AI orchestration console. A user asks one question; Conclave analyzes the request, prepares model-appropriate prompts, dispatches them to multiple language models, preserves each raw response, identifies agreement and disagreement, and produces a final synthesis through a configurable authority model.

The goal is not to create an autonomous swarm. Conclave is intentionally designed as a **deterministic, inspectable pipeline**.

## Why Conclave?

Using several AI systems can produce better perspective, but the human often ends up doing the tedious work:

1. Ask one model.
2. Carry the useful context to another model.
3. Reword the question for that model.
4. Repeat.
5. Compare several long answers.
6. Decide which claims conflict.
7. Carry the responses back to a preferred model for synthesis.

Conclave exists to automate that plumbing without hiding the underlying reasoning products from the user.

## Core workflow

```text
User question
    |
    v
Request Analyzer
    |
    v
Prompt Router
    |
    +----> Delegate A
    +----> Delegate B
    +----> Delegate C
    |
    v
Response Collector
    |
    v
Critic / Disagreement Pass
    |
    v
Arbiter / Synthesizer
    |
    v
Final answer + raw responses + disagreements
```

## Design principles

- **Visible deliberation.** Raw model responses remain available.
- **Evidence over majority vote.** Three models agreeing does not make a claim true.
- **Partial failure is normal.** One failed provider must not kill an otherwise useful run.
- **Model-specific prompting.** Different models may receive different roles and wording when appropriate.
- **Project context matters.** Workspaces should eventually carry persistent context and constraints.
- **Deterministic before autonomous.** Start with a clear pipeline rather than agents endlessly talking to one another.
- **Provider independence.** Avoid coupling the application to one model vendor.
- **Cost awareness.** The system should know when one model is enough and when a panel is justified.
- **Local models are first-class.** OpenAI-compatible local endpoints should be supported alongside hosted providers.

## Proposed MVP

The first useful version should stay deliberately small:

- Single-user web interface
- Workspaces/projects
- One question input
- Query complexity classification
- Provider/model selection
- Parallel model calls
- Per-provider timeout and retry
- Partial-success handling
- Raw response viewer
- Provider/result normalization while preserving raw responses and exact prompts
- Critic/disagreement pass
- Configurable synthesis/authority model
- Basic token, latency, and cost accounting

See [docs/MVP.md](docs/MVP.md) for the bounded first-release definition, [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for current design notes, [docs/CONFIGURATION.md](docs/CONFIGURATION.md) for provider setup, and [docs/MANUAL_TEST.md](docs/MANUAL_TEST.md) for the staged human-test checklist.

### Explicitly not MVP

- Free-form autonomous agent conversations
- Endless self-reflection loops
- Automatic tool execution on external systems
- Complex RAG infrastructure
- Team/multi-tenant administration
- Mobile clients
- A marketplace of agent personalities

## Current implementation

The current pre-alpha contains:

- a FastAPI service
- provider-neutral delegate abstraction
- a generic OpenAI-compatible adapter for direct endpoints, OpenRouter, LiteLLM Proxy, LM Studio, and similar gateways
- concurrent panel execution with independent per-delegate timeouts
- partial-success handling
- a dedicated **Critic → Arbiter** pipeline
- deterministic role/context prompt construction
- SQLite-backed persistent workspaces with default delegates, roles, Critic, Arbiter, and project context
- persisted workspace deliberation history with raw delegate/Critic/Arbiter results
- saved request snapshots so old runs can be reproduced safely
- exact Delegate/Critic/Arbiter prompt preservation and inspection
- isolated retry of one Delegate without rerunning successful Delegates
- isolated Critic and Arbiter retries without rerunning the Delegate panel
- deterministic request-complexity analysis that recommends panel size and desired capabilities
- capability-aware automatic Delegate selection within a workspace
- provider capability/priority metadata for role-aware routing
- provider discovery, explicit connection testing, model/token metadata, latency, and optional cost estimation
- workspace create/edit/delete with preserved detached run history
- JSON export of saved runs for debugging/review
- a first usable browser console for workspaces, questions, history, results, prompt inspection, and retries
- deterministic fake providers for testing
- API, persistence, prompt, provider, analyzer, and orchestration tests
- GitHub Actions CI

Automatic Delegate selection, workspace editing, connectivity tests, and optional cost estimation are now available. Native provider adapters, deeper source/citation normalization, and richer long-term provider health scoring remain future work.

## Development

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
uvicorn conclave.api:app --reload
```

Then open the Conclave web console at `http://127.0.0.1:8000/` or the FastAPI docs at `http://127.0.0.1:8000/docs`.

The built-in `demo-*` providers exist only to exercise orchestration before real provider configuration is added.

### The Critic has no default

Whether adding a Critic stage improves the Arbiter's answer is unmeasured, so Conclave does not choose for you. Saving a workspace requires an explicit `critic`: a provider name, or `null` for no Critic (the API returns 422 otherwise, and the console form requires a choice). Existing workspaces keep working unchanged. `bench/judge/` holds a paid benchmark (24 cases, real judge models, two arms, a decision rule fixed in advance) that will settle it; it has **not** been run yet, so there is still no default. See `bench/judge/RESULTS.md`.

### The mock benchmark

`tests/benchmark/` holds a fixed, free benchmark that runs with the rest of the suite (about five seconds). `fixtures.json` scripts 32 panels with fake providers (agreement, dissent, partial failure, empty answers, single sources, duplicate sources by configuration, reported model, router alias and copied text, malformed and insufficient-evidence Arbiter answers, fallbacks and very long answers) plus 5 scripted HTTP failure sequences, and `test_invariants.py` checks thirteen invariants against them: dissent reaches the Arbiter inside its own block; a failure is disclosed as "k of n"; a single source is labelled and the Critic skipped; an empty answer is not a success; duplicate sources collapse and different models stay separate; judging is blind and the order varies by seed but is stable across retries; call counts and prompt sizes match; nothing paid for is lost when a run is cancelled at the panel, Critic or Arbiter stage; ledger totals equal the sum of the rows and unpriced calls are never $0; a position is shown for every delegate whatever the Arbiter wrote; structured output parses or says it did not; prompts rebuilt from a stored run are byte-identical; and no delegate prompt contains any other model's output. Every fixture passes, with no expected failures. It measures that the pipeline keeps these properties with scripted providers. It does not measure whether a real model judges well; that is a separate, paid benchmark (roadmap P1-13).

### Running safely

Conclave has **no login**. Keep the server on loopback (`127.0.0.1`, the uvicorn default) and do not publish its port. Anyone who can reach it can spend your provider credit and read your stored prompts and responses, which are kept in plain text in the SQLite database and `run_logs/`.

The server refuses requests whose `Host` is not `127.0.0.1`, `localhost` or `[::1]`, and refuses any request other than `GET` and `HEAD` whose `Origin` differs from its `Host`, so a web page open in your browser cannot make it spend provider calls. If you deliberately reach it under another name, list that host in `CONCLAVE_ALLOWED_HOSTS` (comma-separated); that widens who can use it, so only do it on a network you trust.

### Untrusted model output

Everything a model returns is treated as data. It is wrapped in per-run markers before a later model sees it, with marker sequences and control or bidirectional characters escaped and each response capped in length; it is never parsed to decide what Conclave does; and the console shows it as escaped text. An adversarial suite (`tests/adversarial/` and `web/render.test.mjs`, about 50 hostile texts in 11 classes run through every route model text can take, including retries and fallback judges) checks that none of it changes which providers are called, how many calls are made, any count, status or flag, or what is saved, that it stays inside its markers, that a fake API key never reaches a prompt, stored run, run log or response, and that the console renders it inertly.

What this shows is that Conclave grants model text **no authority**. It does **not** show that a real judge model ignores persuasion: a judge may still be swayed by a convincing lie placed inside its own marked block. That is a property of the model, not of this code, and it is measured separately (roadmap item P1-13). Add a hostile text by appending an entry to `tests/adversarial/corpus.json`; no code change is needed.

**Blind judging.** The Critic and Arbiter see answers as `Response A`, `Response B`... in an order permuted by the run seed, with no provider name, model name, latency, cost or error text. The mapping is saved and shown in the console, and if a judge is the same source as a delegate the console says so (`judge_overlaps`) without telling the judge. Limitation: answer text can still name its author, and raw text is never edited, so this hides configuration, not writing style.

## Likely architecture

The current direction is intentionally provisional.

```text
Frontend
  Web UI
    |
Backend
  Request Analyzer
  Prompt Builder
  Orchestrator
  Response Normalizer
  Critic
  Synthesizer
    |
Provider Gateway
  LiteLLM (candidate)
    |
  OpenAI
  Anthropic
  Gemini
  OpenAI-compatible/local models
```

Potential implementation stack:

- **Backend:** Python + FastAPI
- **Frontend:** lightweight vanilla HTML/CSS/JS for the pre-alpha; a framework can be introduced later if the UI outgrows it
- **Storage:** SQLite
- **Provider gateway:** optional; LiteLLM/OpenRouter can sit behind Conclave's OpenAI-compatible adapter
- **Local providers:** LM Studio/Ollama-style OpenAI-compatible endpoints

Conclave intentionally owns orchestration, failure isolation, Critic/Arbiter behavior, and persistence even when a gateway handles provider-specific API differences.


### Capability-aware routing

Configured providers can declare capability tags such as `general`, `reasoning`, `critical`, `research`, `code`, `creative`, `fast`, or `privacy`, plus a numeric priority. A workspace may enable automatic Delegate selection; Conclave then analyzes the question, chooses an appropriate panel size, and ranks only that workspace's allowed Delegates against the inferred capabilities. The selection remains deterministic and inspectable rather than hidden behind another model call.

## Failure behavior

A central requirement is graceful degradation.

For example:

```text
OpenAI   OK   8.2s
Claude   FAIL timeout
Gemini   OK   5.9s

2 of 3 delegates completed.

[Continue with available responses]
[Retry Claude]
```

Conclave should not turn a single provider failure into a failed session.

## Vocabulary

- **Router** — analyzes the user's request and decides how it should be dispatched.
- **Delegate** — a participating model asked to provide an independent response.
- **Critic** — examines responses for unsupported claims, contradictions, assumptions, and blind spots.
- **Arbiter** — produces the final synthesis while preserving meaningful disagreement.
- **Workspace** — persistent project context, preferences, constraints, and model configuration.

## Status

**Pre-alpha / real-provider MVP pipeline validated.**

The deterministic orchestration path, persistence, routing, failure isolation, retries, cost/latency capture, and browser console are implemented. Manual testing has now produced a complete real-provider run through multiple Delegate responses, a real Critic pass, and a real Arbiter synthesis.

The main remaining uncertainties are reliability and product quality rather than architectural viability: transient-provider retry/backoff, provider-specific quota/capacity behavior, routing quality, synthesis quality, and whether Conclave consistently reduces enough human copy/paste and comparison work to justify continued expansion.

## Research notes and roadmap

- [November 13, 2026 research roadmap](docs/RESEARCH_ROADMAP_2026-11-13.md): coordination fixtures, contribution-aware Critic evaluation, bounded harness changes, and verified newsletter leads on evaluation, routing, and supervised tools. Includes evidence limits and measurable proposals; no implementation is claimed.
- [October 23, 2026 research roadmap](docs/RESEARCH_ROADMAP_2026-10-23.md): proposed experiments for runtime-enforced delegate scope, evidence-backed Critic verification, and a capped shared findings buffer, with sources, limitations, prerequisites, and measurable acceptance targets. These are proposals, not completed implementation or an expansion of MVP execution authority.

## License

No license has been selected yet.
