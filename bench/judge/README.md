# Judge benchmark

Measures what the mock benchmark cannot: whether a **real** judge model keeps a correct minority, admits a missing answer, counts duplicates once, refuses injected instructions, says "insufficient evidence" when it should, and prefers a checkable fact to a confident majority. Its job is to decide the Critic default with evidence instead of an assumption (roadmap P1-13).

## Design

- **Real judges, scripted panels.** Delegate answers are fixed texts (`cases.json`), so only judge calls cost money and every case is exactly repeatable.
- **24 cases, six classes of four**: a correct minority with a distinctive claim; a failed delegate; a duplicate pair that is one source; an injected instruction; an unanswerable question; a confident majority contradicted by a minority that cites a checkable fact. Each case lists automatic checks on the judge's structured (four-section) answer. An answer that is not in the required format fails every check.
- **Two arms on identical inputs** (same panel, same seed, so the same labels and order): the Arbiter alone, and the Critic then the Arbiter (the same model in both roles).
- **Three repeats per arm, up to two judge models.** 24 x (3 + 6) = 216 calls per judge model, 432 for two.
- **Scoring is automatic** (`scoring.py`, unit-tested on hand-written answers in `tests/test_bench_judge.py`). Human review is for cases the scorer cannot decide and is capped at 30 minutes in total.

## Decision rule (fixed before any run)

Pass rate over all checks, per arm. Default ON: the Critic arm passes at least 10 percentage points more and is not more than 5 points worse on any class. Default OFF: the Critic arm is less than 3 points better, or worse overall. Anything else is inconclusive and the interim rule stays: there is no Critic default and a workspace must state its choice. Results are counts, not only percentages; 72 paired trials per judge model is a screening result.

## Running it (this spends money or free-tier quota)

```bash
# 1. See what it would do and cost. No model is called.
python -m bench.judge.runner --config conclave.json --judge mistral --dry-run

# 2. Approve a ceiling at or above the estimate. Nothing runs without it.
python -m bench.judge.runner --config conclave.json --judge mistral --approve-cost 0.50

# A free tier with no price configured: approve that explicitly.
python -m bench.judge.runner --config conclave.json --judge mistral --approve-unpriced

# Summarize results.jsonl and apply the rule.
python -m bench.judge.runner --summarize
```

The estimate comes from the prompts the run would actually send and the prices in `conclave.json` (`input_cost_per_million`, `output_cost_per_million`; use 0 for a free tier), with 900 output tokens assumed per call. A judge with no price makes the cost unknown, not zero, and needs `--approve-unpriced`. Each finished trial is appended to `results.jsonl` immediately, so an interrupted run resumes without paying for anything twice. After the run, copy the counts into `RESULTS.md` with the date, the commit and the models.
