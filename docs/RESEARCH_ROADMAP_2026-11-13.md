# Research roadmap — November 13, 2026

Status: proposed experiments only. No implementation, provider calls, or experimental results are claimed by this document.

This follows the [October 23 research roadmap](RESEARCH_ROADMAP_2026-10-23.md). Before implementation, inspect the active checkout and reuse existing routing, retry, fallback, persistence, and adversarial-test machinery. Preserve blind Critic/Arbiter judging, raw responses, workspace allowlists, and the rule that model output has no dispatch authority. These notes do not add automatic external tool execution.

## Priority order

1. **Recorded-output coordination evaluation:** highest expected benefit for modest effort; no paid calls are needed to establish orchestration checks.
2. **Contribution-aware Critic experiment:** test evidence retention and correct minority findings before changing synthesis.
3. **Bounded harness improvement:** only after a frozen baseline exists; constrain evaluation cost and latency.
4. **Optional learned-routing comparison:** a shadow experiment, after deterministic routing quality is measured.
5. **Future supervised tools:** design checks only; outside the current execution scope.

Benefit/effort judgments and all acceptance thresholds below are project proposals, not source results.

## R04 — Measure coordination separately from model quality

Source: [WorkflowArena: Benchmarking Executable Workflow Orchestration in LLM-Based Multi-Agent Systems](https://arxiv.org/abs/2611.12856), submitted **November 9, 2026**.

**Reported:** 145 tasks across eight domains evaluate integrated deliverables and recorded delegation. Transferring workflows while holding the executor fixed improved weaker executors on a challenging subset.

**Evidence and limits:** Most comparisons mix models and harnesses; runs are limited and some grading uses model judges. This does not establish that autonomous workflow generation would improve Conclave.

**Inference:** Coordination needs its own evaluation rather than attribution through final-answer scores alone.

**Proposed experiment:** Create 12 offline fixtures covering independent findings, a dependency, conflicting evidence, an unavailable delegate, and a correct minority. Feed identical recorded delegate outputs to baseline and candidate synthesis paths. Represent dependencies and expected evidence explicitly without executing a generated plan.

**Pass:** all fixture dependencies are respected; unresolved contradictions and missing results are disclosed; all required evidence survives synthesis; no failed delegate is described as successful. Record per-case results, not just an average. Later live-model evaluation measures synthesis quality separately. Low local CPU/memory demand, zero provider cost for the fixture stage.

## R05 — Judge contribution without suppressing dissent

Source: [From Delegation to Coordination: Learning Efficient Multi-Agent Deep Research (LEAD-RL)](https://arxiv.org/abs/2611.17041), submitted **November 12, 2026**.

**Reported:** contribution-aware training assigns credit according to each report's research utility. Against shared team-credit training, authors report +2.49 percentage points on BrowseComp and 24.5% lower critical-path cost.

**Evidence and limits:** This is reinforcement learning across model families and research benchmarks. Critical-path cost is a step-based measure, not measured wall-clock latency or a dollar saving. A Critic prompt cannot reproduce the training result.

**Inference:** Contribution labels could make redundancy, unsupported claims, and useful minority evidence inspectable.

**Proposed experiment:** On 20 panels with known evidence, ask a blinded Critic for advisory helpful/neutral/harmful labels tied to specific claims and receipts. Include correct minorities and persuasive incorrect majorities. Keep every response available to the Arbiter; labels cannot remove evidence or trigger dispatch.

**Pass:** at least 90% agreement with manually assigned fixture labels, all correct minority findings remain available and represented appropriately in synthesis, and every harmful label names a concrete defect. Log added tokens and p50/p95 latency. Stop if the added stage cost outweighs correction savings.

## R06 — Improve the harness against held-out failures

Source: [MULTILOOP: Evolving Multi-Agent Harnesses for Complex Information-Seeking Tasks](https://arxiv.org/abs/2611.15754), submitted **November 11, 2026**.

**Reported:** using ten training examples, automated harness edits improved fully correct DeepSearchQA results from 67.27% to 71.88% on 890 held-out questions. Structural orchestration failures largely persisted.

**Evidence and limits:** Single case-study environment and model/harness setting; accuracy improvement does not prove lower cost, and prompt-only optimization did not solve coordination.

**Inference:** Target a documented orchestration defect rather than starting an unrestricted optimization loop.

**Proposed experiment:** Freeze ten development cases and 20 untouched evaluation cases. Make one bounded change addressing evidence loss, duplicate work, or dependency handling. Compare the same inputs/settings; keep the untouched set out of prompt development. Use replay first, followed by a capped real-provider evaluation only when needed.

**Pass:** fewer coordination failures, no reduction in correctness or useful dissent, and no more than 10% additional tokens. Report p50/p95 elapsed time, total provider cost, failed attempts, and local resource use. Reject a candidate that only improves the development set.

## Gmail-derived engineering additions

Recent AI/developer newsletters were used as discovery leads. The entries below link to verified public originals; email bodies, account information, tracking links, and private correspondence are not reproduced.

### R07 — Per-example release gates

Source: [What Is Eval-Driven Development?](https://www.langchain.com/blog/what-is-eval-driven-development), **November 9, 2026**; found via TLDR Dev, November 12.

**Reported:** define behavior, create examples/evaluators before changes, then compare baselines per example. An aggregate improvement can conceal a regression. This is an engineering guide, not a controlled performance study.

**Proposed application:** attach explicit “must keep working” checks to R04–R06: successful delegates survive 429/503/timeouts, isolated retries do not rerun successes, raw evidence remains accessible, and model text cannot change runtime authority. Preserve the existing adversarial suite. Pass every deterministic invariant and review every new per-case regression before promoting a change. No new evaluation platform is required.

### R08 — Shadow-test bounded semantic routing

Source: [Gemini Decisions API: Fast, calibrated multimodal decisions](https://blog.google/innovation-and-ai/technology/developers-tools/gemini-decisions-api/), **November 11, 2026**; found via TLDR Dev, November 12.

**Reported:** Google offers fixed-choice and rubric probability outputs; its announcement claims 150–250 ms end-to-end latency. These are vendor measurements, not results on Conclave or this account.

**Inference:** a closed-set scorer might help ambiguous complexity/capability classification, but adds a cloud dependency to an inspectable deterministic path.

**Proposed experiment:** shadow-score 30 manually labeled routing cases using only candidates already allowed by the workspace. Do not change actual dispatch. Inject timeout, malformed, low-confidence, and rate-limit responses; retain the existing route on failure. No secrets or private project content in fixtures.

**Pass:** at least 90% label agreement, zero selections outside the allowlist, all injected failures retain the baseline route, and p95 added latency below 500 ms. Record billed cost and compare against the deterministic baseline. Adopt only if better routing justifies extra latency, cost, and failure exposure. No runtime authority is delegated to the scorer.

### R09 — One tool contract across CLI and MCP, later

Source: [MCP or CLI? Yes.](https://blog.sentry.io/mcp-or-cli/), **November 10, 2026**; found via TLDR Dev, November 11.

**Reported:** Sentry bridges CLI login to its stdio MCP server. The post describes filesystem-oriented CLI advantages and inconsistent client support for MCP features. Transport-specific steering is discussed as future work, not a shipped result. No comparative benchmark is supplied.

**Inference/proposal:** for any later supervised tools, share schemas and permission checks across transports rather than treating CLI access as broader authority. Design a dummy read-only tool with identical CLI/MCP outputs and a runtime-enforced allowlist. Pass: all 20 malformed/unauthorized requests are denied and allowed requests produce equivalent receipts. Use local fixtures, no credentials and no external actions. This remains outside MVP execution.

### Older backlog lead — host-enforced permissions and scoped undo

Source: [Dropbox engineering report](https://dropbox.tech/machine-learning/how-two-engineer-side-projects-became-the-agent-taking-action-inside-dropbox), **November 5, 2026**; surfaced in TLDR Dev, November 12. **Outside this week's publication window.**

**Reported:** isolated workspaces keep credentials and access checks in a trusted host; changes are attributed to conversations for scoped undo, with later edits preserved. This is a vendor system report, not an independent security evaluation.

**Proposed follow-up to October R01/R02:** sketch a supervised plan receipt with runtime-owned scope, turn/revision IDs, permitted operations, and reversible change records. On ten offline cases including cancellation and a later conflicting edit, pass only if scope expansion is denied and undo preserves the later edit. No tools or VM stack are adopted through this note.
