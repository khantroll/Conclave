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
