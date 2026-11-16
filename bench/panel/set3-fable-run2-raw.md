# Fable 5.2 set 3, run 2 (subagent, no tools, 2026-11-15), unedited

**S1.** Without the 100-cent coin, the standard count using 1, 5, 10, 25 and 50 is 292 (recalled, not re-derived). The single 100-cent coin adds one more way.
Answer: 293
Confidence: high

**S2.** Substitute d1' = d1 − 1, so the five values sum to 19 with d1' ≤ 8 and the others ≤ 9. Unrestricted: C(23,4) = 8855. Subtract d1' ≥ 9: C(14,4) = 1001. Subtract each other digit ≥ 10: 4 × C(13,4) = 2860. Add back d1' ≥ 9 together with another digit ≥ 10: 4. Total 8855 − 1001 − 2860 + 4 = 4998.
Answer: 4998
Confidence: high

**S3.** This is the derangement number D8, from D(n) = (n−1)(D(n−1) + D(n−2)): 0, 1, 2, 9, 44, 265, 1854, 14833.
Answer: 14833
Confidence: high

**S4.** 2^100 = 1267650600228229401496703205376, and its digits sum to 115.
Answer: 115
Confidence: high

**S5.** Multiples of 15, 21 and 35 up to 10000: 666 + 476 + 285 = 1427. Multiples of 105 (95 of them) are counted three times and must be removed entirely: 1427 − 3 × 95 = 1142.
Answer: 1142
Confidence: high

**S6.** Arrange the 7 non-S letters (M, four I's, two P's): 7!/(4!·2!) = 105. Place the four S's in 4 of the 8 gaps: C(8,4) = 70. Product: 105 × 70 = 7350.
Answer: 7350
Confidence: high

**S7.** C20 = C(40,20)/21 = 6564120420 (recalled, not re-derived).
Answer: 6564120420
Confidence: high

**S8.** F60 = 1548008755920 (recalled, not re-derived).
Answer: 920
Confidence: high

**S9.** `next` yields 0. `send(5)` makes x = 5. `next` sends None, so x = 5 + 1 = 6. `send(None)` makes x = 7.
Answer: 0 5 6 7
Confidence: high

**S10.** `self.x + [1]` builds a new instance list `[1]` each time, leaving the class list untouched. The append then changes the class list, which B shares by inheritance.
Answer: [1] [1] [9] [9]
Confidence: high

**S11.** Negative zero keeps its sign. `#06x` pads to width 6 including the `0x` prefix. 3.5 and 2.5 round half to even, giving 4 and 2.
Answer: 1,234.57|-0.0|0x00ff|   ab|4|2
Confidence: high

**S12.** `0.1*3` is 0.30000000000000004. `0.1+0.2` is not equal to 0.3. `1e16+1` rounds back to 1e16. `float(2**53+1)` rounds to 2**53, and the comparison with the exact integer is False.
Answer: 0.30000000000000004 False True False
Confidence: high

**S13.** F must be 1. Working through T = 5 to 9 by case gives exactly these: 734+734=1468, 765+765=1530, 836+836=1672, 846+846=1692, 867+867=1734, 928+928=1856, 938+938=1876.
Answer: 7
Confidence: high

**S14.** `~5` is −6. `5 ^ 3` is 6. `-17 >> 2` floors to −5. `-17 % 5` is 3. `7 & -8` is 0. `1 << 70 > 2**69` is True.
Answer: -6 6 -5 3 0 True
Confidence: high

**S15.** Python strings have no `reverse()` method; calling it raises `AttributeError`. Only lists have `reverse()`, which works in place and returns None. To reverse a string, use `s[::-1]` or `''.join(reversed(s))`.
Answer: False premise: str has no reverse() method (AttributeError)
Confidence: high

**S16.** Integer division gives 2, and 5/2.0 gives 2.5. The `%` result takes the sign of the left operand, giving 2 and −2. `||` binds tighter than `+`, so the expression is `('a'||1)+1`, which is `'a1'+1` = 0 + 1 = 1. `typeof(1/2)` is 'integer'. `1=1.0` is 1. `'1'=1` is 0, because literals have no column affinity and text never equals an integer.
Answer: 2 | 2.5 | 2 | -2 | 1 | integer | 1 | 0
Confidence: high
