# Continue Conclave development

Continue development of khantroll/Conclave from the current checkout and repository state. Work through the following priorities until complete or blocked by a specific external dependency. Do not stop after producing a plan.

Preserve Conclave’s purpose: obtain independent model answers, compare them, preserve disagreement and uncertainty, and produce an inspectable synthesis. Keep external tool execution, recursive debates, shared delegate memory, and integrations with other projects outside this task.

## 1. Establish the current state safely

Read repository instructions, current roadmap, release criteria, test log, recent commits and open PRs. Inspect branch, worktree and uncommitted changes before modifying anything. Preserve existing work, configuration, credentials, databases and run logs. Use temporary databases or verified copies for acceptance tests; never test migrations against the only live database.

Recent development reportedly completed acceptance work around PR #24 and benchmark corrections around PR #25. Verify their actual status and contents rather than assuming they are merged or complete.

## 2. Verify all five independent-audit findings against the current implementation

For each finding, identify the relevant implementation and meaningful regression test. If still defective, fix it in a small, reviewable change:

- Mid-panel cancellation must preserve every delegate answer already completed. Pending or cancelled slots must remain recoverable, and retrying a missing slot must actually insert its result.
- Initial runs and retries must persist completed work incrementally. Cancelling a Critic retry during its subsequent Arbiter must preserve the newly completed Critic response and the retry’s lineage.
- Similarity detection must not collapse opposing recommendations merely because their surrounding text matches. Test negation, changed numbers and identical background with opposite Conclusion lines. Distinguish known model identity from suspected text overlap; do not tell judges that lexical similarity proves the same underlying source. Preserve anti-inflation safeguards without suppressing dissent.
- Historical responses must retain immutable, secret-free provider provenance. Changing current model, endpoint, family or router-alias configuration must not reclassify an unchanged historical answer during a retry.
- Malformed provider metadata must become a contained provider failure rather than aborting a healthy panel. Cover invalid reported-model types and malformed telemetry while allowing cancellation to propagate properly.

Do not count a finding as resolved merely because its PR merged or the general suite passes. Record the specific evidence.

## 3. Investigate Gemini’s inconsistent execution

The reported symptom is that Gemini answers quickly when tested alone but times out after 60 seconds inside deliberations.

Reproduce using the same configured model, exact saved prompt, system prompt, generation settings and adapter. Compare isolated execution with execution inside the orchestration path, then compare sequential and concurrent requests.

Capture safe timing and attempt diagnostics sufficient to distinguish prompt size, provider throttling, transport behavior, cancellation and application blocking. Never log credentials. Avoid repeated provider calls once quota or rate limits make further attempts uninformative.

Fix an application defect if found. If the cause remains external or uncertain, document the evidence and the next discriminating check. Do not merely increase the timeout or label this an outage without supporting evidence.

## 4. Correct and preserve benchmark state

The last reported judge benchmark completed only 3 of 144 trials before Groq exhausted its free quota.

Verify the actual checkpoint and results. Preserve completed trials and resume only missing work. Availability/quota failures must not be scored as poor judge answers; report them separately as operational outcomes.

Documentation must state “attempted, incomplete, no decision,” with actual counts. Three trials cannot establish a Critic default. Keep workspace Critic selection explicit while evidence is incomplete.

Use existing confirmed free-tier configurations only. Do not enable paid fallback, change billing settings or incur new paid usage without approval. If the benchmark cannot continue, leave a verified checkpoint and exact resume command, then continue independent work.

## 5. Finish acceptance evidence where possible

Verify the previously reported migration, wrong-key, fallback, duplicate-source, interruption/resume, retry-lineage and prompt-blinding results.

Attempt the remaining healthy-provider scenario only when configured providers are available. Preserve the required source quorum and model-family diversity; do not weaken acceptance criteria to obtain a pass.

Separate:
- locally estimated cost;
- provider-reported usage/cost;
- independently verified billing.

A ledger row proves a recorded attempt, not its billed amount. If billing-page access is unavailable, mark reconciliation unverified and identify the precise remaining manual check.

## 6. Validate and update the development record

Run the appropriate isolated regression tests, full suite and repository checks for the final changes. Use fake providers for automated tests; make real-provider calls deliberate and bounded.

Update the authoritative roadmap/status/release evidence so implemented, verified, partial, blocked and deferred work are clearly distinguished. Resolve stale statements without inventing results. Keep the original audit as historical evidence.

Prepare focused commits and PRs following the repository’s established workflow. Preserve history and avoid unrelated changes.

Finish with:
- findings fixed and their regression evidence;
- findings already fixed and how verified;
- Gemini diagnosis and remaining uncertainty;
- test results and audited commit;
- benchmark completion/checkpoint state;
- acceptance and billing items still blocked;
- PR links and the next concrete development step.

Continue useful local work when provider quotas block external validation. Do not mark release readiness complete while required evidence is missing.
