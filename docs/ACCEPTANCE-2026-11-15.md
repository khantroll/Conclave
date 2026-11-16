# Live acceptance of the v1.0 release candidate, 2026-11-15

What was run, against what, and what it showed. Everything here used real providers through the release-candidate code (branch `release/v1.0-rc`) with a scratch database; the owner's real `conclave.db` was not touched. Raw outputs are in `docs/acceptance/2026-11-15/`; the scripts are in `scripts/acceptance/` (they read keys from an env file you name; keys are never printed or stored).

Providers used: groq (`openai/gpt-oss-120b`), OpenRouter (`qwen/qwen3.7-flash`, `deepseek/deepseek-chat-v3-0324`, the `openrouter/free` router, one tiny test call to `anthropic/claude-sonnet-4.6`), Mistral (`mistral-small-latest`) and Gemini (`gemini-3.6-flash`). Total spend by the call ledger across the session: under one cent. Mistral and Gemini free tiers are small; their failures below are real, not simulated.

## 1. Provider health (all configured providers, plus a deliberately wrong key)

| Provider | Result |
|---|---|
| groq, qwen-flash, deepseek-v3, openrouter-free, sonnet-46 | succeeded |
| mistral | `rate_limit` (HTTP 429, 2 attempts) |
| gemini | timed out at the 20 s test limit; answered in 7.7 s inside a later run |
| a copy of groq with a wrong key | `auth` (HTTP 401), as intended |

The dashboard's per-provider "last success" and "last failure" came from the call ledger and matched. Quota and context-window figures showed "unknown", because no provider reports them to Conclave.

## 2. Panels with partial failure (`panel.json`)

- **A, no Critic.** Five delegates; the wrong-key one failed (`auth`), four answered as four independent sources. Quorum 2 met. The Arbiter wrote all four sections; its coverage line said "4 of 5 delegates answered". 6 ledger calls, estimated $0.00057, provider-reported $0.00057.
- **B, explicit Critic.** Same panel plus a Critic (qwen-flash, with a fallback). Critic and Arbiter both succeeded. 7 calls.
- **Reserve wave.** Two delegates, quorum 2, one of them (a different model with a wrong key) failing: the run stopped with quorum unmet and no judge call. With two reserves listed, exactly one reserve ran (the number of sources missing), was marked `reserve: true`, and the quorum was met. The second reserve was never called.

## 3. Contested question, end to end (`contested.json`)

Question: pay down a 6.5% mortgage or invest $50,000 in an index fund. Six delegates, a Critic, an Arbiter with a fallback, quorum 3.

- 4 delegates answered (4 independent sources, 4 model families); `openrouter-free` failed `malformed` (a reasoning model ran out of output budget) and Mistral failed `rate_limit`. Both failures were recorded and shown; neither stopped the run.
- Positions: three delegates said invest (medium confidence), one said pay down the mortgage (high confidence). The Arbiter put the disagreement under "Disagreements" and cited each side. Dissent was visible; the synthesis leaned to the majority and said "confidence: medium".
- **Blinding:** none of the provider names or reported model names appeared in either judge prompt (checked by searching the real prompts). Two responses were flagged in `judge_overlaps` because the judges are also panel members.
- Cost: 9 calls, estimated $0.00092, provider-reported $0.00092 for the calls that report one.
- **Retry lineage:** retrying a failed delegate created a linked child run; the delegate failed again for the same reason. Retrying the Arbiter created a second child. The chain showed 13 calls, $0.00141, and the original run was unchanged.
- **Quality caveat:** the Arbiter's "common ground" contained statements the delegates had not made (for example that there is no pre-payment penalty). Conclave shows each delegate's raw answer beside the synthesis so this can be checked; it does not prevent it.

## 4. Resource controls (`controls.json`)

| Scenario | Observed |
|---|---|
| Cost ceiling $0.0001 | Every call refused (`cost_ceiling`), zero ledger rows, run flagged `stopped_reason: cost_ceiling`. |
| Ceiling $0.05 | All calls ran; ledger $0.00100, provider-reported $0.00100. |
| Ceiling $0.005 (room for one delegate) | qwen-flash ran, deepseek-v3 refused, the Arbiter ran; flagged as stopped by the ceiling; ledger $0.00075 (under the ceiling). |
| Ceiling with a provider that has no price | HTTP 422 before the run started, naming the provider. Nothing recorded. |
| Background run, then cancel after 1.5 s | HTTP 202 with run id; cancel returned in about 0.05 s; run `interrupted`; **no ledger rows were added in the following 8 s**; a second cancel returned 409. |
| Shared stage deadline (every attempt timing out at 0.3 s) | Off: three Arbiter attempts (primary and both fallbacks). On: one attempt; no fallback started. |

## 5. The web console in a real browser

`scripts/acceptance/browser_check.py` drives headless Edge through the DevTools protocol against the running app:

- The dashboard rendered 12 providers and the 7-day cost line ("Estimates are not invoices").
- A workspace was created through the form and appeared in the selector.
- A question was run in background mode with a cost ceiling: the Cancel button appeared during the run, the status line showed stage progress, and the final page had the positions table, the four Arbiter sections, delegate cards, a cost line (estimated and provider-reported), the call ledger table (rows matched the run) and the history entry.
- A second run was started and cancelled from the page: the status said it was interrupted and the Run button re-enabled.
- No JavaScript errors or `console.error` calls were raised.

## 6. Clean install

A fresh virtual environment from a clean checkout (`pip install -e ".[dev]"`, Python 3.14, Windows) started with no configuration, served the console, ran a demo deliberation, and passed the full suite: **3684 passed, 97% line coverage** (lowest file `analyzer.py`, 78%). `pip-audit` found no known vulnerabilities in runtime dependencies (it flagged `pip` itself and the dev-only `pytest 8.4.2`).

## Not covered here

- Billing was not reconciled against provider usage pages. The owner stated billing is fine; that is a statement, not a check.
- Linux was not run locally. CI runs the suite on Ubuntu (Python 3.11 and 3.14).
- Mistral and Gemini could not be exercised repeatedly because of free-tier limits.
- The Critic's value and whether a panel beats one model remain unmeasured (see `docs/RELEASE_EVIDENCE.md`).
