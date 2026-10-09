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
