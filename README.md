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

- [October 23, 2026 research roadmap](docs/RESEARCH_ROADMAP_2026-10-23.md): proposed experiments for runtime-enforced delegate scope, evidence-backed Critic verification, and a capped shared findings buffer, with sources, limitations, prerequisites, and measurable acceptance targets. These are proposals, not completed implementation or an expansion of MVP execution authority.

## License

No license has been selected yet.
