# Conclave — v1.0 release criteria

Revision 2, 2026-11-10. v1.0 is released when every box below is ticked on the commit being tagged.

**How a box gets ticked.** A box is ticked only with evidence written beside it: the name of the test that proves it, a CI run link, or a dated `docs/TEST_LOG.md` entry. A box without evidence is not ticked.

**References.** Item numbers refer to `docs/ROADMAP-TO-V1.md`, revision 2. Invariants I1–I8 are defined there. Nothing here is ticked yet; `docs/IMPLEMENTATION-STATUS.md` records where each one stands.

## 1. Existing work is protected

- [ ] **Inventory.** The read-only inventory in P0-0 has been run on every machine with a Conclave checkout. The owner has reviewed the output, and it is logged in `TEST_LOG.md` with date and machine names only. (P0-0)
- [ ] **Local commits.** Every local-only commit found is reachable from a remote branch. (P0-0)
- [ ] **Installation backup.** `conclave.json`, `.env`, `conclave.db` and `run_logs/` were copied outside the checkout before any merge, branch change or upgrade on that machine. (P0-0)
- [ ] **Remote history.** No force-push, history rewrite or branch deletion happened without explicit approval recorded in the pull request where it was done. Each one was preceded by a backup branch or tag.
- [ ] **Merged history.** `git merge-base --is-ancestor origin/feature/mvp-scaffold origin/main` succeeds, and every `rescue/*` branch is merged or explicitly kept. (P0-1)

## 2. Repository

- [ ] **Branch protection.** `main` requires the CI `test` check before merging. (P0-1)
- [ ] **No secrets in history.** A scan of every commit for API-key patterns and for `.env`, `conclave.json`, database and run-log files finds nothing.
- [ ] **Tag and versions.** The release commit is tagged `v1.0.0`. `pyproject.toml`, the FastAPI app version and the result `schema_version` match it.

## 3. Test safety and automated checks

- [ ] **Canary.** The P0-2 canary passes in CI. Run in a synthetic configured directory (a fake `conclave.json` pointing at a recording listener, a fake `.env`, a `conclave.db` with known row counts), the suite makes zero requests, changes no row and creates no file, and passes. (P0-2)
- [ ] **Order of use.** No test was run against the real installation before the canary had passed in CI. (P0-2)
- [ ] **Suite.** `pytest -q` passes. Any skipped test states its reason.
- [ ] **Coverage.** Line coverage of `src/conclave` is at least 90%, and no file is below 80%.
- [ ] **Lint and syntax.** `ruff check src tests` passes, and `node --check` passes on every file in `web/`.
- [ ] **Rendering tests.** `node --test web/` passes. (P1-2)
- [ ] **Mock benchmark.** The mock benchmark passes every fixture, with no expected failures. (P1-12)
- [ ] **Injection suite.** The adversarial suite passes every fixture on every path. (P1-2)
- [ ] **Python versions.** CI runs all of the above on the README's Python version and on the version used for the acceptance run. (P1-14)

## 4. Independence and corroboration (I1, I2)

- [ ] **No sharing.** No delegate prompt contains any other model's output. Checked in the mock benchmark.
- [ ] **Empty answers.** An empty or whitespace-only answer is recorded as failed, kind `empty_response`. (P0-6)
- [ ] **Duplicate names.** The same provider name cannot appear twice among a run's delegates through any endpoint. (P0-6)
- [ ] **One source per model.** Delegates with the same configured identity, the same normalized reported model, or unresolved router aliases on one host form one source. (P0-6)
- [ ] **Copies.** Near-verbatim answers form one source. The P1-4 pair fixtures classify as specified: copies merge, and different models' paraphrases do not. (P1-4)
- [ ] **Independent counts everywhere.** Quorum, `single_source`, the "k of n" disclosure, the console and the judge prompts all use `independent_source_count`, never raw successes. (P0-6, P1-1)
- [ ] **Agreement wording.** Every judge prompt and every result view states that agreement is not evidence of correctness. No label, prompt or document describes agreement as verification. (P1-4, P1-14)
- [ ] **Model families.** When `family` is configured, the console shows the count of distinct model families. (P1-4)

## 5. Blind judging (I7)

- [ ] **No identities.** No configured provider name, configured model, reported model, latency, token count, cost or error text appears in any Critic or Arbiter prompt, across every mock and injection fixture. (P1-3)
- [ ] **Order.** Response order comes from the run seed. It differs between seeds and is identical across every retry in a chain. (P1-3, P1-10)
- [ ] **Judge overlap.** A judge sharing a source with a delegate is recorded in `judge_overlaps` and shown in the console. (P1-3)
- [ ] **Real prompts.** The acceptance run confirms blinded judge prompts on real providers. (P1-15)

## 6. Dissent, absence and uncertainty (I4, I5)

- [ ] **Positions.** Every result carries a position row (conclusion and confidence, or "not stated") for every delegate. The console shows all of them above the synthesis, whatever the Arbiter wrote. (P1-5)
- [ ] **Missing delegates.** When any delegate did not answer, both judge prompts state how many answered, how many independent sources there are, and the failure kind of each missing slot, without provider names or error bodies. (P1-1)
- [ ] **Single source.** A single-source run is labelled and never calls the Critic. It follows the workspace's explicit `single_source_mode`. (P1-1)
- [ ] **Structured synthesis.** Every Arbiter result has four parsed sections or `format_ok: false` with the raw text shown. Citations to nonexistent labels are listed. (P1-6)
- [ ] **Insufficient evidence.** `insufficient_evidence` is set by the rules in P1-5 and shown above the synthesis. (P1-5)

## 7. Model output is untrusted data (I3, I6)

- [ ] **Containment.** No byte of model output appears in a later prompt outside its own marker pair, across the whole corpus. (P0-4, P1-2)
- [ ] **Instruction sentence.** Both judge prompts carry the fixed untrusted-data sentence, and the workspace-context caveat. (P0-4)
- [ ] **Flooding.** Every response in a judge prompt is capped at the same limit with a visible truncation note. Stored raw answers are never truncated. (P0-4)
- [ ] **Control-flow invariance.** For every fixture in all 11 attack classes, the orchestration trace (providers called, order, call count, statuses, counts, flags, saved rows, ledger rows) equals that of its benign control. (P1-2)
- [ ] **Parser isolation.** Only Arbiter output is parsed for sections. Injected headings yield `format_ok: false`, never wrong sections. (P1-2, P1-6)
- [ ] **Rendering.** No model-derived string reaches the page except through the tested render helpers. Every markup and script fixture renders as text. (P1-2)
- [ ] **Secret hygiene.** A fake API key appears in no prompt, stored run, run log or API response. (P1-2)
- [ ] **Raw preservation.** Raw prompts, answers and errors are stored byte for byte as sent and received.
- [ ] **Stated limit.** The README states that these tests show Conclave gives model text no authority, and do not show that judge models resist persuasion. It quotes the measured rates. (P1-13, P1-14)

## 8. Data integrity

- [ ] **Interrupted runs.** Cancelling during the panel, the Critic or the Arbiter leaves a stored run containing every stage that had finished, with status `interrupted`. (P0-3)
- [ ] **Reproducible prompts.** Rebuilding any stage prompt from a stored run reproduces it byte for byte. (P0-4)
- [ ] **Lineage.** Every retry records `parent_run_id` and `chain_root_id`. (P1-10)
- [ ] **One retry at a time.** A second retry within a chain that is already retrying gets 409. (P1-10)
- [ ] **Succeeded delegates.** Re-running a delegate that succeeded requires `force`. (P1-10)
- [ ] **Migration.** A copy of a database created by `c2285d6` migrates under v1.0, writes a backup first, and keeps all workspaces and runs readable. (P1-11)
- [ ] **No silent migration.** No migration runs on an existing database without writing a backup. (P1-11)

## 9. Cost accounting (I8)

- [ ] **One row per request.** Every request the fake transport receives, including HTTP retries, fallbacks, failed and timed-out calls, stage retries and connectivity tests, has exactly one ledger row. (P1-9)
- [ ] **Run totals.** Per-run totals equal the sums over that run's ledger rows. (P1-9)
- [ ] **Chain totals.** Per-chain totals equal the sums over every row in the chain. (P1-9, P1-10)
- [ ] **Three terms.** Estimated, provider-reported and billed are distinct. Estimates are labelled "estimated". Provider-reported figures come only from a configured field or header and are labelled with their coverage. Billed cost is never shown or implied. (P1-9)
- [ ] **Unknown is not zero.** A call with unknown usage or price is counted as unpriced, and timeouts are marked possibly billed. (P1-9)
- [ ] **Reconciliation.** The acceptance run reconciles ledger totals against each provider's own usage or billing page and records the difference. (P1-15)

## 10. Provider resilience

- [ ] **Single attempts.** `auth`, `quota`, `bad_request`, `malformed` and `empty_response` errors are sent once, with their kind recorded. (P1-7)
- [ ] **Bounded retries.** `rate_limit`, `capacity` and refused connections are retried within the configured bound. (P1-7)
- [ ] **Fallback trail.** When a fallback is used, the result lists every earlier failed attempt. (P1-7)
- [ ] **Prompt size.** A prompt longer than a provider's `max_prompt_chars` is never sent to it. (P1-8)
- [ ] **Missing key.** A missing API key makes that provider unavailable and leaves the application running.

## 11. Security

- [ ] **Loopback guard.** A state-changing request with a foreign `Origin`, or a `Host` other than loopback, is refused unless the host is explicitly allowed. (P0-5)
- [ ] **README warning.** The README states that Conclave has no login, must stay on loopback, and stores prompts and responses in plain text. (P1-14)

## 12. Operation

- [ ] **Bounded history.** The history list returns at most 200 summaries per request, and its size does not depend on prompt or response length. (P1-11)
- [ ] **Fresh clone.** A fresh clone reaches a working demo run using only the README.
- [ ] **Acceptance run.** A real-provider acceptance run on at least three providers from at least two model families is recorded in `TEST_LOG.md`, with all eight P1-15 scenarios passed. (P1-15)

## 13. Evidence and product decisions

- [ ] **Critic default.** Exactly one of these is true and written in the README with its basis:
  - The Critic default comes from `bench/judge/RESULTS.md`, with the fixed P1-13 rule applied.
  - The result was inconclusive or the benchmark was not approved, and workspace creation requires an explicit Critic choice.

  No other default is allowed. (P1-13)
- [ ] **Critic stays optional.** The Critic can be turned off for any workspace, whatever the default.
- [ ] **Panel claim.** The README states whether the end-to-end panel-versus-single-model benchmark (P2-1) has been run, and does not claim that panels beat one model unless it has. (P1-14)
- [ ] **Limitations.** The README's limitations section covers every point listed in P1-14. (P1-14)
- [ ] **Status complete.** `docs/IMPLEMENTATION-STATUS.md` marks every v1.0 capability verified. Provider rows outside the acceptance run may read "supported by the adapter, not verified". (P1-14)

## Explicitly not required for v1.0

- A cost ceiling, a shared stage deadline, console progress, orchestrator consolidation and routing evaluation (P2-2 to P2-6).
- The end-to-end benchmark (P2-1). Not running it is allowed only if the README says so.
- Everything under P3.
- Any integration with another project.
