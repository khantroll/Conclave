# Conclave — independent audit

- Date: 2026-11-10.
- Implementation audited: branch `feature/mvp-scaffold` at `c2285d6` (2026-10-24). All file and line references below are to that commit.
- This document lives on a docs branch cut from `main`, so the code it cites is not in the same tree until the implementation is merged.
- Method: read every source file (`src/conclave`, 1,500 lines; `web/app.js`), ran the CI steps locally, and wrote 16 throwaway tests in a scratch directory outside the repo using fake providers only, and ran the suite once beside a config pointing at a local stand-in server (F23). No provider was called, no credit was spent, and no application code was changed.

Each finding is labelled:

- **Confirmed** — reproduced by a test I ran.
- **Code-level risk** — visible in the code, not exercised.
- **Architectural** — a design property, not a bug.
- **Hypothesis** — plausible, not verified here.

## 1. Where the implementation is

| Branch | Commits | Last commit | Contents |
|---|---|---|---|
| `main` | 6 | `cf425b8`, 2026-10-24 | README, `docs/ARCHITECTURE.md`, `docs/MVP.md`, `docs/RESEARCH_ROADMAP_2026-10-23.md`. No code. |
| `feature/mvp-scaffold` | 212 | `c2285d6`, 2026-10-24 | The application: FastAPI backend, browser console, provider adapter, SQLite store, orchestrator, tests, CI. |

- The branches share `8e06ca8` as their base. `main` is 2 commits ahead (a README link and the research roadmap); the feature branch is 208 ahead.
- There is one pull request: #1, draft, `feature/mvp-scaffold` → `main`, 39 files, +5,108/−40. GitHub reports it mergeable. A local merge simulation (`git merge-tree`) completes with no conflict.
- CI (`.github/workflows/test.yml`) passed on the last push and on the PR, 2026-10-24.
- No other branches, tags or forks exist on the remote.

**Most complete tested implementation: `feature/mvp-scaffold` at `c2285d6`.** Reproduced locally on Python 3.13: 66 tests pass, Ruff clean, `compileall` clean, `node --check web/app.js` clean, 93% line coverage of `src/conclave`.

**Local installation: not verified.** This audit ran in a cloud workspace with no access to the machine where Conclave has been run. Whether that checkout has uncommitted or unpushed work is unknown. The handoff note on the feature branch says the same. To settle it, run these on that machine, in the Conclave checkout, before anything is merged:

```
git status --short
git stash list
git fetch origin
git log --oneline origin/feature/mvp-scaffold..HEAD
git branch -vv
```

Any output from the first, second or fourth command is work that exists only locally. `conclave.json`, `.env`, `conclave.db` and `run_logs/` are ignored by design and are expected to exist only there.

## 2. What the code does

A request runs as: analyze (keyword rules) → optional delegate selection → parallel delegate calls with a timeout each → quorum check → Critic (optional, with fallbacks) → Arbiter (with fallbacks) → save the run and write a JSON log. Every stage records the exact prompt, the raw response, model, latency, usage and attempts. Any stage can be re-run later from the saved request snapshot.

That matches the stated purpose on orchestration and inspectability. It falls short on three parts of the purpose: independence is assumed rather than checked, disagreement exists only as free text the Arbiter is asked to write, and nothing ties a statement in the synthesis back to the delegate it came from.

## 3. Findings

### Independence and correlated answers

**F1. Independence is not enforced or measured. Architectural, partly confirmed.**
- The direct endpoint accepts the same provider twice and counts two successes toward quorum. Confirmed: `delegates: ["demo-a", "demo-a"]` with `minimum_successes: 2` returns `successful_count: 2`. Only the workspace path rejects duplicates (`api.py:388-389`).
- Two differently named providers may point at the same model, or at two models from one vendor. Nothing compares `base_url`, `model` or vendor.
- The Critic and Arbiter may also be delegates. The console warns; the API allows it.
- Nothing measures how similar the delegate answers are. Three near-identical answers look the same to the pipeline as three independently reasoned ones.

**F2. The Arbiter and Critic see each delegate's provider name and model. Code-level risk.** `prompts.py:41` writes `--- Delegate 1: groq (openai/gpt-oss-120b) ---`. A judge model that knows which answer came from which vendor, or from itself, can weight by reputation instead of content. Order is also fixed by workspace order.

### Consensus, synthesis and disagreement

**F3. An empty answer is a success. Confirmed.** A provider that returns `""` or whitespace is recorded as `succeeded` (`orchestrator.py:319-329`) and counts toward quorum. Two empty answers satisfied `minimum_successes: 2` and the Arbiter ran on nothing.

**F4. The Arbiter is not told what is missing. Confirmed.** Failed delegates are dropped from the prompt and the survivors are renumbered (`prompts.py:33-43`). With one of three delegates failed, the Arbiter prompt contains no mention of a failure. The synthesis cannot say "one delegate did not answer", and "common ground" may be the view of two.

**F5. One surviving answer still gets a Critic and an Arbiter. Confirmed.** Quorum defaults to 1 (`models.py:60`). With a single successful delegate the pipeline still calls the Critic and the Arbiter, which can only restate that answer under headings such as "common ground".

**F6. Disagreement is requested, never checked. Architectural.** The four sections (common ground, disagreements, uncertainty, synthesis) are an instruction in the prompt (`prompts.py:96-101`). The response is stored as one string. Nothing verifies the sections exist, nothing records which delegate a claim came from, and there is no state for "insufficient evidence to answer".

### Cost and unnecessary calls

**F7. A question judged "simple" costs three calls. Confirmed.** With auto-selection on, the analyzer returns one delegate for a simple question with the rationale "a single model is likely sufficient; a panel would add overhead" (`analyzer.py:68-75`). The workspace path then runs that delegate, the Critic and the Arbiter. Observed stages: `demo-a`, `demo-critic`, `demo-arbiter`.

**F8. Context is paid for in every stage. Architectural.** With N delegates, context C, answers of length L and a critique K, input is roughly `N·C` for the panel, `C + N·L` for the Critic and `C + N·L + K` for the Arbiter. For three delegates that is five calls and about five copies of the context, against one call for a single model. Measured storage effect: a run with a 4 KB context saves as 23.7 KB because the context is stored five times.

**F9. No length, sampling or budget controls. Confirmed.** The request body is `model` and `messages` only (`providers/openai_compatible.py:57-60`). No `max_tokens`, `temperature` or `seed` is sent, there is no check that the Arbiter prompt fits the model's context window, and there is no per-run cost ceiling. "Deterministic" describes the orchestration; the model outputs are not reproducible.

**F10. Retry totals drop the calls they replaced. Confirmed.** After an Arbiter retry and then a Critic retry, `estimated_cost_usd` was 0.09 each time; actual spend in that test was 0.21. The total is recomputed from the surviving results only (`orchestrator.py:249-256`).

### Provider errors and partial failure

**F11. Quota exhaustion is retried like a rate limit. Confirmed.** A 429 carrying `insufficient_quota` and `Retry-After: 3600` was sent three times with two 10-second sleeps (`providers/openai_compatible.py:79`, `142-157`). There is no distinction between "slow down", "out of credit", "bad key" and "model overloaded".

**F12. A refused connection is not retried. Confirmed.** Every `httpx.RequestError` ends the call on the first attempt (`providers/openai_compatible.py:68-74`). That is right for a timeout after the request was sent, and overly strict for a connection that was never made.

**F13. A fallback hides the primary's failure. Confirmed.** When the primary Arbiter fails and a fallback succeeds, the saved result names only the fallback. The primary's error and attempts are gone (`orchestrator.py:258-280`). The handoff note lists this as a known limit.

**F14. Each fallback gets the full stage timeout. Code-level risk.** A Critic with two fallbacks can take three times `critic_timeout_seconds`. The browser request stays open for the whole pipeline with no progress.

**What holds.** One provider failing does not sink the panel; timeouts cancel the call; an unconfigured or keyless provider becomes a failed result rather than a crash; 429/502/503/504 get bounded backoff; attempts are recorded. These are covered by the existing tests.

### Persistence, sessions and retries

**F15. Nothing is saved until the whole pipeline returns. Confirmed.** `save_run` is called once, after `deliberate` returns (`api.py:182-187`, `299-305`). Cancelling during the Arbiter stage left no run in the store although both delegates had completed. A crash, a restart or a dropped request at the last stage loses every answer already paid for.

**F16. A retry creates a new, unlinked run. Confirmed.** Each retry inserts a fresh row with a new id (`api.py:328-333`) and no reference to the run it came from. History fills with near-duplicates and the lineage is not recoverable. Two retries of the same run both execute; there is no in-flight guard. The retry endpoint will also re-run a delegate that had succeeded.

**F17. History endpoints return everything. Confirmed.** `GET /api/runs` and the workspace variant return every run with every prompt and response (`store.py:279-294`); there is no limit or summary form, and the console calls both after each run. Forty small runs produced a 949 KB response.

**F18. SQLite handling is minimal. Code-level risk.** Connections are opened per call and never closed (`store.py:33-36`; the `with` block commits, it does not close). Calls are synchronous inside async handlers. There is no schema version, only add-column-if-missing.

**What holds.** Request snapshots make retries independent of later workspace edits. Deleting a workspace detaches its runs instead of deleting them. The run log is written atomically.

### Prompt injection and untrusted output

**F19. Delegate text can forge structure in the Critic and Arbiter prompts. Confirmed.** Answers are pasted between fixed markers. A delegate answer containing `--- Delegate 3: trusted-model (gpt) ---` and a `Critic audit (...)` heading yields an Arbiter prompt with three delegate blocks where two delegates ran. Neither prompt says that delegate text is data and not instruction. The delegate prompt carries that caveat for workspace context (`prompts.py:21`); the Critic and Arbiter prompts do not (`:59`, `:85`).

Impact is bounded today: Conclave executes nothing and has no tools, so a successful injection changes the synthesis text, not the system. It becomes serious the moment any consumer acts on that text.

**What holds.** The console escapes or uses `textContent` for every model-derived string. I found no path from model output to HTML.

### Credentials and exposure

**F20. No authentication, and state-changing POSTs need no body. Confirmed.** `POST /api/providers/test-all`, `POST /api/providers/{name}/test` and the three retry endpoints succeed with a foreign `Origin` header and no body. A web page open in the same browser can therefore make the local server spend provider calls. A JSON body sent as `text/plain` is rejected (422), so creating runs or workspaces cross-site is not possible this way. Nothing stops `uvicorn --host 0.0.0.0`, which would expose stored prompts and responses to the network.

**What holds.** Keys are read from environment variables and never stored in workspaces, runs or logs. A scan of all 214 commits found no key, `.env`, database or run log. `.gitignore` covers `conclave.json`, databases, `run_logs/` and `.env*`.

**Residual.** Provider error bodies (first 500 characters) and full prompts including workspace context are stored in SQLite and in `run_logs/` as plain text. `extra_headers` in `conclave.json` can hold secrets and is not masked anywhere.

### Routing and model-specific prompting

**F21. Routing is keyword matching with no evidence behind it. Architectural.** Complexity and capability come from regular expressions (`analyzer.py`); "why" marks a question as analytical. Selection is a deterministic sort on tag matches and priority (`selection.py`). It is predictable and cheap, which is its merit. No run has compared its choices with a fixed panel.

**F22. "Model-specific" means a role string and a system prompt. Architectural.** There are no per-model parameters, no context-length awareness and no handling of responses where content is a list or the answer sits in a reasoning field; those become "non-text content" failures.

### Tests and maintainability

**F23. Running the tests uses the real configuration and the real database. Confirmed.** `tests/test_api.py:3-6` imports the module-level `app`, which loads `conclave.json` and `.env` from the working directory and opens `conclave.db` and `run_logs/` there (`api.py:50-51`, `103-106`, `426`). Two effects:

- Every `pytest` run writes two fake runs ("Should Conclave survive partial failures?", "test") into the default database and two files into `run_logs/`. Reproduced in a clean checkout.
- `test_all_configured_providers_endpoint` posts to `/api/providers/test-all`. With a `conclave.json` naming two providers at a local stand-in server, the suite sent one chat-completion request to each, and two tests failed (`test_health` expects zero configured providers). On a machine with real providers configured, running the tests therefore calls each of them once and cannot pass.

CI is unaffected because it has no `conclave.json`.

- 66 tests, all against fakes. Line coverage 93%; the lowest file is `analyzer.py` at 78%.
- The browser console (643 lines) has a syntax check and no tests.
- Nothing after `4b5d72c` (2026-10-09) has been run against a real provider: bounded retries, Critic/Arbiter fallbacks, HTTP-date backoff and the run logs are verified with fakes only.
- CI lint is limited to error classes (`E4`, `E7`, `E9`, `F`).
- The code is small, typed and readable. `orchestrator.py` repeats the Critic-then-Arbiter block four times; that is the one obvious consolidation.
- Documentation overlaps: `README.md`, `docs/MVP.md` and `docs/ARCHITECTURE.md` differ between the two branches, and the feature branch's handoff note points at a roadmap file that exists only on `main`.

## 4. Does the panel beat one strong model?

**There is no evidence either way in this repository.** The test log records one successful real run (2026-10-09, free-tier models, roles reassigned to whatever was responding) and says itself that the value of the Critic and Arbiter "still needs repeated comparison". No baseline, no fixed question set and no scoring exist.

What can be said from the design:

| Dimension | Assessment |
|---|---|
| Human effort saved | The one benefit that does not depend on answer quality. One question, parallel dispatch, answers side by side, saved. This is working. |
| Correctness and completeness | Unmeasured. A panel helps when delegates fail differently. Agreement between models trained on similar data is weak evidence, and F1 means Conclave cannot tell the two cases apart. |
| Preservation of uncertainty | Prompt-only (F6). It depends on the Arbiter model following instructions. |
| Recognition of disagreement | Same. Reduced further when failures are hidden (F4) or one answer survives (F5). |
| Evidence quality | No retrieval, no citations, no checking. Models assert; the Arbiter weighs assertions. |
| Diversity | Whatever the workspace author configured. Not checked. |
| Latency | Slowest delegate, plus Critic, plus Arbiter, in sequence. Roughly three model round-trips where a single model takes one. |
| Cost | At least `N + 2` calls and about `N + 2` copies of the context (F8). |

**Critic versus no Critic.** The Critic is one extra sequential call whose output the Arbiter may ignore. Its value is an empirical question that the benchmark below answers directly. Until then it should be treated as optional.

### Benchmark design

**Stage A — deterministic mocks, no cost.** This cannot measure answer quality, because the Arbiter is a mock too. It measures whether the pipeline preserves what a good synthesis needs. Fixed fixtures, scripted fake providers, assertions on prompts and results:

1. *Dissent reaches the Arbiter.* Two delegates agree, one dissents with a marker string; the marker must be in the Arbiter prompt.
2. *Failure is disclosed.* One of three fails; the Arbiter prompt must state how many answered. (Fails today, F4.)
3. *Single source is labelled.* One survivor; the result must be flagged single-source and the Critic skipped. (Fails today, F5.)
4. *Empty is not success.* (Fails today, F3.)
5. *Forged blocks are neutralised.* A delegate answer containing the block markers must not produce an extra delegate block. (Fails today, F19.)
6. *Correlated answers are flagged.* Three identical answers must set a similarity flag. (No such flag today, F1.)
7. *Call count and token budget.* For each fixture, assert the number of provider calls and total prompt characters. (Simple question: three calls today, F7.)
8. *Nothing paid for is lost.* Cancel at each stage; completed stage results must be in the store. (Fails today, F15.)
9. *Retry accounting.* Cumulative cost equals the sum of all calls made. (Fails today, F10.)

About 20 fixtures in one JSON file and one test module. Runs in CI in under a second. It turns the findings above into regression gates.

**Stage B — real models, only with explicit cost approval.**

- 30 questions with checkable answers, fixed in a file: 10 factual with one correct answer, 10 where the correct response is "cannot be determined from what is given", 10 multi-step reasoning or code-review items with a known flaw.
- Four arms on the same questions: (1) the strongest single configured model; (2) panel + Arbiter, no Critic; (3) panel + Critic + Arbiter; (4) the same model three times + Arbiter, to separate model diversity from mere repetition.
- Score each final answer blind to its arm: correct or not; for the "cannot be determined" set, whether it said so; count of unsupported claims; whether a real disagreement among delegates appears in the synthesis.
- Record wall time, calls, tokens and cost from the run logs.
- Decision rules, fixed in advance. Keep the Critic on by default only if arm 3 beats arm 2 by at least 3 of 30 correct or halves unsupported claims. Keep panels as the default only if arm 2 or 3 beats arm 1 by at least 3 of 30. If arm 4 matches arm 2, the benefit comes from repetition and diversity adds nothing measurable.
- Size: about 330 provider calls. On the free tiers already configured this costs nothing but will hit rate limits and take several sessions. On paid mid-tier models, a rough estimate is a few dollars; compute it from the provider's current prices before approving. Thirty questions is a screening result, not proof.

### Smallest implementation that keeps the unique value

1. One question to N delegates in parallel, each with its own timeout.
2. Raw answers side by side, with exact prompts, saved.
3. One Arbiter pass that must return labelled sections, told how many delegates answered and which did not.
4. Honest labels: single-source, near-identical answers, empty answers.
5. Retry of a failed stage.

Everything else is optional for v1.0: the Critic stays as a switch, auto-selection stays off by default, fallbacks stay.

## 5. Future integration

Current interfaces: a REST API returning the full result as JSON with the run id in a header, and an importable `Orchestrator` class that needs only a mapping of provider objects.

- Usable today by another program for "ask a panel, get text back". The orchestrator has no dependency on FastAPI or SQLite, which is the right seam.
- Not ready as a dependency: the call blocks for the whole pipeline, there is no authentication, the final answer is free text with no machine-readable verdict, and F19 means a consumer would be acting on text an upstream model can steer.

Per project, as optional and advisory only:

| Project | Fit | Condition |
|---|---|---|
| Hail, Tank | Plausible callers of a "second opinion" endpoint | Must work unchanged when Conclave is absent or times out |
| LineageForge | Possible for weighing conflicting records | Only with source text supplied in context; Conclave has no evidence handling |
| ForgeBridge | Weak fit | Conversion work is deterministic; a panel adds cost without a clear gain |
| AgentTrade | Advisory input to analysis at most | Must never size, place, block or release an order, and must never override stops, caps or the reconciliation gate |

Nothing in v1.0 should be added for these. The one v1.0 item that also serves them is structured Arbiter output, which is needed for Conclave's own purpose.

## 6. Repository readiness

- **Should the implementation merge into `main`? Yes.** The default branch does not contain the application, which is the largest integrity problem in the repository. The merge is clean and CI is green.
- **Blockers before merging:** confirm the local checkout has no unpushed work (section 1).
- **Not blockers:** the findings above. They are better fixed in small pull requests against `main` than on a 208-commit branch.
- **Secrets:** none found in history.
- **Documentation conflicts:** `README.md`, `docs/MVP.md` and `docs/ARCHITECTURE.md` differ between branches; git merges them without conflict, and the result should be read once after merging. The four documents in this pull request are new files and collide with nothing.
- **Author name:** three commits (`cf425b8`, `4a0a13a` on `main`; `c2285d6` on the feature branch) carry a personal name where the other 211 carry `khantroll`. Changing them means rewriting history and force-pushing. Decide before merging if it matters; it is far harder afterwards.
- **No licence** is selected. Fine for a private repository; decide before any sharing.

**Safe sequence** (nothing here has been done; each step needs approval):

1. Run the local checks in section 1. Push anything found to `feature/mvp-scaffold`. Do not run `pytest` in that checkout until F23 is fixed; use a fresh clone with no `conclave.json`.
2. Merge this documentation pull request into `main`.
3. Update `feature/mvp-scaffold` from `main` (merge, not rebase, to keep the 208 commits' hashes) and confirm CI.
4. Mark PR #1 ready and merge it with a merge commit. Tag the result `v0.1.0`.
5. Add branch protection on `main` requiring the `test` check.
6. Keep `feature/mvp-scaffold` until v1.0 is tagged, then delete it.
7. Do all roadmap work as short-lived branches from `main`.

## 7. Final recommendation

1. **Is the architecture worth preserving?** Yes. A provider interface, an orchestrator that depends only on it, a store, and a thin API is the right shape and the right size. Nothing found needs a rewrite or a new dependency.
2. **What is genuinely working?** Parallel dispatch with per-delegate timeouts; partial success; bounded retry on transient HTTP errors; Critic and Arbiter stages with fallbacks; exact prompt and raw response capture; workspaces; saved runs with request snapshots; stage retries; JSON run logs; the console. All verified with fakes. One real end-to-end run is on record from 2026-10-09; nothing since has been run live.
3. **What threatens reliability or correctness?** Paid work lost if the last stage dies (F15). Empty answers and duplicate delegates counted as independent successes (F1, F3). The Arbiter not told what failed (F4). Forged structure from delegate text (F19). Unauthenticated endpoints that spend calls (F20). Unbounded history responses (F17). A test suite that calls real providers and writes into the real history when run in a configured checkout (F23).
4. **Is the Critic/Arbiter design providing measurable value?** Unknown, because nothing has been measured. The Arbiter is required for the product to exist. The Critic is unproven and should be off by default until the Stage B benchmark says otherwise.
5. **Is it close to v1.0?** Closer than the branch layout suggests. The plumbing is done. What remains is about fifteen small, well-bounded changes and one benchmark, set out in `ROADMAP-TO-V1.md`.
6. **Shortest safe path?** Merge to `main`; fix the P0 items; make the Arbiter's input honest and its output structured; add the mock benchmark as a CI gate; run one approved real-model acceptance pass; tag.
7. **What to defer or discard?** Discard for now: R01 runtime delegate scope (there are no tools or dispatches for a delegate to hijack) and R02 evidence receipts (requires tool execution, which is out of scope). Defer: R03 shared findings buffer (it trades away independence, the property Conclave exists to provide), native provider adapters, semantic claim extraction, retrieval, multi-user access, streaming, and every integration.
8. **Standalone or reusable service?** Standalone for v1.0. Afterwards, an optional local service that other projects may call and must be able to live without. It should never sit in the path of a deterministic safety control.
