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

**Diagnosis: not an application defect. Two external causes, one established and one still uncertain.**

1. **Established: a free-tier limit of 20 requests per day for `gemini-3.6-flash`.** Google's own 429 body says so ("generate_content_free_tier_requests, limit: 20 ... per day limit exceeded on Free Tier ... retry in 12h36m"), with no `Retry-After` header. A day of acceptance probes alone uses that up, and then every call fails at once (Conclave classifies it `quota` and does not retry it). The 503 "high demand" replies seen on 2026-10-09 and again during this work are separate capacity events (`capacity`, retried).
2. **Uncertain: the slow successful calls.** Earlier the same day, with the real adapter and with raw HTTP (no adapter, no orchestrator, no retries), successful replies for about 90 tokens took anywhere from 3 s to 22 s, and a 6.8 KB prompt took 38 s; concurrent requests finished no later than sequential ones, with no throttle header. A streaming probe afterwards, with calls spaced 25 s apart, was consistently fast: first chunk after 3.0, 2.4 and 2.6 s, total about 3 s, before the daily limit cut it off (three 429s). So the long latencies appeared in bursts of calls close together and were absent when calls were spaced; why (server-side queuing near the limit, or load) cannot be told from the outside. The application showed no blocking: calls overlapped and completed independently, and timing is the same with the adapter bypassed.
- Not done on purpose: raising the timeout as a fix, and further calls once the daily quota was gone (they carry no information).
- **Next discriminating check** (needs a fresh daily quota, so tomorrow): 10 spaced streaming calls (at least 60 s apart, so well inside any per-minute limit and the 20 per day), logging first-chunk and total time and the HTTP status of each, then 5 back-to-back; if the spaced ones stay near 3 s and the burst ones slow down, the cause is burst handling on the free tier. Gemini on this free tier cannot serve as a benchmark judge: 216 calls would need about 11 days.

## Judge benchmark

**Complete on three judges with the repaired scorer (v2).** `qwen/qwen3.7-flash` and `deepseek/deepseek-chat-v3-0324` (two Arbiter prompts each) and `anthropic/claude-sonnet-4.6` (144 of 144 trials per set; about $2.8 of OpenRouter spend in all, per the key's own usage counter): the Critic arm moved -1.3 to +1.3 points, all "default off" by the fixed rule, and was slightly worse with Sonnet (Arbiter alone 99.4%). Screening results; the first scorer was unfair in four ways (found by an independent audit) and was repaired and every trial rescored, original scores kept. Both judges, in both arms, scored 0 of 12 on acknowledging a missing delegate and almost never noticed duplicate sources: a finding about the Arbiter's prompt. After the prompt change (PR #36, re-run on both judges for about $0.21) the missing-delegate class is 12 of 12 and the Arbiter-alone score about 98%, and the Critic is still "default off" (+1.3 qwen, +0.6 deepseek). groq (free tier): 6 of 144, incomplete, no decision. Outages are in `bench/judge/operational.jsonl`, apart from the scores. Details: `bench/judge/RESULTS.md`. There is still no Critic default.

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
| P1-13 Critic default | Interim explicit-choice rule implemented; benchmark run to completion on three judges (all sets "default off"); a stronger judge and the prompt change are still to do. **Partial.** |
| P1-15 real-provider acceptance | Partly passed (above). Billing reconciliation **blocked** on provider dashboards. |
| Panel versus one model | Not measured. **Deferred** (P2-1). |
| Spending ceiling, shared stage deadline, run-progress polling, router evaluation | **Deferred** (P2). |
| Release readiness | **Not complete**: missing the benchmark, billing reconciliation and the panel-versus-one measurement. |
