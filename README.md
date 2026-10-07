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

### Explicitly not MVP

- Free-form autonomous agent conversations
- Endless self-reflection loops
- Automatic tool execution on external systems
- Complex RAG infrastructure
- Team/multi-tenant administration
- Mobile clients
- A marketplace of agent personalities

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

**Planning / pre-alpha.**

The repository has been initialized to capture the product idea before implementation begins. The next step is to define a tightly bounded MVP and decide how much provider plumbing should be delegated to LiteLLM versus implemented directly.

## License

No license has been selected yet.
