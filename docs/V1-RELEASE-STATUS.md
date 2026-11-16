# v1.0 release status

Candidate: `1.0.0rc1` on branch `release/v1.0-rc`. Updated 2026-11-15. This file is the resume point for another session. A criterion is PASS only with the evidence named beside it; BLOCKED means something outside the code stops it.

## Criteria

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | Installation and startup work from a documented clean environment | **PASS** (Windows, Python 3.14); Linux by CI only | Fresh venv from a clean checkout, `pip install -e ".[dev]"`, started with no config, served the console, ran a demo deliberation ( `docs/ACCEPTANCE-2026-11-15.md` §6). `docs/INSTALL.md`. CI runs Ubuntu on 3.11 and 3.14. Not run by hand on Linux. |
| 2 | Provider configuration works | **PASS** | Seven real provider entries loaded from `conclave.json`, plus one deliberately wrong-key copy; statuses, models, prices and failures reported (acceptance §1). |
| 3 | A real multi-provider panel executes | **PASS** | Six-delegate, four-family panel with Critic and Arbiter (acceptance §3; `docs/acceptance/2026-11-15/contested.json`). |
| 4 | Independent quorum accounting is verified | **PASS** | Live: 6 delegates, 4 answered, 4 sources, 4 families, failures excluded. Same-model and router-alias merging by `tests/test_sources.py`, `tests/test_orchestrator.py`, the mock benchmark and the 2026-11-13 live scenario (`docs/TEST_LOG.md`). |
| 5 | Critic and Arbiter behave as documented | **PASS** | Four parsed sections, citations, dissent shown, blind prompts (no provider or model name in either real judge prompt), overlap recorded (acceptance §3). The Critic stays off by default. |
| 6 | Partial failure, retry and fallback are verified | **PASS** | Live: `auth`, `rate_limit`, `malformed` failures kept beside successes; delegate and Arbiter retries with lineage and chain cost; fallback chain recorded `prior_attempts` (acceptance §2, §3, §4). |
| 7 | Resource limits and cancellation behave correctly | **PASS** | Live: cost ceiling refuses before calling and stays under the ceiling; unboundable cost refused up front; cancel stops a background run with no further ledger rows; shared stage deadline cuts the fallback chain (acceptance §4). `tests/test_cost_ceiling.py`, background and cancel tests in `tests/test_api.py`. |
| 8 | The GUI supports the complete ordinary workflow | **PASS** | Driven in headless Edge: dashboard, provider table, workspace creation through the form, background run with progress and Cancel, positions, structured synthesis, ledger, history (acceptance §5). Providers are configured in `conclave.json`/`.env`, not in the console (by design). |
| 9 | Run history and accounting are reliable | **PASS** for ledger and totals; see row 16 for billing | Ledger rows equal calls made; estimated totals equal provider-reported totals for OpenRouter (acceptance §3, §4); unknown cost shown as unknown (`web/render.test.mjs`). |
| 10 | Security regression tests pass | **PASS** | Full suite includes the adversarial corpus, loopback and CSRF guard (now covering the cancel endpoint), render tests. No secrets or `.env`/db files in any of 318 commits (scan); `pip-audit`: no runtime dependency vulnerabilities. |
| 11 | Existing data survives migration | **PASS** | The owner's live database was upgraded on first start on 2026-11-15: the app wrote its own backup and a read-only `integrity_check` returned `ok` (recorded in `docs/TEST_LOG.md`, 2026-11-15; the database itself is not in the repository). Migration tests in `tests/test_store.py`. The acceptance run used a scratch database. |
| 12 | Automated tests and CI pass | **PASS** locally; CI on the release branch to be confirmed before merge | 3684 passed at 97% coverage in a clean venv; `ruff` clean; `node --test web/render.test.mjs` 234 pass. CI was green on #43 and #44, whose code this branch contains. |
| 13 | Live acceptance results are documented | **PASS** | `docs/ACCEPTANCE-2026-11-15.md`, raw outputs and scripts in the repo. |
| 14 | No release-blocking defects remain | **PASS** (none known) | Non-blocking issues are listed below. |
| 15 | Documentation matches the implementation | **PASS** | README, `docs/INSTALL.md`, `docs/CONFIGURATION.md`, this file; `tests/test_docs.py` passes. |
| 16 | The release branch is reviewed and ready to merge or tag | **PASS** for review; merge and tag need the owner | Codex plan review (findings applied), Codex completion reviews of #44 and of this branch (its five findings were fixed: last-failure query, migration evidence wording, provider count, demo-only wording, a stale console sentence). Not merged; not tagged. |

## Not verified, and why

- **Billing reconciliation (BLOCKED).** The owner states billing is fine. Conclave's totals were not compared with any provider's own usage page, because that needs the owner's provider dashboards.
- **Linux by hand.** CI covers it; no local Linux machine.
- **Whether a Critic or a panel improves answers.** Unmeasured. The Critic stayed off by default on the evidence (-1.9 points with a different Critic model; -1.3 to +1.3 on three judges). A panel scored 24/26 against Fable's 24/26 on a hard set and 40/48 against 48/48 on a third set. These are not release criteria; the README says so.
- **Groq benchmark.** Closed as not completable on the free tier (6 of 144 trials).

## Known limitations (non-blocking)

- Free tiers are small: Gemini about 20 requests a day per model, Mistral rate-limits readily, free OpenRouter routes sometimes return no text from reasoning models.
- The Arbiter can state assumptions no delegate made in "common ground" (seen once in acceptance). The delegates' raw answers sit beside it for checking.
- Quota and context-window figures are always "unknown": no provider reports them to Conclave.
- A cost ceiling is an estimate-based guard (pessimistic, one token per prompt byte, counts retries), not a check against invoices. It needs prices, `max_output_tokens` and a retry limit for every participant.
- Background runs live in one server process; a restart marks them interrupted.
- Reserve delegates are chosen per run (`use_reserves`), not stored in a workspace.
- Test-suite hygiene: some tests leave SQLite connections for the garbage collector (ResourceWarnings); harmless, not fixed.
- Dev dependency `pytest` is pinned below 9 and has an advisory fixed in 9.0.3; dev only.

## Pull requests

- **#43** (next-steps refresh) and **#44** (run controls): merged into this branch; merge via the release PR.
- **#2** (audit and plan, revision 2) and **#3** (draft, trimmed plan): dated 2026-11-10 planning documents. Their release criteria are covered by this file and by `docs/RELEASE_EVIDENCE.md`. Recommend closing both with a comment pointing here; closing needs the owner.

## Release checklist

- [ ] Owner reviews the release PR and `docs/ACCEPTANCE-2026-11-15.md`.
- [ ] CI green on the release PR.
- [ ] Optional: reconcile ledger totals against provider usage pages and record it in `docs/TEST_LOG.md`.
- [ ] Merge to `main`.
- [ ] Set the version to `1.0.0` in `pyproject.toml`, `src/conclave/__init__.py` and `src/conclave/api.py` (a test keeps them equal), update `CHANGELOG.md`, and tag `v1.0.0`.
- [ ] Back up `.env`, `conclave.json`, `conclave.db`, `run_logs/` and update the live checkout.
- [ ] Choose a license (none selected).
