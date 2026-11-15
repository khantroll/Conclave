# Panel versus one strong model: screening attempt (2026-11-15)

**Status: attempted, complete for this question set, no decision. The set did not discriminate (every arm was at or near the ceiling), so it says nothing about whether a panel beats one strong model.** `README.md` still says the question is unmeasured, and that stays true.

## What was run

- **Questions:** 10, in `questions-for-fable.md` (six checkable facts or computations, two judgment calls, one false premise, one unanswerable). Key in `answer-key.md`, withheld from both arms while the set was live.
- **One strong model:** Fable 5.2 as a subagent with no tools, one answer per question, raw text in `fable-raw.md`.
- **Panel:** Conclave with five delegates (`qwen-flash`, `deepseek-v3`, `gemini`, `groq`, `mistral`), `qwen-flash` as Arbiter, no Critic (default off per `bench/judge/RESULTS.md`), `minimum_successes` 2, one run per question. `mistral` failed (HTTP 429) on all ten, so four sources answered every time. Raw output, including every delegate answer, in `panel-raw.json`. Estimated cost $0.011 by the ledger; billing not checked.

## Scores against the key (scored by the same assistant that ran the panel, not blind to arm; the key is objective for Q1 to Q6)

| | Fable | Panel (Arbiter) |
|---|---|---|
| Q1 to Q6 (facts, computations) | 6/6 | 6/6 |
| Q7, Q8, Q10 (judgment, 0 to 2) | 6/6 | 6/6 |
| Q9 (unanswerable, 0 to 2) | 1/2: gave "about $926.69" with medium confidence and a verify note, where the key asks for no confident exact figure | 2/2: declined |
| Total (of 14) | 13 | 14 |

The one-point gap is a judgment on Q9 (Fable hedged; the key's wording is strict) and is not evidence of a difference. Scored leniently they are equal.

Each individual cheap delegate was also correct on every checkable question it finished (Q1, Q2, Q3, Q4, Q6, Q9 inspected; groq and qwen-flash gave a looser Q3 conclusion). So the panel did not rescue any wrong single answer, because there were none to rescue.

## What this does and does not show

- It does **not** show a panel beats one strong model, nor that it does not. The questions were too easy to separate anything: all arms at about 100%.
- It shows the panel pipeline completes real questions end to end with one provider failing every time (mistral 429), and that the Arbiter recorded coverage ("4 of 5 delegates answered") as designed.
- Not measured: cost against a single strong model, time, unsupported claims, human correction effort.

## Next, if this is pursued

A set where cheap single models fail some of the time (hard or recent facts, multi-step reasoning, subtle traps), with several repeats and a blind scorer, so there is room for a panel to help. Not built.
