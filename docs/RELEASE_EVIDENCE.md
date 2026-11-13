# Release evidence

What is implemented, what has been verified and how, and what is partial, blocked or deferred. It does not rewrite the original audit (`docs/AUDIT.md` on the `docs/v1-audit-roadmap` branch), which stays as historical evidence. Last updated 2026-11-13. **Conclave is not release-ready**: required evidence below is missing.

## Second audit: five findings, checked against the code

| # | Finding | State | Evidence |
|---|---|---|---|
| 1 | A mid-panel cancel must keep completed answers; a cancelled slot must be recoverable and its retry must insert the result | **Already fixed**, now with a regression test | `run_panel` keeps finished delegates and records the rest as `cancelled` (PR #21). `tests/test_audit2_persistence.py::test_a_cancelled_slot_stays_recoverable_and_its_retry_inserts_the_result` cancels a real request mid-panel, checks the kept answer and the cancelled slot, then retries the slot and checks the answer is inserted and the kept one is not re-run. Also seen against real providers (`docs/TEST_LOG.md`, scenario 5). |
| 2 | Retries must persist completed work incrementally; cancelling a Critic retry during its Arbiter must keep the new Critic and the lineage | **Was a defect; fixed** (PR #26) | Retries ran as one opaque call, so the run was an empty interrupted shell. `retry_*` now take `on_stage` and the API saves each stage. `test_a_cancelled_critic_retry_keeps_the_new_critic_and_its_lineage` and `test_a_cancelled_arbiter_retry_before_it_answers_leaves_the_panel_and_critic` fail without the change and pass with it. |
| 3 | Similarity must not collapse opposing recommendations; known identity must be distinguished from suspected text overlap | **Was a defect; fixed** (PR #28) | Identical background with opposite `Conclusion:` lines was merged into one source. Now answers whose conclusions differ, that carry different numbers, or a different number of negations are not merged; a text merge is described to judges as nearly identical text that may be copying, not as a shared origin. `tests/test_audit2_dissent.py` (negation, changed numbers and hours, opposite conclusions, `no`/`a`, `without`) and the unchanged fixture set (genuine copies, light edits and padding still merge). A benchmark fixture that asserted the old behaviour was corrected. |
| 4 | Historical answers keep immutable, secret-free provenance; changing configuration must not reclassify them on a retry | **Was a defect; fixed** (PR #27) | Source and family counting on a retry used today's configuration for every answer. Each answer now stores endpoint (no credentials or query), configured model, router-alias flag and family. `test_changing_the_configuration_later_does_not_reclassify_an_unchanged_answer` changes a, b to the same model and family and a to an alias, retries c, and checks a and b are still two sources with unchanged provenance; answers saved before provenance fall back to the current configuration (tested). |
| 5 | Malformed provider metadata must be a contained failure; cancellation must still propagate | **Was a defect; fixed** (PR #27) | A non-string reported model, non-mapping usage, bad cost or attempts aborted the result or source counting. Wrong-typed metadata is dropped to unknown; non-string reply text is that delegate's `malformed` failure. 10 metadata shapes, 4 text shapes, a non-string model through source counting, and an HTTP reply with `model: 12345` and list `usage`; `test_cancellation_still_propagates_through_the_containment`. |

A merged PR is not counted as proof: each row names a test that would fail without the change (findings 2 to 5 were run without the source change to confirm; finding 1 passes without any change because it was already fixed).

## Gemini: fast alone, 60 s inside deliberations

**Diagnosis: external latency variability; not an application defect found. Uncertain: its cause on Google's side.**

- Same configured model, the real adapter, free tier. Alone: 19 s (one 503 retry, 2 attempts) for a 6-token answer; 8 s for a 98-token answer; 37.6 s for a 6,807-character prompt with a 112-token answer. Three concurrent requests: 3.8 s, 7.7 s and 15.4 s.
- Raw HTTP (no adapter, no orchestrator, no retry logic): sequential 22.6 s and 17.9 s for about 90 tokens; concurrent 3.3 s, 6.0 s and 21.6 s. No `Retry-After`, no throttle header, HTTP 200 throughout.
- So the same 3 to 22 s spread, unrelated to answer length (about 90 tokens each time), appears with the adapter bypassed. Prompt size adds to it (the 6.8 KB prompt took 38 s). Concurrency does not hurt: three at once finished no later than the slowest sequential call. Application blocking is ruled out because the concurrent calls completed at different times, and cancellation and transport behaviour show nothing (one ordinary 503 earlier). In `docs/TEST_LOG.md` the 60 s timeouts happened inside runs; a later three-provider run succeeded with a 150 s delegate timeout.
- Not done: the timeout was raised only for that retry run, as a probe, and is not offered as a fix. Further calls were avoided once the raw probe matched the adapter.
- **Next discriminating check** (not run): stream the response and log time to first byte versus total for 20 spaced calls, at different hours, against `gemini-3.6-flash` and a lighter Gemini model; if first-byte time carries the variance the delay is Google's queueing for this model on the free tier. If you want a delegate timeout that tolerates it, set `timeout_seconds` per request; Conclave does not raise it for you.

## Judge benchmark

Attempted 2026-11-13 on free-tier groq: **3 of 144 trials, no decision.** Checkpoint `bench/judge/results.jsonl`; the quota stop is in `bench/judge/operational.jsonl` and is reported apart from any score. Resume command and details: `bench/judge/RESULTS.md`. There is still no Critic default.

## Acceptance (real providers, free keys, a copy of the real database)

See `docs/TEST_LOG.md`, entries 2026-11-13. Passed: migration of a copy with its backup, wrong key (one request, not retried), Arbiter fallback with its trail, two names on one model counting once, an interrupted run kept and resumed, a linked retry chain, blind judge prompts (4 runs), and a healthy run with three providers answering (3 independent sources, two declared families, openai and google, a third answering model of another vendor). Not verified: reconciliation of the ledger against any provider's billing or usage page.

Three kinds of cost, never mixed:
- **Locally estimated**: tokens times the configured price. All prices were configured as 0 (free tiers), so every estimate is $0.
- **Provider-reported**: none of these providers was configured with `reported_cost_field` or `reported_cost_header`, so none was recorded.
- **Independently verified billing**: **unverified.** A ledger row proves a request was recorded, not what it was billed. The precise remaining manual check: open each provider's own usage page (Groq, OpenRouter, Google AI Studio, Mistral) for 2026-11-13 and compare its request and token counts with the ledger rows of the acceptance runs (`GET /api/runs/{id}/calls` in a copy of the database), and confirm the billed amount is $0.

## Status of everything else

| Area | State |
|---|---|
| P0, P1-1 to P1-12, P1-14 | Implemented and merged; covered by the suite and the mock benchmark. |
| P1-13 Critic default | Interim explicit-choice rule implemented; benchmark built, attempted, incomplete. **Partial.** |
| P1-15 real-provider acceptance | Partly passed (above). Billing reconciliation **blocked** on provider dashboards. |
| Panel versus one model | Not measured. **Deferred** (P2-1). |
| Spending ceiling, shared stage deadline, run-progress polling, router evaluation | **Deferred** (P2). |
| Release readiness | **Not complete**: missing the benchmark, billing reconciliation and the panel-versus-one measurement. |
