# Conclave MVP

This document defines the first target release. The purpose of the MVP is to prove that multi-model deliberation can be more useful and more reliable than manually carrying context between AI systems.

## Primary user story

As a user, I can submit one question to a selected panel of models, see each model's original response, survive individual provider failures, and receive a synthesized answer that explicitly identifies important agreement, disagreement, assumptions, and uncertainty.

## Required capabilities

1. **Ask once**
   - Accept a free-form question.
   - Optionally attach workspace context.

2. **Analyze the request**
   - Extract intent, constraints, entities, and desired output.
   - Assign a simple complexity level.
   - Recommend whether one model or a panel is appropriate.

3. **Prepare delegates**
   - Select configured models.
   - Support a common prompt plus optional model-specific role/instructions.
   - Show the generated prompts to the user.

4. **Dispatch concurrently**
   - Call delegates in parallel.
   - Apply an independent timeout per delegate.
   - Retry a failed delegate without rerunning successful delegates.

5. **Degrade gracefully**
   - Preserve successful responses if another provider fails.
   - Allow synthesis from the available subset.
   - Clearly label missing delegates.

6. **Preserve originals**
   - Store and display each raw response.
   - Never replace the source responses with the synthesis.

7. **Critique**
   - Identify conflicting claims.
   - Flag unsupported assumptions and likely factual claims requiring verification.
   - Surface useful minority opinions.
   - Avoid treating vote count as truth.

8. **Synthesize**
   - Use a configurable Arbiter model.
   - Produce a concise final answer.
   - Preserve unresolved disagreements and uncertainties.

9. **Track execution**
   - Latency by model.
   - Token usage where providers expose it.
   - Estimated/actual cost where practical.
   - Provider/model errors.

10. **Workspace basics**
    - Name and description.
    - Persistent context/instructions.
    - Default delegates.
    - Default Arbiter.

## MVP non-goals

The first release will not include:

- autonomous agent-to-agent conversations
- recursive debate loops
- automatic code changes or external actions
- complex retrieval infrastructure
- multi-user access control
- mobile applications
- provider-specific feature parity beyond text requests
- automated benchmarking of model intelligence

## Success criteria

The MVP is successful if it can demonstrate all of the following:

- A three-model request succeeds when all providers are healthy.
- A request still produces a useful result when one delegate times out or errors.
- Failed delegates can be retried independently.
- Raw responses are always inspectable.
- The final synthesis distinguishes consensus from uncertainty and disagreement.
- A workspace can materially reduce repeated context entry.
- Running Conclave feels easier than manually copying responses among several AI chats.

## Decisions made for the pre-alpha

- **Provider strategy:** Conclave owns the provider abstraction; LiteLLM/OpenRouter may be used behind the generic OpenAI-compatible adapter.
- **Request analysis:** deterministic/rule-based first, so routing does not require an extra model call.
- **Prompt visibility:** exact prompts and untouched raw responses are persisted.
- **Critic/Arbiter:** configured per workspace.
- **Secrets:** API keys are referenced through environment variables and are not stored in workspace data.
- **Persistence:** SQLite stores workspaces, request snapshots, and run results.
- **Retries:** Delegate, Critic, and Arbiter retries are isolated so successful upstream work does not need to be repeated.

Semantic claim/source normalization is intentionally deferred until real-provider testing demonstrates a clear need.
