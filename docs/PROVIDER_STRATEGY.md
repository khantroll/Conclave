# Provider Strategy

Conclave should own its orchestration behavior without owning every provider's HTTP quirks.

## Decision

For the first implementation, Conclave uses its own small provider abstraction and ships an **OpenAI-compatible adapter**. That adapter can target:

- OpenAI-compatible hosted APIs
- OpenRouter
- LiteLLM Proxy
- LM Studio
- Ollama compatibility endpoints
- other compatible gateways

LiteLLM is therefore a **recommended gateway option**, not a hard runtime dependency.

## Why not embed LiteLLM immediately?

LiteLLM solves a real problem, but making the application itself depend on LiteLLM from day one would move a critical part of Conclave's failure model behind a large abstraction before we have proven our own semantics.

Conclave specifically needs to control:

- independent delegate timeouts
- partial success
- retries of one delegate without rerunning the panel
- raw response preservation
- prompt visibility
- cost and usage capture
- Critic/Arbiter behavior

Those remain Conclave responsibilities whether the provider call underneath goes directly to a vendor or through LiteLLM.

Using LiteLLM Proxy behind the OpenAI-compatible adapter gives us its broad provider support without forcing Conclave's core to know about it.

## Why not directly reuse HomeLedger's Configure AI implementation?

HomeLedger contains useful design lessons around optional cloud AI, provider configuration, privacy boundaries, and local-first behavior. Those principles should carry forward.

The implementation itself is not a clean dependency for Conclave: HomeLedger's AI work lives inside a Tauri/Rust/TypeScript desktop application and is coupled to HomeLedger's privacy and application boundaries. Copying it wholesale would import unrelated assumptions.

Conclave will reuse the **patterns**, not create a code-level dependency between the projects.

## Likely evolution

1. **Now:** generic OpenAI-compatible adapter.
2. **Next:** validate real calls through at least one direct compatible provider and one LiteLLM/OpenRouter route.
3. **As needed:** add native adapters only where they unlock capabilities or reliability that the compatibility layer cannot provide.
4. **Implemented in pre-alpha:** explicit connection tests, optional pricing metadata, and per-provider capability/priority flags.
5. **Later:** richer provider health history, automated model discovery, and native adapters only where compatibility gateways are insufficient.

## Architectural rule

The Orchestrator may depend on Conclave's `Provider` interface. It should never need to know whether a delegate is backed by OpenAI, Anthropic, Gemini, LiteLLM, OpenRouter, LM Studio, or another implementation.

That boundary is what lets Conclave change provider strategy without rewriting deliberation logic.
