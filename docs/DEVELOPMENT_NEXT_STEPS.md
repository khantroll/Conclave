# Development handoff — October 24, 2026

## Current state

Implementation remains on `feature/mvp-scaffold` in draft PR #1. Main contains planning and the October 23 research roadmap; it is not the runnable application branch. Do not replace the implementation with main or lose main's newer research notes when reconciling branches.

The manual test log records successful demo testing on October 7 and real Delegate → Critic → Arbiter synthesis on October 9, using Groq/OpenRouter while Gemini returned 503 and Mistral returned 429. Those observations are historical, not a current provider availability check.

Inspection at `ce81e0f` confirmed that bounded transient retries, downstream fallbacks, and automatic run audit exports were already implemented. This continuation adds:

- Correct attempt telemetry on exhausted HTTP retries and subsequent transport/response failures.
- HTTP-date Retry-After handling, including past dates and invalid/non-finite values.
- Regression coverage for all four transient statuses, malformed responses, transport failures, and cancellation during backoff while another Delegate succeeds.
- Clarified timeout boundaries: each fallback provider gets its own timeout.

Validation: 66 tests pass on Python 3.12; Ruff, Python compilation, JavaScript syntax, and diff whitespace checks pass. A Starlette TestClient/httpx deprecation warning remains. No live provider calls were made and no browser interaction was performed in this continuation.

## Next steps, in order

1. **Repeat the real-provider reliability test locally.** Update the existing `feature/mvp-scaffold` checkout, restart Conclave, and test configured providers. Use the previously working Groq/OpenRouter panel first; then retry Gemini/Mistral. Keep configuration and API keys local. Export or retain the automatic run JSON. Pass: successful Delegate output survives a failed provider, Critic/Arbiter complete through configured fallbacks, failures show useful diagnostics and attempt counts, and an isolated retry does not rerun successful Delegates. Use `docs/MANUAL_TEST.md` as the test procedure.

2. **Measure whether the panel improves actual decisions.** Run a small fixed set of representative questions through Conclave and the manual multi-chat workflow. Record correctness, unsupported claims, useful dissent, human correction effort, elapsed time, and reported cost/token usage. Keep models, settings, and questions comparable. Do not equate agreement with evidence. Use this baseline before changing deliberation architecture.

3. **Implement the R01 boundary experiment.** Follow `docs/RESEARCH_ROADMAP_2026-10-23.md` on main. Start with offline adversarial fixtures and runtime-owned participant/task/context scope. Delegate text must never expand authority or trigger new dispatches. Pass: zero unauthorized dispatches/context transfers across 50 cases while legitimate dissent reaches synthesis. This does not add automatic external tool execution.

4. **Add R02 evidence-backed Critic verification.** Bind actual check receipts to a candidate revision. Failed required checks must deterministically block verification; model assertions alone are insufficient. Start with offline fixtures and clean controls.

5. **Consider R03 shared findings only after scope checks and a measured baseline.** Keep it optional and bounded; retain the independent panel as the default until paired evaluation supports a change.

## Known limits

- Timeout results retain the legacy default attempt count, rather than an exact count of interrupted HTTP requests.
- Fallback results retain the final selected provider; earlier failed fallback outcomes are not a complete stage-by-stage attempt history.
- Each fallback gets a separate timeout. A shared total stage deadline and richer fallback audit trail remain possible reliability follow-ups.
- Current account quotas, model availability, and response quality need live testing with the user's configuration.
- No verified assignment to Codex/Cursor or running instance on Xenos is known from this cloud session.
