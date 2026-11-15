# Fable 5.2 raw answers (subagent, no tools, 2026-11-15), unedited

**Q1.** SQLite does not enforce foreign keys by default: enforcement is off for each connection unless you turn it on. Run `PRAGMA foreign_keys = ON;` on every connection (it does not persist in the database file, and it is a no-op inside an open transaction). Check with `PRAGMA foreign_keys;` — it should return 1. A less common cause is a build compiled with `SQLITE_OMIT_FOREIGN_KEY`, where the constraint is parsed but never enforced.
Conclusion: Foreign key enforcement is off by default in SQLite, so the cascade never fired; enable it with `PRAGMA foreign_keys = ON` on each connection.
Confidence: high

**Q2.** Let E0 be the expected flips from the start and E1 the expected flips after one head.
E0 = 1 + ½E1 + ½E0
E1 = 1 + ½(0) + ½E0
From the second, E1 = 1 + ½E0. Substituting into the first gives E0 = 1 + ½ + ¼E0 + ½E0, so ¼E0 = 1.5 and E0 = 6.
Conclusion: The expected number of flips is 6.
Confidence: high

**Q3.** The premise is false: Python 3.12 has no `switch` statement. What exists is structural pattern matching, `match`/`case`, added in Python 3.10 (PEP 634). It matches a subject against patterns: literals, sequences, mappings, class patterns with attribute capture, guards (`case x if x > 0`) and a wildcard `case _`. There is no fall-through. A bare name in a pattern captures a value rather than comparing against it, so use dotted names or literals for constants.

Prefer `match` when destructuring structured data such as tuples, dicts, dataclasses or AST-like nodes. Prefer `if/elif` for simple boolean conditions or range checks, and a dict lookup for plain value dispatch.
Conclusion: Python has no `switch`; the nearest feature is `match`/`case` (3.10+), best used for structural destructuring rather than simple comparisons.
Confidence: high

**Q4.** Use a two-proportion z-test. The pooled rate is (500 + 550) / 20,000 = 0.0525.
SE = sqrt(0.0525 × 0.9475 × (2 / 10,000)) ≈ 0.003154.
z = 0.005 / 0.003154 ≈ 1.585, giving a two-sided p ≈ 0.113.
That is below the 1.96 threshold. The 95% confidence interval for the difference is roughly −0.12 to +1.12 percentage points, which includes zero. The test is underpowered for a lift of this size; you would need roughly 31,000 users per arm for 80% power.
Conclusion: No — z ≈ 1.59, p ≈ 0.11, so the difference is not significant at the 5% two-sided level.
Confidence: high

**Q5.** The revert undid the changes from the first merge but not the history: those `feature` commits are still ancestors of `main`. The second merge therefore brings in only the commits made after the first merge. The original feature work stays reverted, so you get a half-applied feature, often with odd conflicts.

The fix is to revert the revert: `git revert <sha-of-the-revert-commit>`.
- Ideally do this on `main` before re-merging `feature`.
- If the second merge is already done, running it afterwards still restores the missing changes; resolve any conflicts.

The alternative is to recreate the branch with new commit IDs (for example `git rebase --no-ff <merge-base>`) before merging, so git treats the commits as new.
Conclusion: The second merge brings in only the new commits while the original changes stay reverted; run `git revert <revert-commit-sha>` to restore them.
Confidence: high

**Q6.** The most likely cause is that `b.a_id` contains at least one NULL. `x NOT IN (1, 2, NULL)` evaluates to UNKNOWN rather than TRUE for any non-matching x, because `x <> NULL` is unknown. So no row passes the WHERE clause.

Two fixes:
- `SELECT * FROM a WHERE NOT EXISTS (SELECT 1 FROM b WHERE b.a_id = a.id)` — NULL-safe and usually optimised well.
- Add `WHERE a_id IS NOT NULL` to the subquery.

A `LEFT JOIN ... WHERE b.a_id IS NULL` also works. Confirm with `SELECT COUNT(*) FROM b WHERE a_id IS NULL`.
Conclusion: A NULL in `b.a_id` makes `NOT IN` evaluate to UNKNOWN for every row; use `NOT EXISTS` or filter out the NULLs.
Confidence: high

**Q7.** It is generally not recommended. Anything in `localStorage` is readable by any JavaScript running on your origin, so one XSS flaw or a compromised third-party script can steal the token and use it elsewhere.

Prefer a cookie set with `HttpOnly`, `Secure` and `SameSite=Lax` or `Strict`, ideally with short-lived sessions and rotation.

The trade-off is that cookies are sent automatically, so you take on CSRF risk and must mitigate it with SameSite, CSRF tokens and Origin checks. Cross-domain API setups also get more awkward. HttpOnly cookies do not neutralise XSS either: an attacker can still make requests from within the page, but cannot take the token away.

For a SPA calling a third-party API, keep the access token in memory and the refresh token in an HttpOnly cookie, or use a backend-for-frontend.
Conclusion: Avoid `localStorage` for session tokens; use HttpOnly, Secure, SameSite cookies and accept the CSRF mitigation work as the trade-off.
Confidence: high

**Q8.** Don't do it now. 200k monthly users is small for Postgres, and four engineers cannot absorb the operational cost of distributed services plus Kafka: deployment, observability, on-call, eventual consistency and distributed debugging. Microservices mainly solve team-scaling problems, which you don't have.

Instead:
- Keep a modular monolith with clear internal boundaries.
- Fix the actual bottlenecks: indexes and query tuning, connection pooling (PgBouncer), caching, a read replica, a bigger instance.
- Move slow work to a background job queue, which can be Postgres-backed.
- Extract a service only where a component has clearly different scaling or isolation needs.

What I would want to know first:
- What is actually hurting: latency, outages, deploy friction?
- Database metrics: CPU, IO, slow queries, connection counts, data size.
- The growth forecast and the read/write mix.
- Peak requests per second.
- Any real event-streaming need.
- Team operations experience.
- Compliance or isolation requirements.
Conclusion: Stay on a well-structured monolith with a tuned Postgres and address measured bottlenecks; microservices and Kafka are premature here.
Confidence: high

**Q9.** From memory, with no way to check here, Nvidia closed at about $926.69 on 7 March 2024. That is the price as quoted at the time, before the 10-for-1 split in June 2024, and equals about $92.67 split-adjusted. I am fairly confident of the neighbourhood: it was the day before the 8 March reversal, when the stock peaked near $974 intraday and closed near $875. I cannot guarantee the cents, so verify against an exchange or market-data source before relying on it.
Conclusion: Approximately $926.69 pre-split (about $92.67 split-adjusted), recalled from memory and worth verifying.
Confidence: medium

**Q10.**
1. **A bug or unhandled path in the library.** An internal dict lookup (a token, field or table lookup) fails on certain malformed inputs and is not wrapped into ValueError. First check: the production traceback, to see which frame raises the KeyError, then reproduce it with the logged input.
2. **A version mismatch.** Production runs a different library version from the one the documentation describes, either a regression or a later fix. First check: the installed version in production (`pip freeze` or the lockfile) against the changelog and issue tracker.
3. **The KeyError does not come from `parse` itself.** It may come from a user-supplied callback, hook or custom mapping, from your own wrapper code, or from misattributed logging. First check: whether the innermost traceback frame is in library code or yours, and what the exception chaining (`__cause__` / `__context__`) shows.
Conclusion: The most likely cause is an unwrapped internal lookup failure in the library, then version drift, then a KeyError originating outside `parse`; the full traceback separates all three.
Confidence: medium
