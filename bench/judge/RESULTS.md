# Judge benchmark results

**Status: complete for one judge model (`qwen/qwen3.7-flash` via OpenRouter), a screening result. Decision by the fixed rule: default off. Two other attempts are incomplete.**

| | |
|---|---|
| Run | 2026-11-13 to 2026-11-14, Conclave `main` with PR #33 (busy-upstream 429 retried), judge provider `qwen-flash` pinned to `qwen/qwen3.7-flash` (not the router alias), `max_output_tokens` 8000 |
| Trials | **144 of 144** scored (24 cases x 2 arms x 3 repeats); 5 trials could not run on the first attempt and were run later (operational outcomes below, never scored) |
| Estimated cost | about $0.09 by the ledger (tokens times the listed prices of $0.03 and $0.13 per million); billing not checked against OpenRouter's page. OpenRouter's key page showed $0.016 spent on that day at one point during the run and a $50 limit. |

## Counts (passed / total checks)

| class | Arbiter alone | Critic then Arbiter |
|---|---|---|
| correct_minority | 24 / 24 | 24 / 24 |
| failed_delegate | 12 / 24 | 12 / 24 |
| duplicate_pair | 12 / 24 | 13 / 24 |
| injected_instruction | 24 / 24 | 24 / 24 |
| unanswerable | 24 / 24 | 24 / 24 |
| majority_vs_fact | 24 / 24 | 21 / 24 |
| **all** | **120 / 144 (83.3%)** | **118 / 144 (81.9%)** |

**Decision: default off.** The Critic arm was **-1.4 points** against the Arbiter alone, under the +3 point line. By the rule fixed in advance, a Critic is not shown to help this judge on these cases, and on `majority_vs_fact` it did slightly worse (3 checks).

## What it does and does not show

- **One judge model, one run of each case three times.** 72 paired trials is a screening result. It does not show what a stronger judge, or a different family, would do. A second judge (the plan allows two) has not been run.
- **The Critic added nothing here, and it cost an extra call per run.** It did not improve minority retention (already 24/24 without it), injection resistance (24/24 both) or "insufficient evidence" (24/24 both).
- **Both arms failed the same two classes, and that is a finding about the Arbiter's prompt, not the Critic.** The judge never acknowledged a missing delegate (0 of 12 scored checks passed in each arm, across all four cases) and never noticed that two responses were one source (1 of 24). The notes telling it so ("2 of 3 delegates answered", "Responses A and B come from the same underlying source") are in the prompt, and the answers read as if the judge did not use them. The scorer is not the cause: the answers contain no acknowledgement (checked on samples from each class). A prompt change that requires the Arbiter to state coverage and shared sources would be the obvious fix; it has not been made, so it has not been re-measured. A prompt change would need these cases re-run.
- Injection resistance of 24/24 is for these four injection texts and this model. It is not a general claim.

## Operational outcomes (never scored)

`operational.jsonl`: groq quota (twice, free tier); qwen-flash one reply that ran past a 4,000-token output limit (limit then raised to 8000); qwen-flash two OpenRouter 429s that said the shared upstream pool was busy but carried the code `insufficient_quota` (Conclave treated them as an empty account; fixed in PR #33 so they are retried).

## Other attempts

`groq` (`openai/gpt-oss-120b`, free tier): **6 of 144 trials, no decision.** All 12 checks passed on `minority-01-session-storage`; the free quota then ran out. Its trials are kept in `results.jsonl`. The rule is applied per judge and only to a complete set, so groq has no decision.

## Consequence for Conclave

Conclave still has **no Critic default**: a workspace must state its choice. The result does not support defaulting the Critic on. If a default were ever set from this evidence it would be "no Critic", pending a second judge model. Resume or extend with `python -m bench.judge.runner --config conclave.json --judge <name> --approve-cost <amount>`; `python -m bench.judge.runner --summarize` applies the rule.
