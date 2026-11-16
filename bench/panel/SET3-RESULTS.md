# Panel vs one model, set 3 (16 verifiable questions, 2026-11-15)

Questions where unaided reasoning is error-prone (combinatorics, big-number recall, Python semantics, float behaviour, SQLite typing). Every key answer was verified by running code (`set3-key.md`). Scorer: `score_set3.py` (regex on each arm's final answer line; mismatches checked by hand).

## Arms

- **Fable 5.2**, no tools, three independent runs (`set3-fable-run{1,2,3}-raw.md`).
- **Panel**: qwen-flash, deepseek-v3, groq and nemo as delegates, qwen-flash as Arbiter, no Critic, three passes (`set3-panel-raw.json`, 48 deliberations, 240 provider calls).

## Results

| Arm | Correct |
|---|---|
| Fable 5.2 | 48/48 (all three runs identical, 16/16 each) |
| Panel Arbiter | 40/48 correct, 5 wrong, 3 failed (no Arbiter answer) |
| groq | 44/48 |
| qwen-flash | 34/42 (6 failed calls) |
| deepseek-v3 | 33/48 |
| nemo | 1/47 |

## Where the panel lost

- **S13** (cryptarithm TWO+TWO=FOUR): the Arbiter failed all three times because qwen-flash returned a malformed result (the Arbiter stage reported `failed`, not a wrong answer). The remaining members disagreed (groq 4, deepseek-v3 1/6, none 7).
- **S16** (SQLite expression row): wrong on all three passes. qwen-flash, the Arbiter, treated `||` as binding after `+`, giving `a2` and `1` for the last field. groq was also wrong each time, so there was no correct dissent to preserve.
- **S9, pass 2**: `0 6 7 8` instead of `0 5 6 7`, copied from qwen-flash.
- **S12, pass 3**: last value `True` instead of `False`, copied from qwen-flash.
- The Arbiter's wrong answers all matched its own delegate's answer. It never reached a wrong answer on its own when qwen-flash was right.

## Reading

- Fable is at the ceiling again and the panel is not: 48/48 against 40/48 (or 40/45 where the Arbiter answered). This set does not show a panel beating the strongest model; it shows the opposite on these questions.
- The panel beat every cheap member except groq, which scored higher (44/48) than the Arbiter. Where a member was right and the Arbiter was wrong, the Arbiter's synthesis did not help.
- The panel's value (preserved dissent, provenance, explicit failures) is not what this test measures. Failures were reported explicitly (three `failed` Arbiter stages) and no error was hidden.
- nemo was nearly always wrong with high stated confidence (44 confident-wrong). It adds cost and noise on questions like these.

## Cost

Panel by the ledger: about $0.076 (240 calls). Fable runs were subagent calls whose cost is not in the Conclave ledger.

## Caveats

- Scoring is regex-based on the final answer line, not blind. The same assistant ran both arms.
- Questions are code-verifiable and domain-narrow; the result may not transfer.
- Gemini was excluded (daily free quota used earlier) and mistral-small (rate-limited), so the panel is a four-source cheap panel, not the strongest one available.
- Fable had no tools, and three runs were identical, so run-to-run variance is not measured.
- Decision: none for the product. Panel-vs-strongest-model remains unproven.
