# Conclave v1.0 Completion Mandate — 2026-11-15

Status: development handoff, **not** proof of completion. This document captures the maintainer's requested completion-focused direction. The latest repository state, open PRs, and local worktree must be rechecked before execution.

## Mission and scope

Finish Conclave as a reliable, single-user, local multi-model deliberation and synthesis console—not an autonomous swarm. It takes a user's question, runs genuinely independent delegate models concurrently, retains original responses, identifies agreement/disagreement/uncertainty, optionally runs a Critic, and uses an Arbiter to provide a transparent synthesis. Every model output is untrusted data; agreement is not independent verification. Do not absorb Tank (agent missions), Hail (voice routing), or NEXUS (desktop docking).

## First: inspect, reconcile, preserve

1. Inspect git remote, branch, HEAD, status, worktrees, configuration, architecture, README, roadmap, tests, CI, issues, and PRs. Fetch safely and preserve uncommitted changes.
2. Reconcile PR #44 (opt-in cost ceiling, shared deadline, reserve delegates, background/cancel execution; tests reported passing but not exercised against live providers), PR #43 (acceptance-run/next-steps docs), and older v1 planning PRs #2 and #3. Never blindly merge or overwrite.
3. Preserve local environment files, credentials, SQLite data and run logs. No secrets in commits or diagnostic output.
4. Create an evidence-based PASS/FAIL/BLOCKED matrix; don't rebuild already working features.

## Completion sequence

### 1. Core orchestration
- Verify concurrent delegates, accurate independent-source quorum, duplicate/router-alias detection, deterministic selection, partial failure, structured retries, bounded fallback and reserve delegates.
- Verify optional Critic and blind Arbiter, stable masked answer labels, response positions, checked four-section synthesis, missing-evidence reporting.
- Preserve benchmark evidence: do not enable Critic by default without a defensible empirical result.
- Implement or harden honest token/cost tracking, cost ceilings that fail closed when unknown, provider-reported vs estimated costs, stage deadlines, background run lifecycle and cancellation.

### 2. Providers and configuration
- Verify configured Gemini, Groq, Mistral, OpenRouter, Anthropic/Claude, OpenAI-compatible and local endpoints as available; don't equate CLI/subscription authentication with API access.
- Show configuration identity, connection/auth status, actual errors, last success, capability limits and prices/quotas only when verifiable. Unknown means unknown.
- Run inexpensive bounded smoke tests with **already authorized** credentials. Ask permission before significant paid usage; record blocked paths rather than fabricating success.

### 3. Finish the existing UI
- Provide everyday workflows without editing Python: provider status/configuration, workspace and model-role selection, quorum and cost controls, initiate run, inspect progress, raw responses and independent-source count, Critic/Arbiter comparison, cancel/retry, history, call ledger, diagnostics and export.
- Improve the current HTML/JS console without introducing a new framework unless clearly necessary.

### 4. Validation
- Run lint, Python tests, JS renderer tests and CI. Add deterministic integration tests for failure, timeouts, independence, retries, reserve waves, cost unknowns, cancellation races, DB migration, output escaping and prompt injection.
- Run a real multi-provider panel with observable providers and reproduce the full question -> delegates -> quorum -> optional Critic -> Arbiter -> synthesis -> history workflow.
- Distinguish live-provider evidence from mocked tests and old acceptance reports. Preserve exact commands, versions, outcomes and redacted logs.

### 5. Security, reliability and release
- Verify loopback boundary, origin checks, secret redaction, untrusted-model-output handling, safe rendering, resource bounds, migration backups and run state transitions.
- Document clean Windows/Linux setup, provider setup, first working panel, troubleshooting, limitations and release changelog.
- Produce a release candidate only with no unresolved release blockers; otherwise mark blocked with exact external dependencies.

## Working rules

Proceed autonomously on ordinary implementation, tests, refactors, documentation, development branches, commits and PRs. Do not require approval at every phase. Require explicit authorization for irreversible operations, protected-branch merges, changes to secrets/permissions, significant paid API spending, and externally consequential actions. Do not disable safety checks to pass tests. Keep an up-to-date, concise status/handoff document with commit refs, verified results and precise next step. Use independent code review, but evaluate its findings rather than treating its approval as proof.

## Definition of DONE

The following must each have reproducible **PASS** evidence (otherwise FAIL or BLOCKED):
- Clean installation/start; provider setup; actual multi-provider concurrent run.
- Correct independence/quorum accounting, partial failures/retries/fallbacks and optional judge stages.
- Safe cancellations, stage deadline, reserve behavior and bounded costs.
- Complete usable GUI, history and honest ledger.
- Adversarial regression tests, safe DB upgrade, passing CI.
- Real-provider acceptance captured with bounded costs and provider/model identities.
- Documentation agrees with code, PRs reconciled, release candidate reviewed.

**Instructions to the coding agent:** Start with a fresh repository audit; implement, test and commit every remaining bounded v1 blocker; keep working through the phases rather than stopping at an audit or roadmap; never claim completion without the evidence above.
