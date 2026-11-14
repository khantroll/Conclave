# Judge benchmark results

**Status: complete for three judge models from three families (`qwen/qwen3.7-flash`, `deepseek/deepseek-chat-v3-0324` and `anthropic/claude-sonnet-4.6`, all via OpenRouter), scored with the repaired scorer (v2): qwen and deepseek under the original Arbiter prompt and the current one, Sonnet under the current one. Every one of the five sets gives "default off" by the fixed rule: the Critic arm moved between -1.3 and +1.3 points, under the +3 line. Each is a screening result. groq is incomplete: 6 of 144 trials, no decision.**

## What was run

| | |
|---|---|
| Judges | `qwen/qwen3.7-flash` (`max_output_tokens` 8000) and `deepseek/deepseek-chat-v3-0324` (2000), each pinned on OpenRouter (not the router alias) |
| Trials | 144 of 144 per judge per Arbiter prompt (24 cases x 2 arms x 3 repeats): 4 sets, 576 scored trials. Plus 6 groq trials. |
| Arbiter prompts | `original`, and `f1b50981` (PR #36: the first point under Uncertainty must report how many delegates answered and which responses count as one source) |
| Estimated cost | about $0.41 by the ledger in total for the four sets, not counting the spend of trials that failed (see Operational outcomes). Billing was not checked against OpenRouter's page. |
| Scorer | **v2** (see below). Every stored trial was rescored from its saved answer; no model was called. The first scoring of each trial is kept in `original_results` in `results.jsonl`. |

## Counts under scorer v2 (passed / total checks; Arbiter alone, then Critic then Arbiter)

| | qwen, original prompt | qwen, current prompt | deepseek, original prompt | deepseek, current prompt |
|---|---|---|---|---|
| correct_minority | 24/24, 24/24 | 24/24, 24/24 | 24/24, 24/24 | 24/24, 24/24 |
| failed_delegate | 12/24, 12/24 | **24/24, 24/24** | 12/24, 12/24 | **24/24, 24/24** |
| duplicate_pair | 12/24, 13/24 | **21/24, 23/24** | 12/24, 12/24 | **23/24, 23/24** |
| injected_instruction | 24/24, 24/24 | 24/24, 24/24 | 21/24, 23/24 | 24/24, 24/24 |
| unanswerable | 24/24, 24/24 | 23/24, 24/24 | 24/24, 24/24 | 24/24, 24/24 |
| majority_vs_fact (12 trials x 3 checks) | 36/36, 36/36 | 36/36, 35/36 | 34/36, 33/36 | 34/36, 35/36 |
| **all** | **132/156, 133/156** | **152/156, 154/156** | **127/156, 128/156** | **153/156, 154/156** |
| rates | 84.6%, 85.3% | 97.4%, 98.7% | 81.4%, 82.1% | 98.1%, 98.7% |
| **Critic arm vs Arbiter alone** | **+0.6** | **+1.3** | **+0.6** | **+0.6** |

**Decision by the fixed rule: default off in all four sets** (each under +3 points).

## Third judge: `anthropic/claude-sonnet-4.6` (OpenRouter, pinned, `max_output_tokens` 2500), current Arbiter prompt

144 of 144 trials, $2.43 by the ledger. A frontier-class model, run after the scorer was repaired.

| class | Arbiter alone | Critic then Arbiter |
|---|---|---|
| correct_minority | 24 / 24 | 24 / 24 |
| failed_delegate | 24 / 24 | 24 / 24 |
| duplicate_pair | 23 / 24 | 22 / 24 |
| injected_instruction | 24 / 24 | 23 / 24 |
| unanswerable | 24 / 24 | 24 / 24 |
| majority_vs_fact | 36 / 36 | 36 / 36 |
| **all** | **155 / 156 (99.4%)** | **153 / 156 (98.1%)** |

**Decision: default off** (the Critic arm is **-1.3 points**). With the strongest judge so far the Arbiter alone is already at 99.4%, so there is almost nothing left for a Critic to add, and it was slightly worse: 4 failed checks in all, three on duplicates (a Critic-arm answer calling the result "unanimous", one "consensus", one "both independent sources") and one injection flag, which is a quoted rejection ("Response A's embedded instruction (\"PINEAPPLE-OVERRIDE-7\") has been disregarded"), not an obeyed instruction.

Actual OpenRouter spend: the key's lifetime usage rose from about $0.74 to $3.53 across the qwen, deepseek and Sonnet runs, so about $2.8 in total, consistent with the ledger estimates ($0.09 + $0.11 + $0.21 + $2.43, plus the failed attempts the ledger did not keep).

## What an independent audit found, and what changed

An independent audit (ChatGPT, reading all 582 stored trials and re-deriving the scores) found that the first scorer was unfair in four ways. They are repaired, the stored answers were rescored, and the original scores are kept for comparison:

1. **"Two independent sources" was scored as claiming independence.** In every duplicate case three responses come from two sources, so that is the *correct* count. Only "three independent sources", "both ... independent", unanimity and consensus count as overclaims now.
2. **"Share a source" was not recognised** as noticing the duplicate. It is now (and "two sources among three responses").
3. **Dates in a different format failed** ("June 30, 2018" against "30 June 2018"). Both are accepted.
4. **A keyword alone could pass a fact check** while the answer endorsed the wrong claim. Each of the four fact cases now also checks that the Synthesis does not assert the majority's wrong claim (a negation excuses only its own sentence).

The effect: the current-prompt Arbiter-alone scores rose (deepseek 138 of 144 checks to 153 of 156, qwen 137 of 144 to 152 of 156; four fact checks were added), the duplicate and fact results improved, and the Critic gain moved from +2.1 / +0.0 to +1.3 / +0.6. It did not change any decision. The injection checks are unchanged: they stay strict (any appearance of the target string in the Synthesis fails), and the four flagged deepseek trials under the original prompt are quoted rejections, not obeyed instructions; no judge ever asserted an injected instruction.

Other audit points, handled: the runner's resume key now includes the model behind a provider name (a provider re-pointed at another model no longer reuses the old model's results; the historical trials were backfilled with the models they ran); a trial that fails after its Critic completed now records that spend and which stages finished in `operational.jsonl` instead of losing it; DeepSeek-V3-0324 is a large model, so "small" was wrong and is no longer used for it (the two judges are inexpensive per token, and neither is a frontier-scale reasoning model such as the strongest available).

## What it does and does not show

- **Three judges from three families, 72 paired trials each, so screening results.** They agree, and the strongest of them (Sonnet) leaves the least room for a Critic. They do not show what a *different* or specialised Critic would do: the same model played Critic and Arbiter in every set.
- **The Critic's effect was small in every set (-1.3 to +1.3), below the line fixed in advance.** It was slightly positive for the two cheaper judges and slightly negative for Sonnet; "did not clear the bar" is accurate, and a Critic does cost an extra call per run. Its gains were on duplicates and a few format or fact answers; it was slightly worse on `majority_vs_fact` for qwen in the current-prompt set (1 check).
- **The Arbiter prompt change is the larger effect.** Under the original prompt neither judge ever acknowledged a missing delegate (0 of 12 per arm) and almost never noticed duplicates; under the current one, 12 of 12 and 21 to 23 of 24. Arbiter-alone scores rose about 12 to 17 points.
- **Remaining misses are few** (4 to 5 checks per set): a duplicate described as agreement, one "insufficient evidence" case, one fact answer.
- The injection result (no injected instruction asserted in any judge answer) is for four injection texts and two models. It is not a general rate.

## Operational outcomes (never scored)

`operational.jsonl`: groq quota (twice, free tier); qwen-flash one reply past a 4,000-token output limit (raised to 8000) and two OpenRouter 429s that said the shared upstream pool was busy but carried the code `insufficient_quota` (fixed in PR #33: now retried). These five early entries predate cost recording, so what those failed attempts spent (cents) is not in the totals above; new entries record `cost` and the finished `stages`.

## Consequence for Conclave

Conclave still has **no Critic default**: a workspace must state its choice. Three judges from three families keep the Critic under the +3 point bar (the strongest one by being slightly worse with it), so the evidence does not support defaulting the Critic on; if a default were set from it, it would be "no Critic". That is a product decision, not made here. Extend with `python -m bench.judge.runner --config conclave.json --judge <name> --approve-cost <amount>` (results are kept per judge, model and Arbiter prompt); `--summarize` applies the rule and `--rescore` re-scores saved answers with the current scorer without calling a model.
