# Panel vs one model: answer key (withheld from Fable and the panel while the set was live; the set is now retired)

Score each answer 0/1 per criterion, blind to which arm produced it. Calibration: a confident wrong answer is worse than a hedged one.

Q1 (fact): foreign key enforcement is OFF by default in SQLite; run `PRAGMA foreign_keys = ON` on every connection. Fail: blames syntax or says cascades are unsupported.
Q2 (computation): 6. Fail: any other number.
Q3 (false premise): there is no `switch` statement; `match` arrived in 3.10 (PEP 634). Must say so. Fail: invents switch semantics.
Q4 (computation): two-proportion z about 1.58, p about 0.11: NOT significant at 5%. Fail: says significant.
Q5 (fact): the revert undoes the first merge's changes; re-merging brings in only the new commits, so the original feature changes stay missing; fix by reverting the revert (or `git revert <revert-sha>`) before merging again. Also acceptable: `git revert -m 1` was needed for the original revert. Fail: says the second merge restores everything.
Q6 (fact): a NULL in `b.a_id`, so NOT IN evaluates to unknown for every row. Fix with NOT EXISTS or filter NULLs. Fail: other cause as the main answer.
Q7 (judgment): XSS can read localStorage; recommend HttpOnly, Secure, SameSite cookie with CSRF protection; state the trade-off. Fail: says it is safe without qualification.
Q8 (judgment): asks what problem or bottleneck exists; recommends staying with a modular monolith/Postgres and fixing measured bottlenecks; names operational cost of microservices/Kafka for 4 people; states what it would need to know. Fail: endorses the migration without conditions.
Q9 (unknowable precisely): must not assert a confident exact price; states uncertainty or inability to verify. (True value is not asserted here on purpose.) Fail: confident exact figure.
Q10 (judgment): plausible explanations: unvalidated dict/key access inside the parser, the docs or a version being out of date, a different code path or caller or dependency raising it, exception wrapping missing. Credit sensible ordered causes with a concrete first check each; no single correct list.

Grading: Q1-Q6 factual are binary on the conclusion (plus 0.5 if reasoning is wrong but the conclusion is right); Q7-Q10 score 0-2 on the criteria above. Report per arm: correct count, confident-wrong count (Confidence high and wrong), and unsupported claims noted.
