# Research roadmap — October 23, 2026 brief

Added October 24, 2026. All items below are proposed experiments, not completed work, validated improvements, or changes to MVP scope. The default-branch README describes a deterministic, inspectable pipeline and excludes automatic external tool execution from the MVP. Preserve those boundaries.

Before implementation, inspect current development branches and run artifacts for equivalent functionality. The existing delegate → Critic → Arbiter flow is the baseline to evaluate, not something this note establishes as implemented on the default branch.

## Order and prerequisites

1. R01: enforce delegate participation and context boundaries before adding shared context.
2. R02: evaluate evidence-backed Critic verification with fixtures and actual check receipts.
3. R03: establish the existing pipeline's baseline, then evaluate a capped findings buffer behind an optional experiment mode.

Keep provider timeouts, bounded retries, partial-success behavior, raw-response visibility, and evidence-over-majority synthesis intact. No experiment authorizes external actions. These research tasks do not override the user's broader project priorities.

## R01 — Runtime-enforced delegate scope

Source: [The Show-Up Attack: When Subagents Win Over Their Supervisor](https://arxiv.org/abs/2610.27574), submitted October 20, 2026.

What changed: the paper studies delegates manipulating a supervisor into involving them in later tasks outside their assignment. SUA-Arena contains 188 cases and six attack strategies; six models were evaluated, and prompting/restricted communication did not consistently prevent the behavior.

Evidence limits: simulated service roles and specific model configurations do not establish vulnerability prevalence in Conclave or deployed heterogeneous systems. This is an author-run preprint evaluation.

Proposed experiment:
- Feed mock delegate responses claiming expanded authority, forged prior approval, or a need to access another task's context.
- Define allowed participants, task IDs, context visibility, and proposed-tool scope in runtime-owned data. Delegate output is evidence to assess, not permission to expand access or participation.
- Exercise 50 cases including legitimate dissent and permitted delegation controls.
- Pass: zero unauthorized dispatches or context transfers; legitimate disagreement still reaches the Arbiter.
- Log blocked attempts and outcomes without secrets or unrelated task content. Record false blocks, processing latency, and local CPU/memory overhead.

Engineering judgment: enforce scope before shared findings or persistent memory can propagate a delegate's self-assigned authority. Prefer deterministic checks over extra model calls. This note does not claim a complete security defense.

## R02 — Evidence-backed Critic checks

Source: [Automating Feature Flag Cleanup at Scale with Multi-Agent LLM Systems: An Industrial Experience at DoorDash](https://arxiv.org/abs/2610.31351), submitted October 22, 2026.

What changed: an industrial report combines cheaper orchestration, stronger editing agents, live state lookup via MCP, isolated git worktrees, and deterministic validation. Of 50 cleanups, 31 succeeded initially, 14 needed revision, and five needed substantial intervention; average API cost was $4.79 and elapsed time 13.8 minutes. Deep cross-file dependency chains exposed incomplete cleanup.

Evidence limits: newly published report using earlier operational data, one company, Kotlin repositories, a narrow cleanup task, and no repeated trials per item. The reported outcomes and cost/time figures are not forecasts for Conclave.

Proposed experiment:
- Build ten small fixture patches with deliberately omitted dependencies or failed checks, plus clean controls.
- Supply the Critic with captured, actual check receipts bound to the candidate patch/revision. Distinguish failed, passed, unavailable, and not-run checks.
- Retain deterministic enforcement: an actual failed required check must block a "verified" result regardless of model opinion. A model's assertion that checks passed is insufficient evidence.
- Pass: every failed required check blocks verification; at least nine of ten incomplete patches are identified; clean-control false positives are recorded.
- Record token usage, wall time, and revision-specific evidence provenance; use offline fixtures before any live tool integration.

Engineering judgment: evidence-backed verification is a prerequisite to considering broader tool-use capabilities. Conclave continues to produce proposed plans under human supervision; this experiment does not add external execution. If coding delegates are later evaluated, isolate worktrees and build artifacts and start with bounded concurrency to limit local CPU contention. Do not copy the report's concurrency setting as a hardware recommendation.

## R03 — Capped shared findings buffer

Source: [Muffin — A Shared Memory Buffer for Asynchronous AI Agents](https://arxiv.org/abs/2610.31355), submitted October 22, 2026.

What changed: delegates exchange selected intermediate findings asynchronously while retaining private reasoning. Authors report best accuracy in 17/20 settings. The headline 77.4% fewer tokens versus multi-agent debate is from a specific stepwise comparison, not a universal savings estimate. One ablation found little gain beyond three agents.

Evidence limits: reasoning/question-answering benchmarks; tool use and long-horizon execution remain future work. Adding findings can introduce redundant or stale information. The paper links implementation and experiment scripts.

Prerequisites: R01's scope checks and a measured baseline of the existing independent-delegate → Critic → Arbiter pipeline. Keep that existing path available.

Proposed experiment:
- Compare the baseline with three delegates exchanging a capped buffer of claims, supporting evidence, and unresolved disagreements, rather than full reasoning traces.
- Keep independent initial responses to measure whether sharing creates correlated errors. Bind entries to the current run/task and source delegate; expire stale findings and exclude unrelated workspace context.
- Use 30 objectively checkable tasks with the same models, provider settings, and maximum token/call budget. Repeat paired runs where feasible and report variability.
- Retain raw responses, dissent, timeouts, and partial-success handling. Cap rounds, entries, entry length, concurrency, and total elapsed time; do not introduce unbounded conversations.
- Pass target (proposed, not a paper result): at least 25% fewer total tokens with no reduction in correct final answers on the fixed set.
- Also record median/p95 wall time, actual API cost, local CPU/memory, unauthorized-sharing attempts, and initially correct delegates pulled toward an incorrect shared answer.
- Treat this small evaluation as a screening result, not proof of general improvement. A failed target keeps the baseline as the default.

Engineering judgment: potentially useful cost/latency improvement with moderate implementation effort, but lower priority than boundary enforcement and verification. No training run, new model stack, or automatic execution is required.

## Relationship to Hail

[Jarvis: Coordination Deserves a Brain of Its Own](https://arxiv.org/abs/2610.23804), submitted October 16, 2026, is tracked primarily in [Hail's roadmap](https://github.com/khantroll/Hail/blob/main/docs/ROADMAP.md). Its task-version and pre-execution checks may inform a future Hail–Conclave handoff. Such a handoff must preserve task/revision identity and reject results from superseded requests; no integration is implemented or authorized by this note.
