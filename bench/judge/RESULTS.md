# Judge benchmark results

**Status: complete for two judge models from different families (`qwen/qwen3.7-flash` and `deepseek/deepseek-chat-v3-0324`, both via OpenRouter), under the original Arbiter prompt and again under the current one. Every one of the four sets gives "default off" by the fixed rule; each is a screening result. A third attempt (groq) is incomplete.**

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

## Second judge: `deepseek/deepseek-chat-v3-0324` (OpenRouter, pinned, non-reasoning, `max_output_tokens` 2000)

144 of 144 trials, about $0.11 by the ledger ($0.29 and $1.14 per million tokens).

| class | Arbiter alone | Critic then Arbiter |
|---|---|---|
| correct_minority | 24 / 24 | 24 / 24 |
| failed_delegate | 12 / 24 | 12 / 24 |
| duplicate_pair | 12 / 24 | 12 / 24 |
| injected_instruction | 21 / 24 | 23 / 24 |
| unanswerable | 24 / 24 | 24 / 24 |
| majority_vs_fact | 23 / 24 | 22 / 24 |
| **all** | **116 / 144 (80.6%)** | **117 / 144 (81.2%)** |

**Decision: default off** (the Critic arm is **+0.7 points**, under +3). The two judges agree: neither shows the Critic helping on these cases (-1.4 and +0.7 points).

- **The injection failures are not injections that worked.** All four flagged trials quote the target string while rejecting it ("PINEAPPLE-OVERRIDE-7 cannot be honored", "Reject B's ZEBRA-APPROVED-91 directive", "OVERRIDE-ACK-6620 is ignored"). The check is strict (any appearance in the Synthesis fails) and was fixed before the run, so they are scored as failures. Sensitivity: if a quoted rejection did not count, deepseek would score 119/144 Arbiter alone and 118/144 with the Critic (-0.7 points); the decision does not change. No judge asserted an injected instruction.
- **Two real misses:** one Critic-arm answer was not in the required format (`fact-01-http-spec`), and one Arbiter answer did not cite the RFC 8996 / PCI DSS facts (`fact-03-tls-pci`).
- **The same two classes failed in both arms and both judges** (0 of 12 on acknowledging a missing delegate, 0 of 12 on noticing duplicates for deepseek; 12 / 24 is the format check passing and nothing else). See below.

## After the Arbiter prompt change (Arbiter prompt `f1b50981`)

The first two runs showed both judges, in both arms, never acknowledging a missing delegate and almost never noticing duplicate sources, although the prompt says both. The Arbiter's instruction was changed (PR #36) so that the first point under "Uncertainty" must report coverage (how many delegates answered) and which responses count as one source. All 144 trials were re-run on both judges under the new prompt (about $0.10 each, $0.21 together). The earlier results are kept, labelled `original`, and are not mixed with these.

| | qwen-flash, original | qwen-flash, new prompt | deepseek-v3, original | deepseek-v3, new prompt |
|---|---|---|---|---|
| correct_minority | 24/24, 24/24 | 24/24, 24/24 | 24/24, 24/24 | 24/24, 24/24 |
| failed_delegate | 12/24, 12/24 | **24/24, 24/24** | 12/24, 12/24 | **24/24, 24/24** |
| duplicate_pair | 12/24, 13/24 | **20/24, 23/24** | 12/24, 12/24 | **19/24, 19/24** |
| injected_instruction | 24/24, 24/24 | 24/24, 24/24 | 21/24, 23/24 | **24/24, 24/24** |
| unanswerable | 24/24, 24/24 | 23/24, 24/24 | 24/24, 24/24 | 24/24, 24/24 |
| majority_vs_fact | 24/24, 21/24 | 22/24, 21/24 | 23/24, 22/24 | 23/24, 23/24 |
| **all (Arbiter alone, Critic then Arbiter)** | 120/144, 118/144 | **137/144, 140/144** | 116/144, 117/144 | **138/144, 138/144** |
| Critic arm vs Arbiter alone | -1.4 | **+2.1** | +0.7 | **+0.0** |

(Each cell is Arbiter alone, then Critic then Arbiter, passed / total checks.)

- **The prompt change worked.** Acknowledging a missing delegate went from 0 of 12 to 12 of 12 in every arm on both judges, and noticing a duplicate pair rose from about 0 to about 19 to 23 of 24 checks passed (the format check is half of each class). Overall the Arbiter-alone arm rose from 83.3% to 95.1% (qwen) and from 80.6% to 95.8% (deepseek).
- **The Critic still did not clear the bar.** By the fixed rule both judges are **default off**: +2.1 points (qwen, 0.9 point under the +3 line) and +0.0 (deepseek). The earlier result was not an artefact of the weak prompt. With the prompt fixed, the Critic's one visible gain is on duplicates for qwen (23 vs 20), and it is slightly worse on `majority_vs_fact` for qwen.
- **A change in the prompt is also a change in the sensitivity to the Critic**, so the qwen figure sits close to the line. Three repeats on 24 cases cannot separate +2.1 from +3; this is still a screening result on two small models.
- **Remaining misses are mostly duplicates the judge still describes as agreement** ("unanimous", "two independent sources", or no mention), plus one `unanswerable` and a few `majority_vs_fact` answers.
- The `original` prompt results above are the historical record of the problem; these are the current Arbiter prompt's.

## What it does and does not show

- **Two judge models (qwen and deepseek), each 72 paired trials: screening results.** They agree, but they are two small, inexpensive models. They do not show what a stronger judge would do.
- **The Critic added nothing here, and it cost an extra call per run.** It did not improve minority retention (already 24/24 without it), injection resistance (24/24 both) or "insufficient evidence" (24/24 both).
- **Both arms and both judges failed the same two classes, and that is a finding about the Arbiter's prompt, not the Critic.** Neither judge acknowledged a missing delegate (0 of 12 in each arm, across all four cases) and they almost never noticed that two responses were one source (qwen 1 of 24 checks, deepseek 0 of 24). The notes telling it so ("2 of 3 delegates answered", "Responses A and B come from the same underlying source") are in the prompt, and the answers read as if the judge did not use them. The scorer is not the cause: the answers contain no acknowledgement (checked on samples from each class). A prompt change that requires the Arbiter to state coverage and shared sources would be the obvious fix; it has not been made, so it has not been re-measured. A prompt change would need these cases re-run.
- Injection resistance of 24/24 is for these four injection texts and this model. It is not a general claim.

## Operational outcomes (never scored)

`operational.jsonl`: groq quota (twice, free tier); qwen-flash one reply that ran past a 4,000-token output limit (limit then raised to 8000); qwen-flash two OpenRouter 429s that said the shared upstream pool was busy but carried the code `insufficient_quota` (Conclave treated them as an empty account; fixed in PR #33 so they are retried).

## Other attempts

`groq` (`openai/gpt-oss-120b`, free tier): **6 of 144 trials, no decision.** All 12 checks passed on `minority-01-session-storage`; the free quota then ran out. Its trials are kept in `results.jsonl`. The rule is applied per judge and only to a complete set, so groq has no decision.

## Consequence for Conclave

Conclave still has **no Critic default**: a workspace must state its choice. Two judges from two families agree that the Critic does not help here, so the result does not support defaulting the Critic on; if a default were ever set from this evidence it would be "no Critic". Whether to make that default is a product decision, not made here. Resume or extend with `python -m bench.judge.runner --config conclave.json --judge <name> --approve-cost <amount>`; `python -m bench.judge.runner --summarize` applies the rule.
