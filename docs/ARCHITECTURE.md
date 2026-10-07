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

### Response Normalizer
Converts provider results into a common internal representation while retaining the untouched raw response.

Candidate normalized fields:
- answer
- key claims
- recommendations
- assumptions
- risks
- unknowns
- citations/sources when present

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

LiteLLM is the leading candidate for the first provider gateway because it can reduce provider-specific integration work. This is not yet a locked decision.

Conclave should retain its own provider-neutral request/response abstraction so replacing or bypassing the gateway later remains possible.

## Data model sketch

Potential initial entities:

- Workspace
- Conversation
- Query
- ExecutionPlan
- DelegateRun
- RawResponse
- Critique
- Synthesis
- ProviderConfig
- ModelConfig

SQLite should be sufficient initially.

## Security assumptions

- API keys must never be committed.
- Local secret storage should be used for a single-user deployment.
- Workspace content may contain sensitive information, so provider selection should be explicit.
- A later privacy policy can allow a workspace to restrict specific delegates to local models only.

## Guiding constraint

The architecture should remain understandable enough that a user can answer:

> Which models saw my question, what exactly were they asked, what did each return, what failed, and how was the final answer produced?

If Conclave cannot answer that clearly, the orchestration layer has become too opaque.
