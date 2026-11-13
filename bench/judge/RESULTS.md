# Judge benchmark results

**Status: attempted, incomplete, no decision.**

| | |
|---|---|
| Attempted | 2026-11-13, judge `groq` (`openai/gpt-oss-120b`, free tier, prices configured as 0) |
| Completed | **3 of 144 trials** (the plan is 24 cases x 2 arms x 3 repeats, one judge) |
| Scored | `minority-01-session-storage` only: arbiter repeat 0 and 1, critic repeat 0. All 6 checks passed (arbiter 4/4, critic 2/2). |
| Stopped by | groq returned a quota error before `minority-01-session-storage`, critic repeat 1. This is an **operational outcome**, recorded in `operational.jsonl`, not a poor answer, and it is not scored. |
| Decision | **None.** Three trials in one class cannot establish a Critic default, and the decision rule is not applied to an incomplete set. |

There is still **no Critic default**: a workspace must state its choice.

## Checkpoint and how to resume

`results.jsonl` holds the three completed trials (their raw answers and checks) and `operational.jsonl` the outage. Both are preserved; a run only does the missing trials and never repeats a recorded one. From the repository root, with a `conclave.json` that names the same free groq provider:

```bash
python -m bench.judge.runner --config conclave.json --judge groq --approve-cost 0
python -m bench.judge.runner --summarize
```

(A priced judge needs `--approve-cost` at or above its estimate, and a judge with no price configured needs `--approve-unpriced`. A free tier priced at 0 needs `--approve-cost 0`.) It will stop again, without scoring anything, whenever the quota is exhausted; run it again after the quota resets. A complete set needs about 216 judge calls, so on a small free allowance it may take several days. Do not use a paid fallback without approval.

When all 144 trials exist, copy the counts per class and arm here with the date, the commit and the model, and apply the fixed rule in `README.md`.
