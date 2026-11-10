# Conclave — v1.0 release criteria

Written 2026-11-10. v1.0 is released when every box below is ticked on the commit being tagged. Each criterion is checkable by a command, a test, or a recorded manual result. Roadmap item numbers refer to `docs/ROADMAP-TO-V1.md`.

Nothing here is ticked yet. `docs/IMPLEMENTATION-STATUS.md` records where each one stands.

## Repository

- [ ] The application is on `main` and `main` is the only long-lived branch. (P0-1)
- [ ] `main` requires the CI `test` check before merging.
- [ ] No API key, `.env`, `conclave.json`, database or run log is in the history: a scan of all commits for key patterns and those file names returns nothing.
- [ ] The release commit is tagged `v1.0.0` and `pyproject.toml` says `1.0.0`.

## Automated checks

- [ ] `pytest -q` passes with no failures and no skipped test that lacks a stated reason.
- [ ] Line coverage of `src/conclave` is at least 90%, and no file is below 80%.
- [ ] `ruff check src tests` passes.
- [ ] `node --check web/app.js` passes.
- [ ] The mock benchmark (`tests/benchmark`) passes on every fixture. (P1-7)
- [ ] CI runs all of the above on the Python version named in the README.

## Data integrity

- [ ] Cancelling a run during the panel, the Critic or the Arbiter leaves a stored run containing every stage that had finished, with status `interrupted`. (P0-2)
- [ ] A database created by `c2285d6` opens under v1.0 with all its workspaces and runs readable. (P1-6)
- [ ] For any chain of retries, the reported cumulative cost equals the sum of every stage cost in the chain. (P1-5)
- [ ] A second retry of a run that is already being retried returns 409. (P1-5)

## Honest orchestration

- [ ] An empty or whitespace-only answer is recorded as failed and does not count toward quorum. (P0-5)
- [ ] The same delegate cannot appear twice in a run through any endpoint. (P0-5)
- [ ] When any delegate did not answer, the Critic and Arbiter prompts state how many answered and which did not. (P1-1)
- [ ] A run with one successful delegate is marked single-source and does not call the Critic. (P1-1)
- [ ] A delegate answer containing the block markers cannot create an extra delegate block or a Critic section in a downstream prompt. (P0-3)
- [ ] Every Arbiter result has four parsed sections (common ground, disagreements, uncertainty, synthesis) or is marked `format_ok: false` with the raw text shown. (P1-2)
- [ ] Identical inputs produce byte-identical prompts.

## Provider resilience

- [ ] Authentication errors, quota exhaustion and other 4xx responses are sent once and reported with their kind. (P1-3)
- [ ] Rate limits, 502/503/504 and refused connections are retried within the configured bound. (P1-3)
- [ ] When a fallback is used, the saved result lists the earlier failed attempts. (P1-3)
- [ ] A prompt longer than a provider's configured limit is not sent to it. (P1-4)
- [ ] A missing API key makes that provider unavailable and leaves the application running.

## Security

- [ ] A state-changing request with a foreign `Origin`, or a `Host` other than loopback, is refused unless the host is explicitly allowed. (P0-4)
- [ ] No model-derived string reaches the page except through `textContent` or `escapeHtml`.
- [ ] API keys appear in no response, stored run, or run log. Verified by a test that runs a deliberation with a known fake key and searches all three.
- [ ] The README states that Conclave has no login, must stay on loopback, and stores prompts and responses in plain text.

## Operation

- [ ] The history list returns at most 200 summaries per request and its size does not depend on prompt or response length. (P1-6)
- [ ] A fresh clone reaches a working demo run using only the README: create environment, install, start, open the console, run with the demo providers.
- [ ] A real-provider acceptance run on at least three providers is recorded in `docs/TEST_LOG.md` with date, commit and outcome for: all healthy; one delegate failing; Arbiter fallback used; an interrupted run resumed; one retry. (P1-9)

## Product decision

- [ ] The Critic's default is set by one of: the real-model benchmark result with the decision rule in `docs/AUDIT.md` section 4 applied, or "off" if that benchmark was not approved. The choice and its basis are written in the README.
- [ ] `docs/IMPLEMENTATION-STATUS.md` has no row marked planned or untested for a v1.0 capability.

## Explicitly not required for v1.0

Blinded delegate labels, similarity flags, a cost ceiling, a shared stage deadline, console progress, routing evaluation, and everything under P3. Their absence does not block the release.
