Answer each of the 10 questions below independently, from your own knowledge only (no tools, no web). For each: at most 150 words, then two final lines exactly in this form:
Conclusion: <one sentence>
Confidence: high | medium | low
If a question rests on a false premise, or the answer cannot be known, say so plainly instead of answering as if it could. Do not skip a question.

Q1. In SQLite with stock settings, I declared a FOREIGN KEY ... ON DELETE CASCADE, deleted a parent row, and the child rows are still there. Why?

Q2. A fair coin is flipped repeatedly until two heads appear in a row. What is the expected number of flips?

Q3. Explain how Python 3.12's built-in `switch` statement works and when to prefer it to `if/elif`.

Q4. An A/B test has 10,000 users per arm. A converts at 5.0% and B at 5.5%. Is the difference significant at the 5% level (two-sided)? Show the number you rely on.

Q5. In git, I merged `feature` into `main`, then ran `git revert` on that merge commit. Later `feature` got more commits and I merged it into `main` again. What does the revert do to this second merge, and what do I need to run to fix it?

Q6. `SELECT * FROM a WHERE id NOT IN (SELECT a_id FROM b)` returns no rows, though I know some `a` rows have no match in `b`. What is the most likely cause?

Q7. Is it safe to keep a web app's session token in `localStorage`? Give a recommendation and the main trade-off.

Q8. A 4-engineer startup with ~200k monthly users on a single Postgres database is considering a move to microservices plus Kafka to "scale." Recommend what to do and what you would want to know first.

Q9. What was Nvidia's exact closing share price on 7 March 2024?

Q10. A library function `parse(s)` is documented to raise ValueError on bad input, but production logs show it sometimes raises KeyError. List the three most likely explanations in order of likelihood and the first thing to check for each.
