# Manual Test Log

## 2026-10-07 — First browser smoke test

### Environment
- Windows PowerShell
- Local FastAPI/uvicorn instance
- Built-in demo providers only
- Workspace: HomeLedger Test

### Passed
- Application served successfully at the local web UI.
- Health indicator reported four demo providers.
- Workspace creation and selection worked.
- Request analysis classified the HomeLedger forecasting question as complex.
- Deliberation completed end to end.
- Delegate results rendered.
- Critic stage rendered.
- Arbiter stage rendered.
- Exact Delegate/Critic/Arbiter prompts were inspectable.
- Run was persisted.
- Workspace history rendered.
- Global run history rendered.
- Download-run control was present.

### Findings
1. The active workspace configuration was not obvious enough. The create/edit form could be mistaken for the currently active configuration.
2. The test workspace accidentally included the Arbiter provider in the Delegate list, producing three Delegate runs instead of the intended two.
3. Long questions made the history list visually noisy because the full question was used as the bold history title.
4. Literal `\n` text in pasted role mappings could be confusing.

### Fixes applied after the test
- Added an always-visible active workspace summary showing Delegate roles, Critic, Arbiter, routing mode, and quorum.
- Added a visible warning when Critic or Arbiter is also configured as a Delegate.
- Added a confirmation when saving a workspace with intentional stage overlap.
- Collapse the create/edit form after a successful save so stale form contents are less likely to be mistaken for active configuration.
- Compacted history cards to a short title, preview, timestamp, Delegate success count, Critic/Arbiter state, and optional cost.
- Role parsing now accepts both real line breaks and pasted literal `\n` separators.

### Status
Phase 1 basic end-to-end execution: **PASS with UX findings**.

The next meaningful test is to re-run the demo path with the corrected two-Delegate workspace, then proceed to real provider configuration.


## 2026-10-09 — First successful real-provider synthesis

### Environment
- Windows PowerShell
- Local FastAPI/uvicorn instance
- Real configured providers present: Gemini, Mistral, Groq, OpenRouter
- Test workspace used a fixed multi-provider panel

### Provider observations
- **Groq** successfully returned real Delegate output after the provider timeout fix.
- **OpenRouter** successfully returned real Delegate output.
- **Gemini** reached the API correctly but returned transient HTTP 503 high-demand/capacity errors during testing.
- **Mistral** reached the API correctly but returned HTTP 429 rate-limit errors during testing.
- Provider failures were preserved independently and did not erase successful Delegate responses.

### Successful end-to-end real-model run
To isolate Conclave from the transient Gemini/Mistral provider issues, the downstream roles were temporarily reassigned:
- successful real Delegates included Groq and OpenRouter;
- Critic: OpenRouter;
- Arbiter: Groq;
- quorum lowered to a value satisfied by the working providers.

The run completed through the full real-model pipeline:

```text
real Delegate responses
        |
        v
real Critic audit
        |
        v
real Arbiter synthesis
        |
        v
final synthesis
```

A final synthesis was produced successfully.

### What this validates
- Real API providers can be loaded from local configuration.
- Multiple real provider families can participate in one run.
- Successful Delegate output survives failures from other providers.
- Quorum behavior works with real failures.
- A real Critic can consume real Delegate responses.
- A real Arbiter can consume both Delegate responses and the Critic audit.
- The complete Delegate -> Critic -> Arbiter orchestration path works outside the fake-provider test harness.
- Provider-side errors remain visible as provider-specific failures rather than collapsing the whole run.

### Remaining findings
1. Gemini HTTP 503 capacity failures need resilience handling rather than endpoint fixes.
2. Mistral HTTP 429 behavior needs separate account/API investigation; the request is reaching the correct API route.
3. Bounded retry/backoff for transient statuses such as 429, 502, 503, and 504 is now a justified next resilience feature.
4. The quality/value of the Critic and Arbiter still needs repeated comparison against the user's manual multi-chat workflow.

### Status
Real-provider core orchestration: **PASS**.

The MVP pipeline is now functionally validated with real model responses and a real final synthesis. Remaining work is reliability, provider-specific diagnostics, routing quality, and UX/product-value refinement rather than proving that the architecture can work.

## 2026-11-13 — Real-provider acceptance run (partial)

Commit `682c370` (main), Python 3.14, Windows. Providers (free tiers, prices configured as 0): groq (`openai/gpt-oss-120b`, family openai), openrouter-free (an alias; it answered as `recursive/flint-v1.0:free`, `nvidia/nemotron-3.5-super-vl:free`, `dots-studio/dots-3-note-preview:free` and others across calls), gemini (`gemini-3.6-flash`, google), mistral (`mistral-small-latest`). A **copy** of the real database was used; the live one was not touched.

| # | Scenario | Result |
|---|---|---|
| 0 | Copy of the 2026-10 database opened | **PASS.** Backed up first (`.bak-0-...`), migrated, 12 runs readable. |
| 1 | All healthy | **PARTIAL.** groq and openrouter-free answered (2 independent sources, quorum met, Critic and Arbiter succeeded, structure `format_ok`). The third provider failed every time: mistral HTTP 429 (3 attempts, rate_limit, as on 2026-10-09), gemini timed out at 60 s in runs although it answers short prompts in 2 to 4 s alone (503 capacity earlier). So no run had three answering providers; two families are not shown by the answering providers alone (openai via groq, and whatever model openrouter-free routed to). |
| 2 | One delegate forced to fail with a wrong key | **PASS.** `groq-badkey`: 1 request, kind `auth`, not retried; the panel carried on. |
| 3 | Primary Arbiter forced to fail, fallback used | **PASS.** The fallback groq answered; `prior_attempts` named `groq-badkey` with kind `auth`; ledger had a row for each. |
| 4 | Two provider names on one model | **PASS.** `groq` and `groq-twin` counted as 1 source (2 sources in total with openrouter-free). |
| 5 | Interrupted run resumed | **PASS.** Cancelled while openrouter-free was pending: groq's answer was kept, the other recorded as `cancelled`, both calls have ledger rows (the cut-off one `cancelled`); run `interrupted`. A delegate retry completed it (Critic and Arbiter ran). |
| 6 | One retry | **PASS.** Linked into the chain (parent and root recorded), the successful delegate was not re-run; a further Critic retry joined the same chain. |
| 7 | Saved judge prompts inspected for blinding | **PASS** on 4 runs: no provider name, model name, latency or error text in any Critic or Arbiter prompt; labels only. |
| 8 | Ledger reconciled | **NOT RECONCILED.** Rows equal requests made (every scenario). Free tier, so billed is expected to be 0, but the providers' own usage or billing pages were **not** checked, so no difference is recorded. Token totals in the ledger matched the usage fields in the stored results only in the weak sense that both come from the same replies. |

### Findings
1. **openrouter-free sometimes returns a non-text answer** (a routed model with `content` null, here after about 29 s), which was a bare `malformed` failure. The adapter now accepts content given as a list of text parts and, for a null answer, says whether the model ran out of its output budget (`finish_reason: length`) and to raise `max_output_tokens`.
2. **gemini timed out at 60 s inside runs** while answering in seconds alone; not explained (503 demand spikes on this model earlier).
3. The blind prompts, error classes, fallback trail, chain linking and cancellation behaved as designed against real providers.

### Status
Not complete. Outstanding: a run with three providers answering from two named families, and reconciliation against the providers' own pages.

### Addendum, same day: scenario 1 repeated, and the Gemini diagnosis

Scenario 1 (all healthy) was repeated with a 150 s delegate timeout and a required quorum of 3 independent sources: groq (openai), openrouter-free (answered as `cohere/north-mini-code:free`) and gemini (google) all answered; 3 sources, quorum met, Arbiter succeeded with a well-formed structure, two declared model families (openai and google), blind prompts clean, 5 ledger rows for 5 requests. The openrouter Critic returned no text (`finish_reason: length`: it spent its 1,500 output tokens thinking), which the adapter now reports as exactly that; the Arbiter still ran. **Scenario 1: PASS** for the delegates and Arbiter; the Critic stage failed on that provider.

The Gemini timing evidence and the conclusion (external latency variability, no application defect found, next check named) are in `docs/RELEASE_EVIDENCE.md`. Billing reconciliation remains **unverified**.
