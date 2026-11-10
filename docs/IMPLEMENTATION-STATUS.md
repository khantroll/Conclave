# Conclave — implementation status

As of 2026-11-10, for `feature/mvp-scaffold` at `c2285d6`. The default branch `main` contains documentation only; nothing below exists there until PR #1 is merged.

## How to read this

| Status | Meaning |
|---|---|
| **Verified (auto)** | Covered by the repository's tests, which were re-run for this audit: 66 passed, Python 3.13, fake providers only. |
| **Verified (manual, 2026-10)** | Recorded as passing in `docs/TEST_LOG.md` by the owner on 2026-10-07 or 2026-10-09. Not re-verified in this audit. |
| **Implemented, untested live** | Code and fake-provider tests exist; never run against a real provider. |
| **Implemented, untested** | Code exists; no automated test. |
| **Defective** | Works on the main path and has a confirmed defect; see the finding in `docs/AUDIT.md`. |
| **Planned** | On the roadmap; not implemented. |
| **Not planned for v1.0** | Deliberately out of scope. |

## Orchestration

| Capability | Status | Notes |
|---|---|---|
| Parallel delegate calls | Verified (auto); Verified (manual, 2026-10) | |
| Per-delegate timeout with cancellation | Verified (auto) | |
| Partial success and quorum | Defective | Empty answers and repeated delegates count as successes (F1, F3) |
| Critic stage | Verified (auto); Verified (manual, 2026-10) | Runs even with one surviving delegate (F5) |
| Arbiter stage | Verified (auto); Verified (manual, 2026-10) | Not told about failed delegates (F4) |
| Critic and Arbiter fallbacks | Implemented, untested live | Earlier failures are not kept (F13); each fallback gets a full timeout (F14) |
| Retry one delegate | Verified (auto) | Also re-runs Critic and Arbiter; will re-run a delegate that succeeded |
| Retry Critic, retry Arbiter | Verified (auto) | New unlinked run; cost of replaced calls dropped (F10, F16) |
| Saving progress during a run | Planned (P0-2) | Today nothing is saved until the pipeline returns (F15) |
| Single-source labelling | Planned (P1-1) | |
| Structured disagreement and uncertainty | Planned (P1-2) | Today a prompt instruction only (F6) |
| Traceable synthesis (claim → delegate) | Planned (P1-2) | Raw answers and prompts are traceable; individual claims are not |
| Independence or similarity checks | Planned (P2-2) | |
| Insufficient-evidence outcome | Planned (P1-2) | |

## Prompts

| Capability | Status | Notes |
|---|---|---|
| Deterministic prompt construction | Verified (auto) | |
| Per-delegate role text | Verified (auto) | |
| Workspace context in all stages | Verified (auto) | "Not instructions" caveat only in the delegate prompt (F19) |
| Evidence-over-majority instruction | Verified (auto) | Presence of the wording is tested; its effect is unmeasured |
| Handling of untrusted model output | Defective | Delegate text can forge blocks (F19) |
| Blinded delegate labels | Planned (P2-1) | Provider and model names are shown to the judge today (F2) |

## Providers

| Capability | Status | Notes |
|---|---|---|
| OpenAI-compatible chat adapter | Verified (auto); Verified (manual, 2026-10) | Groq and OpenRouter returned answers on 2026-10-09 |
| Gemini and Mistral through that adapter | Implemented, untested live | Reached the APIs on 2026-10-09 and got 503 and 429; no successful answer on record |
| Local endpoints (LM Studio, Ollama style) | Implemented, untested live | No recorded run |
| Missing key → provider unavailable, app still starts | Verified (auto) | |
| Bounded retry on 429, 502, 503, 504 | Implemented, untested live | Added after the last live run |
| `Retry-After` seconds and HTTP-date | Implemented, untested live | |
| Attempt counts | Verified (auto) | Timeouts report 1 regardless of attempts made |
| Error classification (auth, quota, rate limit, capacity) | Planned (P1-3) | Quota is retried like a rate limit today (F11) |
| Retry of refused connections | Planned (P1-3) | Not retried today (F12) |
| Output length, temperature, prompt-size limits | Planned (P1-4) | None sent today (F9) |
| Connectivity test, single and all | Verified (auto); Verified (manual, 2026-10) | Callable cross-site with no body (F20) |
| Cost estimate from configured prices | Verified (auto) | Only when prices are configured; wrong after retries (F10) |
| Native Anthropic or Gemini adapters | Not planned for v1.0 | |

## Routing

| Capability | Status | Notes |
|---|---|---|
| Keyword complexity analysis | Verified (auto) | 78% line coverage; accuracy never evaluated (F21) |
| Capability-tag delegate selection | Verified (auto) | Deterministic; quality never evaluated |
| Auto-selection in a workspace | Verified (auto) | A "simple" question still costs three calls (F7) |
| Extraction of intent, constraints, entities (listed in `MVP.md`) | Planned, no roadmap item | Not implemented; recommend removing it from `MVP.md` |

## Persistence

| Capability | Status | Notes |
|---|---|---|
| Workspaces: create, edit, delete | Verified (auto); Verified (manual, 2026-10) | |
| Runs kept when a workspace is deleted | Verified (auto) | |
| Request snapshot per run | Verified (auto) | |
| Exact prompts and raw responses stored | Verified (auto); Verified (manual, 2026-10) | |
| Automatic JSON run log | Verified (auto) | Written atomically; no manual test on record |
| Add-column upgrades of an existing database | Verified (auto) | No schema version (F18) |
| History listing | Defective | Returns every run in full, no paging (F17) |
| Retry lineage and cumulative cost | Planned (P1-5) | |
| Connection handling | Implemented, untested | Connections are not closed (F18) |

## API and console

| Capability | Status | Notes |
|---|---|---|
| REST endpoints for panel, deliberate, workspaces, runs, retries | Verified (auto) | Direct endpoints skip the workspace validation (F1) |
| Run id in `X-Conclave-Run-ID` | Verified (auto) | |
| Browser console: workspaces, run, results, prompts, history, retries, export | Verified (manual, 2026-10); Implemented, untested | No automated tests; syntax check only. Features added after 2026-10-09 (fallback controls, test-all, attempt display) have no recorded manual test |
| HTML escaping of model output | Implemented, untested | Read for this audit; no injection path found |
| Authentication | Not planned for v1.0 | Loopback-only guard is planned instead (P0-4) |
| Origin and host checks | Planned (P0-4) | |
| Progress during a run | Planned (P2-6) | |

## Operations

| Capability | Status | Notes |
|---|---|---|
| CI: compile, Ruff, JS syntax, pytest | Verified (auto) | Green on the last push and on PR #1; runs Python 3.11 |
| Keys only in environment variables | Verified (auto) | No secret found in 214 commits |
| Mock benchmark | Planned (P1-7) | |
| Real-model benchmark | Planned (P2-3) | Needs cost approval |
| Evidence that a panel beats one model | None | One real run on record; no baseline |
| Licence | Not selected | |

## Unknown

- Whether the local checkout where Conclave has been run has uncommitted or unpushed changes. See `docs/AUDIT.md` section 1 for the commands that answer it.
- Whether the configured free-tier providers still respond, and with which models.
- Behaviour on Windows of anything added after 2026-10-09.
