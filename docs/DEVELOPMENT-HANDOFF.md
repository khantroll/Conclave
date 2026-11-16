# Development handoff

Written 2026-11-15 on resuming after a usage-limit stop. Verified against the repository, not copied from earlier notes.

## State

- Branch: `main` at `dba8c59` (merge of PR #40). Worktree was clean on resume; no stash; no uncommitted or half-applied edit.
- Open PRs: #2 (audit/plan, open) and #3 (trimmed plan, draft). Both are docs and predate current `main`; untouched.
- No background process of this project was running (only an unrelated `node.exe`).
- Milestone: none was in flight. The last completed milestone is the judge benchmark and runner spend limit (PR #40, merged).

## Benchmark state (verified from `bench/judge/results.jsonl`)

qwen/qwen3.7-flash 288, deepseek/deepseek-chat-v3-0324 288, anthropic/claude-sonnet-4.6 144, openai/gpt-oss-120b (groq) 6 of 144. Matches `bench/judge/RESULTS.md`: Critic arm within -1.3 to +1.3 points, default off; groq incomplete, no decision.

## Tests

- First pytest attempt failed with `PermissionError` on the default temp dir (`%TEMP%\pytest-of-khantroll`): an environment fault, not a code failure.
- Rerun with `--basetemp` in the scratchpad: see "Test result" below.

Command: `python -m pytest -q --basetemp=<writable dir> -p no:cacheprovider`

## Remaining work (from `docs/DEVELOPMENT_NEXT_STEPS.md`, not started, all need your approval)

1. Real-provider acceptance run (`docs/MANUAL_TEST.md`): needs cost approval.
2. ~~Benchmark with a different model as Critic~~ **Done 2026-11-15** (owner-approved, cap $1): qwen-flash Arbiter + mistral-nemo Critic, 144 of 144 trials, about $0.07, Critic arm -1.9 points, default off. Results in `bench/judge/RESULTS.md`. Uses the new `--critic` runner option.
3. Update the live checkout (back up `.env`, `conclave.json`, `conclave.db` first).
4. Measure panel vs one strong model.

## Review status

The `--critic` runner change was reviewed twice: Codex (completed; its script wrote the result to a file named `-` instead of stdout, which is a script quirk to fix) and the `opus-reviewer` fallback. Fixed: unpriced Critic bypassing cost approval and `--max-spend` (now refused), estimate not an upper bound (input and output now priced at the dearer of each), failed Critic reported under the Arbiter's name, blank `--critic`, and two provider names on one model passing as a "different" Critic. Left as is (low): labels join names with `+`, so a provider literally named `a+b` could collide. After the fixes: `tests/test_bench_judge.py` and `tests/test_docs.py` 126 passed. The full suite was not rerun after these bench-only changes (it passed 3639/1 environmental on `dba8c59`).

## Test result

Full suite on `dba8c59` (with `--basetemp` redirected): 3639 passed, 1 failed, 583 s.
The one failure, `tests/test_isolation.py::test_canary_suite_leaves_a_configured_directory_untouched`, runs an inner pytest subprocess that does not inherit `--basetemp`, so it hit the same blocked default temp dir. Rerun with `TMP`/`TEMP` pointed at a writable directory: **passed** (81 s). So the failure is environmental, not a code defect.
Full-suite command that works here: set `TMP` and `TEMP` to a writable directory, then `python -m pytest -q -p no:cacheprovider`.

## Acceptance evidence

`docs/TEST_LOG.md` (2026-11-13) already records every acceptance scenario as PASS, including the all-healthy rerun with 3 sources from 2 families. Not repeated (it would only spend free-tier quota; Gemini allows 20 requests a day).
Real config, `.env` and the database copy live in `C:\AMD\p115`, not in this checkout. Later in the session, with the owner's approval (billing fine, cap $1), one live OpenRouter benchmark ran (about $0.07; see Remaining work item 2). No other provider calls were made.

## Exact next action (needs the user)

Billing reconciliation is still unverified. Compare the Groq, OpenRouter, Gemini and Mistral usage pages with the ledger rows for the 2026-11-13 runs (`C:\AMD\p115\real_copy.db`). If all show $0, mark scenario 8 verified in `docs/TEST_LOG.md`. Other open items need approval (see Remaining work).

## Later in the 2026-11-15 session

- Branch `docs/development-handoff-2026-11-15` is pushed; PR #41 is open (https://github.com/khantroll/Conclave/pull/41).
- Live checkout `C:\AMD\Conclave\Conclave` was fast-forwarded to `main` (`dba8c59`) with `"router_alias": true` added for `openrouter-free`. Backup of `.env`, `conclave.json` and `conclave.db` is in `C:\AMD\Conclave\conclave-backup-20261115`. The app was not started, so the database upgrade has not run on the real `conclave.db`; it upgrades itself at first start with its own backup.
- Panel versus one model, three sets (all in `bench/panel/`; the owner lifted the no-Fable rule for this test only):
  - Easy 10 questions: ceiling, no decision (`RESULTS.md`).
  - Hard 13 questions: panel 24/26 = Fable 24/26, above each cheap member (`HARD-RESULTS.md`).
  - Set 3, 16 questions: Fable 48/48 over three runs; panel Arbiter 40/48 (3 failed Arbiter stages on S13, 5 wrong), groq alone 44/48 (`SET3-RESULTS.md`). The panel did worse than the strongest model here.
  - Conclusion: no evidence yet that a panel beats the strongest model. Panel cost by the ledger for set 3 was about $0.076.
- Different-Critic benchmark: Critic arm scored -1.9 points; default stays off.

## Four opt-in run controls (branch `feat/cost-ceiling-deadlines-reserves`)

Built on the owner's instruction (2026-11-15), all off by default: per-run estimated cost ceiling that fails closed (`src/conclave/budget.py`), shared stage deadline, reserve delegates (one replacement wave), and background runs with cancel. Documented in `docs/CONFIGURATION.md` ("Optional run controls"). A Codex plan review (findings applied) and a Codex completion review (no material findings) ran. Full suite exited 0; ruff clean. Not tried against real providers; the web console does not use background mode. The live app on port 8000 still runs the previous code until restarted.
