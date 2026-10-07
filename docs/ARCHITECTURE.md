# Architecture Notes

Conclave should begin as a deterministic orchestration pipeline, not an autonomous multi-agent system.

## Logical components

### Router
Receives the user's request and workspace configuration. Produces an execution plan containing:
- intent
- constraints
- complexity
- selected delegates
- per-model roles/instructions
- synthesis strategy

### Delegate Runner
Executes model calls independently and concurrently.

Each delegate has its own:
- provider
- model
- prompt
- timeout
- retry state
- response/error
- usage metadata

A failed delegate must not invalidate completed delegates.

### Response Normalization
The current pre-alpha normalizes provider transport metadata (status, raw response, model, usage, cost, latency, error) while preserving the untouched raw response and exact prompt.

Semantic normalization into claims/recommendations/risks/assumptions remains deliberately deferred until real-model testing shows whether it improves synthesis enough to justify another transformation layer.

### Critic
Receives the original question plus successful delegate outputs.

The Critic should focus on:
- contradictions
- unsupported factual assertions
- hidden assumptions
- duplicated conventional wisdom
- meaningful minority positions
- missing information

It should not merely summarize.

### Arbiter
Produces the user-facing synthesis.

Core instruction: **prefer evidence and reasoning over majority vote.**

The Arbiter should clearly separate:
- common ground
- material disagreements
- uncertainty
- final recommendation/answer

## Reliability model

A panel run is a collection of independent delegate jobs rather than one indivisible transaction.

Suggested states:

```text
planned
running
succeeded
failed
timed_out
cancelled
```

The run itself may be considered synthesizeable when a configurable minimum number of delegates have succeeded.

## Provider abstraction

Conclave owns a small provider-neutral request/response abstraction. The first adapter targets OpenAI-compatible chat-completion endpoints, allowing direct compatible providers as well as gateways such as LiteLLM Proxy and OpenRouter.

LiteLLM is an optional gateway, not a hard application dependency. This keeps failure isolation, retries, prompt visibility, routing, and persistence under Conclave's control.

## Data model sketch

Potential initial entities:

- Workspace
- Workspace
- DeliberationRun
- DeliberationRequest snapshot
- DelegateResult
- Critic result
- Arbiter result
- ProviderConfig / ProviderDescriptor

SQLite is sufficient for the current single-user pre-alpha.

## Security assumptions

- API keys must never be committed.
- Local secret storage should be used for a single-user deployment.
- Workspace content may contain sensitive information, so provider selection should be explicit.
- A later privacy policy can allow a workspace to restrict specific delegates to local models only.

## Guiding constraint

The architecture should remain understandable enough that a user can answer:

> Which models saw my question, what exactly were they asked, what did each return, what failed, and how was the final answer produced?

If Conclave cannot answer that clearly, the orchestration layer has become too opaque.
