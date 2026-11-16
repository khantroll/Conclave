# Panel versus one strong model: hard set (2026-11-15)

**Status: complete for this set. No decision on "panel beats the strongest single model": it tied. It does show the panel beating each of its own cheap members.** One set, 13 questions, 2 runs per arm, so a screening result.

## What was run

- **Questions:** `hard-questions.md` (13: arithmetic, Python/SQL/regex behaviour, a probability variant, a false premise, and one question nobody can answer without running code, H12). Every answer is machine-verified (`hard-key.md`: code run, or integer arithmetic).
- **One strong model:** Fable 5.2, two independent runs, no tools (`hard-fable-run1-raw.md`, `hard-fable-run2-raw.md`).
- **Panel:** Conclave, delegates `qwen-flash`, `deepseek-v3`, `groq` (`openai/gpt-oss-120b`) and `nemo` (`mistralai/mistral-nemo`), `qwen-flash` as Arbiter, no Critic, two passes (`hard-panel-raw.json`, 26 deliberations). Gemini was left out (free quota spent earlier the same day) and mistral-small (rate-limited all day). One delegate call failed (`groq`, empty response, H11 pass 1), recorded and not retried. Cost by the ledger: $0.037 (billing page not checked).
- **Scoring:** `score_hard.py` against the key; Fable's answers were read by hand. Scored by the same assistant that ran it, with the key written before any answer existed, so objective for 12 of 13 questions.

## Results (answers correct / answers given; two passes of 13)

| Arm | Correct | Confident and wrong |
|---|---|---|
| **Panel (Arbiter)** | **24/26** | 0 (the scorer counts one "cannot be determined, Confidence: high" on H12 as wrong; it is an honest refusal) |
| Fable 5.2 (run 1 / run 2) | 12/13 and 12/13 = **24/26** | 0 |
| groq alone (as a delegate) | 22/25 | 1 |
| qwen-flash alone | 22/26 | 2 |
| deepseek-v3 alone | 20/26 | 3 |
| mistral-nemo alone | 3/26 | 22 |

H12 (the 1000th digit of the square root of 2) is unanswerable without computation. Fable and the Arbiter both said so (Fable also gave a low-confidence guess, wrong); neither is penalised beyond the one point, so **24/26 is the best any arm could score**, and the panel and Fable both reached it.

## What it shows

- **Panel against its own members: a real effect.** The cheap models fail on this set: nemo is wrong 23 times in 26 (usually with `Confidence: high`), deepseek-v3 six times (36,524 days for H11; 2/3 for the random-host Monty Hall once), qwen-flash four times (a wrong H3; a wrong regex result in H7 once), and some answers differ only in format ("2" for 2.0). The Arbiter overruled the wrong delegates and scored 24/26. It named the dissent, for example "outlier claim stems from a foundational error in applying prime-specific modular theorems" (H1) and "Response D contains systematic errors across every evaluated component" (H5).
- **Panel against the strongest model: a tie, and both hit the ceiling.** The set cannot show the panel beating Fable, because Fable lost only the one point nobody can win.
- Conclave's own guarantees held: delegate answers stayed independent and raw, the Arbiter reported coverage and dissent, and a failed delegate was recorded.

## What it does not show

- Whether a panel helps on questions the strongest model gets wrong. This set had none it could get wrong except H12.
- That the gain comes from the panel and not from `qwen-flash` as Arbiter: the Arbiter-alone arm (qwen-flash given the question once) is the 22/26 row, and the Arbiter's 24/26 is two points higher; two questions on 26 runs is within noise.
- Cost or time against a single strong model; unsupported claims; human correction effort.
- Generality: 13 questions in one domain (code and arithmetic, chosen because they can be verified).

## Next, if pursued

Questions the strongest model fails some of the time (so a panel could help or hurt), more repeats, and a scorer that does not know the arm. Not built.
