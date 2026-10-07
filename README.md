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
- Structured response normalization
- Critic/disagreement pass
- Configurable synthesis/authority model
- Basic token, latency, and cost accounting

See [docs/MVP.md](docs/MVP.md) for the bounded first-release definition and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for current design notes.

### Explicitly not MVP

- Free-form autonomous agent conversations
- Endless self-reflection loops
- Automatic tool execution on external systems
- Complex RAG infrastructure
- Team/multi-tenant administration
- Mobile clients
- A marketplace of agent personalities

## Current implementation

The first scaffold now contains:

- a FastAPI service
- provider-neutral delegate abstraction
- concurrent panel execution
- independent per-delegate timeouts
- partial-success handling
- a fake provider for deterministic testing
- API and orchestration smoke tests
- GitHub Actions test workflow

Real OpenAI/Anthropic/Gemini/LiteLLM adapters, prompt routing, criticism, synthesis, persistence, and the web UI are intentionally still ahead of this scaffold.

## Development

Requires Python 3.11+.

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pytest -q
uvicorn conclave.api:app --reload
```

Then open the FastAPI docs at `http://127.0.0.1:8000/docs`.

The current demo panel accepts delegates named `demo-a` and `demo-b`; they exist only to exercise orchestration before real provider configuration is added.

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
- **Frontend:** React/Next.js or another lightweight web UI
- **Storage:** SQLite initially
- **Provider gateway:** LiteLLM is the leading candidate
- **Local providers:** Ollama / LM Studio through OpenAI-compatible APIs

No implementation choice above should be considered final until the MVP requirements are written and tested against existing orchestration tools.

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

**Pre-alpha / active scaffold.**

The orchestration skeleton is under development. The immediate goal is to prove reliable delegate execution and failure isolation before adding real provider integrations or UI complexity.

## License

No license has been selected yet.
