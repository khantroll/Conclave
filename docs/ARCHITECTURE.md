# Architecture Notes

Conclave should begin as a deterministic orchestration pipeline, not an autonomous multi-agent system.

## Logical components

### Router
Receives the user's request and workspace configuration. Today it is a deterministic analyzer (`analyzer.py`, `selection.py`): it assigns a complexity level, recommends a panel size and desired capabilities, and ranks the workspace's allowed delegates. It does not extract intent, constraints or entities, and it makes no model call. Before any delegate is called, `quorum.py` checks that enough *independent* sources can answer (see below) and tops an automatically chosen panel up from the eligible pool.

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

### Response handling
Provider transport metadata (status, raw response, model, usage, latency, error and its kind) is normalized while the untouched raw response and the exact prompt are preserved. Two things are read from model text, both display-only and both from a model's own answer alone: a delegate's closing `Conclusion:` and `Confidence:` lines (`positions.py`), and the Arbiter's four sections (`synthesis.py`).

Semantic normalization into claims/recommendations/risks/assumptions remains deliberately deferred.

### Independent sources
`sources.py` groups the answers that count as one source: the same configured endpoint and model, the same reported model, unresolved router aliases on one host, or near-identical text. Quorum is measured in sources. Text similarity catches copies, not shared training data or shared errors.

### Blind judging
`prompts.py` shows the Critic and Arbiter `Response A`, `Response B`... in an order permuted by the run seed and stable across retries, with no provider, model, timing, cost, attempt or error text, inside per-run markers, with model text escaped and capped. They are also told how many delegates answered and which responses are one source or one family (by label only). The label-to-delegate mapping is stored for the user.

### Critic
Receives the original question plus successful delegate outputs.

The Critic is optional, and a workspace must say whether it uses one. It should focus on:
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

The Arbiter writes four headings (common ground, disagreements, uncertainty, synthesis) with points that cite response labels. The answer is parsed strictly; anything else is shown raw with a notice. The synthesis must begin "Insufficient evidence" when the responses do not support an answer.

## Reliability model

A panel run is a collection of independent delegate jobs rather than one indivisible transaction.

A delegate ends `succeeded`, `failed` (with an error kind) or `timed_out`; an empty answer is a failure. A run is synthesizeable when the configured number of *independent sources* has answered, or when a workspace explicitly allows a single-source run (which is then labelled and never reported as a consensus). A run row exists, as `running`, before any provider is called, is updated after each stage, and ends `complete` or `interrupted`; a delegate that had answered when a run was cancelled keeps its answer.

Provider errors are classified, and only rate limits, capacity errors and refused connections are retried. A Critic or Arbiter fallback keeps the failed primary's trail. Retries are new runs linked into a chain, one at a time per chain.

## Provider abstraction

Conclave owns a small provider-neutral request/response abstraction. The first adapter targets OpenAI-compatible chat-completion endpoints, allowing direct compatible providers as well as gateways such as LiteLLM Proxy and OpenRouter.

LiteLLM is an optional gateway, not a hard application dependency. This keeps failure isolation, retries, prompt visibility, routing, and persistence under Conclave's control.

## Data model sketch

Stored entities:

- Workspace
- DeliberationRun, with its DeliberationRequest snapshot (including the seed) and DeliberationResult
- DelegateResult for each delegate, the Critic and the Arbiter, with prompts, raw responses, error kinds and prior attempts
- Positions, the Arbiter's structure, the label map and the cost summary inside the result
- The call ledger: one row per provider request
- Retry lineage (`parent_run_id`, `chain_root_id`) and a schema version

ProviderConfig and ProviderDescriptor are configuration, not stored. SQLite is sufficient for a single user; history is served as bounded summaries, and a database is backed up and verified before it is upgraded.

## Security assumptions

- API keys must never be committed.
- Local secret storage should be used for a single-user deployment.
- Workspace content may contain sensitive information, so provider selection should be explicit.
- Model output is untrusted data: it has no authority over what Conclave does, and an adversarial suite tests that.
- Conclave has no authentication and is meant for loopback: it refuses requests whose `Host` is not loopback and cross-origin state changes. Prompts, answers and the ledger are stored in plain text.
- A later privacy policy can allow a workspace to restrict specific delegates to local models only (not built).

## Guiding constraint

The architecture should remain understandable enough that a user can answer:

> Which models saw my question, what exactly were they asked, what did each return, what failed, and how was the final answer produced?

If Conclave cannot answer that clearly, the orchestration layer has become too opaque.
