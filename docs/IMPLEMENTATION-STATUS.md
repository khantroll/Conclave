# Conclave — implementation status

As of 2026-11-10, for `feature/mvp-scaffold` at `c2285d6`. The default branch `main` contains documentation only; nothing below exists there until PR #1 is merged. Item numbers refer to `docs/ROADMAP-TO-V1.md` revision 2, and invariants I1–I8 are defined there.

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
| Partial success and quorum | Defective | Empty answers and repeated delegates count as successes, and quorum counts raw successes, not independent sources (F1, F3); fix planned (P0-6) |
| Critic stage | Verified (auto); Verified (manual, 2026-10) | Runs even with one surviving delegate (F5) |
| Critic default | Planned (P1-13) | The API defaults to no Critic, and a blank console field means no Critic: an implicit "off". Planned: the default comes from the judge benchmark, and until then every workspace must choose explicitly (P1-13) |
| Arbiter stage | Verified (auto); Verified (manual, 2026-10) | Not told about failed delegates (F4) |
| Critic and Arbiter fallbacks | Implemented, untested live | Earlier failures are not kept (F13); each fallback gets a full timeout (F14) |
| Retry one delegate | Verified (auto) | Also re-runs Critic and Arbiter; will re-run a delegate that succeeded |
| Retry Critic, retry Arbiter | Verified (auto) | New unlinked run; cost of replaced calls dropped (F10, F16) |
| Saving progress during a run | Planned (P0-3) | Today nothing is saved until the pipeline returns (F15) |
| Single-source labelling | Planned (P1-1) | Will use independent sources, not raw successes |
| Structured disagreement and uncertainty | Planned (P1-6) | Today a prompt instruction only (F6) |
| Traceable synthesis (claim → delegate) | Planned (P1-6) | Raw answers and prompts are traceable; individual claims are not. Planned as citations to blinded response labels |
| Each delegate's own position shown verbatim (I4) | Planned (P1-5) | Today dissent is visible only if the Arbiter reports it, or by reading the raw answers |
| Source identity: one source per underlying model (I2) | Planned (P0-6) | Today two names pointing at one model count as two corroborating sources |
| Near-duplicate answer detection and model-family labels (I2) | Planned (P1-4) | Catches copies; cannot detect shared training bias |
| Insufficient-evidence outcome | Planned (P1-5, P1-6) | |

## Prompts

| Capability | Status | Notes |
|---|---|---|
| Deterministic prompt construction | Verified (auto) | |
| Per-delegate role text | Verified (auto) | |
| Workspace context in all stages | Verified (auto) | "Not instructions" caveat only in the delegate prompt (F19) |
| Evidence-over-majority instruction | Verified (auto) | Presence of the wording is tested; its effect is unmeasured |
| Handling of untrusted model output (I6) | Defective | Delegate text can forge blocks (F19). Planned: data framing, seeded markers, escaping, a per-response cap (P0-4) and an 11-class adversarial suite (P1-2) |
| Blinded judging (I7) | Planned (P1-3) | Provider and model names are shown to the judge today, in workspace order (F2) |

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
| Error classification (auth, quota, rate limit, capacity) | Planned (P1-7) | Quota is retried like a rate limit today (F11) |
| Retry of refused connections | Planned (P1-7) | Not retried today (F12) |
| Output length, temperature, prompt-size limits | Planned (P1-8) | None sent today (F9) |
| Connectivity test, single and all | Verified (auto); Verified (manual, 2026-10) | Callable cross-site with no body (F20) |
| Cost estimate from configured prices | Verified (auto) | Only when prices are configured. Drops retried and fallback calls (F10), and missing prices show as no figure rather than "unpriced" |
| Call ledger: estimated vs provider-reported, never billed (I8) | Planned (P1-9) | Today only an estimate exists, and it is not labelled as one |
| Native Anthropic or Gemini adapters | Not planned for v1.0 | |

## Routing

| Capability | Status | Notes |
|---|---|---|
| Keyword complexity analysis | Verified (auto) | 78% line coverage; accuracy never evaluated (F21) |
| Capability-tag delegate selection | Verified (auto) | Deterministic; quality never evaluated |
| Auto-selection in a workspace | Verified (auto) | A "simple" question still costs three calls (F7) |
| Extraction of intent, constraints, entities (listed in `MVP.md`) | Not planned for v1.0 | Not implemented; to be removed from `MVP.md` (P1-14) |

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
| Retry lineage and single-flight retries | Planned (P1-10) | |
| Connection handling | Implemented, untested | Connections are not closed (F18) |

## API and console

| Capability | Status | Notes |
|---|---|---|
| REST endpoints for panel, deliberate, workspaces, runs, retries | Verified (auto) | Direct endpoints skip the workspace validation (F1) |
| Run id in `X-Conclave-Run-ID` | Verified (auto) | |
| Browser console: workspaces, run, results, prompts, history, retries, export | Verified (manual, 2026-10); Implemented, untested | No automated tests; syntax check only. Features added after 2026-10-09 (fallback controls, test-all, attempt display) have no recorded manual test |
| HTML escaping of model output | Implemented, untested | Read for this audit; no injection path found |
| Authentication | Not planned for v1.0 | Loopback-only guard is planned instead (P0-5) |
| Origin and host checks | Planned (P0-5) | |
| Progress during a run | Not planned for v1.0 (P2-4) | |

## Operations

| Capability | Status | Notes |
|---|---|---|
| CI: compile, Ruff, JS syntax, pytest | Verified (auto) | Green on the last push and on PR #1; runs Python 3.11 |
| Test isolation from real config and data | Defective | In a configured checkout the suite calls each provider once and writes two runs into the real database (F23); fix planned (P0-2). Until then, do not run `pytest` in a configured checkout |
| Keys only in environment variables | Verified (auto) | No secret found in 214 commits |
| Mock benchmark | Planned (P1-12) | |
| Adversarial injection suite | Planned (P1-2) | |
| Judge benchmark: real judges, scripted panels | Planned (P1-13) | Sets the Critic default; needs cost approval |
| End-to-end benchmark: panel vs single model | Not planned for v1.0 (P2-1) | Strongly recommended; the README must say whether it has been run |
| Inventory of local checkouts and backups | Planned (P0-0) | This session cannot reach the machine where Conclave has been run |
| Evidence that a panel beats one model | None | One real run on record; no baseline |
| Licence | Not selected | |

## Unknown

- Whether the local checkout where Conclave has been run has uncommitted or unpushed changes. See `docs/AUDIT.md` section 1 for the commands that answer it.
- Whether the configured free-tier providers still respond, and with which models.
- Behaviour on Windows of anything added after 2026-10-09.
