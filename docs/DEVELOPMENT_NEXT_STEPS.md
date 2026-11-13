# Development status and next steps

Last updated 2026-11-13. This replaces the October 24 handoff note, whose branch and runtime assumptions are out of date. It points only at files that are on `main`.

## Where things stand

The v1 pipeline is implemented on `main` and covered by tests: independent-source quorum, blind judging, positions, the Arbiter's structured output, provider error classes and fallback trails, length and prompt-size controls, the call ledger, retry chains, a bounded history, a schema version with a verified backup before upgrades, an adversarial suite for untrusted model output, and a mock benchmark of thirteen invariants. `README.md` describes what exists and what does not; `docs/CONFIGURATION.md` documents every setting.

It has **not** been run against real providers since 2026-10-09 (see `docs/TEST_LOG.md`), before most of this work.

## Remaining work, in order

1. **Real-provider acceptance run** (needs your approval of the cost; free tiers are enough). Follow `docs/MANUAL_TEST.md` on at least three providers from at least two model families, against a copy of your real database: all healthy; one delegate forced to fail with a wrong key; the primary Arbiter forced to fail so its fallback answers; two provider names on one model counting as one source; an interrupted run; one retry; saved judge prompts inspected for blinding; and ledger totals reconciled against each provider's own usage or billing page. Record the results in `docs/TEST_LOG.md` with the date, commit, providers and families.
2. **Judge benchmark** (paid; needs approval). `bench/judge/` compares the Arbiter alone with the Critic then the Arbiter on real judge models. Until it has been run there is no Critic default. Its decision rule is fixed in advance and is in `bench/judge/README.md`.
3. **Update your live checkout carefully.** It is behind `main`. Before pulling, back up `.env`, `conclave.json` and `conclave.db`. The database upgrades itself (with its own verified backup). Add `"router_alias": true` to any gateway entry that picks a model per call (for example `openrouter/free`) so it is identified by what it reports.
4. **Measure whether a panel beats one strong model**, on a small fixed set of representative questions, comparing correctness, unsupported claims, useful dissent, human correction effort, time and cost. Do not equate agreement with evidence. This has not been done, and the README says so.

## Improvements that are not needed for a first release

- A per-run cost ceiling (`max_estimated_cost_usd`) that fails closed when a cost is unknowable. Deliberately a separate change.
- One shared deadline per stage instead of one per fallback.
- Returning the run id at once and showing delegate answers while later stages run.
- Evaluating the keyword router against hand-labelled past questions.
- Native provider adapters, and semantic claim extraction.

## Open decisions (not settled; do not treat as decided)

- **Critic default.** Unmeasured; explicit choice until the judge benchmark has been run.
- **Automatic reserve delegates.** Deferred. If built: one bounded replacement wave, keep successful responses, respect a budget, and stop clearly if the quorum is unmet.
- **Spending cap.** A separate change, not part of the pipeline work.
- **Panels versus one model.** Unmeasured.
- **License.** None selected.

## Research proposals

The research roadmaps (`RESEARCH_ROADMAP_2026-10-23.md` and `RESEARCH_ROADMAP_2026-11-13.md`) are proposals with evidence limits, not approved work or implementation. The runtime-enforced delegate scope, evidence-backed Critic checks and shared findings buffer they describe are not built; the part that applies today, giving model text no authority, is covered by the adversarial suite. Tool-transport and host-permission ideas do not authorize external execution. Newsletter-derived routing stays shadow-only.

## Known limits

- A timeout result keeps the default attempt count, not an exact count of interrupted HTTP requests (the call ledger does record the abandoned request).
- Each fallback provider gets its own timeout, so a stage with several fallbacks can take longer than one timeout.
- Current account quotas, model availability and response quality need live testing with your own configuration.
