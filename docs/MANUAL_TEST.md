# Manual Test Checklist

This checklist begins only after CI is green.

## Phase 1 — no real API keys required

1. Create a Python virtual environment and install the project:
   ```bash
   pip install -e ".[dev]"
   ```
2. Start Conclave:
   ```bash
   uvicorn conclave.api:app --reload
   ```
3. Open `http://127.0.0.1:8000/`.
4. Confirm the header reports Conclave online and shows the built-in demo providers.
5. Create a workspace using:
   - Delegates: `demo-a, demo-b`
   - Critic: `demo-critic`
   - Arbiter: `demo-arbiter`
   - Role examples:
     - `demo-a = Architect`
     - `demo-b = Skeptical reviewer`
6. Ask a simple question and confirm:
   - a run is saved;
   - raw Delegate responses are visible;
   - exact Delegate prompts are inspectable;
   - Critic and Arbiter outputs are shown;
   - Critic and Arbiter prompts are inspectable;
   - run history reloads correctly after refreshing the browser;
   - **Download run JSON** exports the saved request/result snapshot.
7. Enable automatic Delegate selection in the workspace.
8. Analyze `What is RAID 10?` and confirm the preview recommends a one-model panel.
9. Ask a more complex architecture/decision question and confirm the preview grows the panel appropriately.
10. Edit the workspace, save it, reload the page, and confirm the changes persist.
11. Delete a disposable workspace and confirm it disappears.
12. Open **All run history** and confirm runs from a deleted workspace remain available as detached history.

## Phase 2 — failure isolation

The automated suite covers provider failure and timeout behavior, but a useful UI smoke test is:

1. Add a deliberately invalid provider to a temporary local config or point a test provider at a non-listening local endpoint.
2. Use it in a workspace alongside a working provider.
3. Confirm the failed provider is shown as failed while successful Delegate output remains available.
4. Confirm the run can still synthesize when quorum is satisfied.
5. Click **Retry this delegate** and confirm successful Delegates are not rerun.
6. Temporarily make the Critic fail, then confirm **Retry Critic + Arbiter** does not rerun Delegates.
7. Temporarily make the Arbiter fail, then confirm **Retry Arbiter only** preserves the panel and Critic.

## Phase 3 — real providers

This is the point where human credentials and real API traffic are required.

1. Copy `conclave.example.json` to `conclave.json`.
2. Configure the exact models/endpoints you want.
3. Put keys in environment variables; never place keys in `conclave.json`.
4. Start Conclave and use the per-provider **Test** buttons.
5. Create a real workspace with at least two different provider families.
6. Run the same question through:
   - fixed Delegate mode;
   - automatic Delegate selection.
7. Verify:
   - actual model names returned;
   - latency;
   - token usage;
   - estimated cost when pricing metadata is configured;
   - prompt visibility;
   - preserved raw responses;
   - Critic behavior;
   - Arbiter behavior;
   - retry behavior.
8. Compare the result against manually asking the same providers to decide whether Conclave meaningfully reduces human copy/paste work.

## First real evaluation question

A suitable initial test is the question that motivated Conclave:

> Evaluate whether a personal multi-model AI orchestration portal is worth building versus using existing products. Assess what should be delegated to gateways, what capabilities justify a custom layer, likely failure modes, whether model-specific prompt rewriting adds value, and whether persistent project context materially changes the answer. Be skeptical and preserve meaningful disagreement.

That question is complex enough to exercise routing, independent perspectives, criticism, and synthesis.
