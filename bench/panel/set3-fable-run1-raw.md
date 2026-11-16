# Fable 5.2 set 3, run 1 (subagent, no tools, 2026-11-15), unedited

**S1.** The classic count with 1, 5, 10, 25 and 50 is 292 (recalled, not re-derived here); the 100-cent coin adds one more way.
Answer: 293
Confidence: high

**S2.** Put d1' = d1 − 1 (0..8), so the five variables sum to 19 with d1' ≤ 8 and the others ≤ 9. Unrestricted: C(23,4) = 8855. Subtract d1' ≥ 9: C(14,4) = 1001. Subtract one other digit ≥ 10: 4 × C(13,4) = 2860. Add back d1' ≥ 9 together with another digit ≥ 10: 4 × 1 = 4. Total 8855 − 1001 − 2860 + 4 = 4998.
Answer: 4998
Confidence: high

**S3.** Derangements: D(n) = (n−1)(D(n−1) + D(n−2)) gives 0, 1, 2, 9, 44, 265, 1854, 14833.
Answer: 14833
Confidence: high

**S4.** 2^100 = 1267650600228229401496703205376, whose digits sum to 115.
Answer: 115
Confidence: high

**S5.** Multiples of 15: 666; of 21: 476; of 35: 285; of 105: 95. Exactly two = (666 + 476 + 285) − 3 × 95 = 1142.
Answer: 1142
Confidence: high

**S6.** Arrange the 7 non-S letters (M, 4 I's, 2 P's): 7!/(4!·2!) = 105. Place the 4 S's in 4 of the 8 gaps: C(8,4) = 70. 105 × 70 = 7350.
Answer: 7350
Confidence: high

**S7.** C20 = C(40,20)/21 = 137846528820/21 = 6564120420.
Answer: 6564120420
Confidence: high

**S8.** F60 = 1548008755920.
Answer: 920
Confidence: high

**S9.** `next` yields 0. `send(5)` makes x = 5. `next` sends None, so x = 6. `send(None)` makes x = 7.
Answer: 0 5 6 7
Confidence: high

**S10.** `self.x = self.x + [1]` creates a new instance list `[1]` each time and leaves the class list untouched. The later append changes only the class list, which B inherits.
Answer: [1] [1] [9] [9]
Confidence: high

**S11.** Negative zero keeps its sign, `#06x` pads to width 6 including the `0x`, and `.0f` rounds half to even (3.5 → 4, 2.5 → 2).
Answer: 1,234.57|-0.0|0x00ff|   ab|4|2
Confidence: high

**S12.** 0.1*3 is 0.30000000000000004. 0.1+0.2 is not 0.3. 1e16+1 rounds back to 1e16. float(2**53+1) rounds to 2**53, which is not equal to the exact integer 2**53+1.
Answer: 0.30000000000000004 False True False
Confidence: high

**S13.** F must be 1. The solutions are 734, 765, 836, 846, 867, 928 and 938 (giving 1468, 1530, 1672, 1692, 1734, 1856, 1876).
Answer: 7
Confidence: high

**S14.** ~5 = −6; 5^3 = 6; −17>>2 floors to −5; −17 % 5 = 3; 7 & −8 = 0; 2^70 > 2^69 is True.
Answer: -6 6 -5 3 0 True
Confidence: high

**S15.** False premise: `str` has no `reverse()` method (strings are immutable), so calling it raises AttributeError. `list.reverse()` exists, reverses in place and returns None. For strings use `s[::-1]` or `''.join(reversed(s))`.
Answer: False premise — str.reverse() does not exist (AttributeError)
Confidence: high

**S16.** Integer division gives 2; 5/2.0 gives 2.5; `%` takes the sign of the dividend (2 and −2). `||` binds tighter than `+`, so `('a'||1)+1` is `'a1'+1` = 0 + 1 = 1. `typeof(1/2)` is 'integer'. `1=1.0` is 1. `'1'=1` is 0, because literals have no column affinity and text never equals an integer.
Answer: 2 | 2.5 | 2 | -2 | 1 | integer | 1 | 0
Confidence: medium
