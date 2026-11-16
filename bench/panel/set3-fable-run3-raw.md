# Fable 5.2 set 3, run 3 (subagent, no tools, 2026-11-15), unedited

**S1.** Standard coin-change count: 292 ways using coins up to 50 cents, plus 1 for the single 100-cent coin (recalled, not re-derived).
Answer: 293
Confidence: high

**S2.** Substitute a = d1 − 1 (0..8), with the other four digits 0..9, summing to 19. Unrestricted: C(23,4) = 8855. Subtract a ≥ 9: C(14,4) = 1001. Subtract each other digit ≥ 10: 4 × C(13,4) = 2860. Add back a ≥ 9 together with one other ≥ 10: 4 × 1 = 4. Total 8855 − 1001 − 2860 + 4 = 4998.
Answer: 4998
Confidence: high

**S3.** This is the derangement number D8, built up from D7 = 1854: D8 = 8 × 1854 + 1 = 14833.
Answer: 14833
Confidence: high

**S4.** 2^100 = 1267650600228229401496703205376, and its digits sum to 115.
Answer: 115
Confidence: high

**S5.** Multiples of 15: 666; of 21: 476; of 35: 285; of 105: 95. Exactly two = 666 + 476 + 285 − 3 × 95 = 1142.
Answer: 1142
Confidence: high

**S6.** Arrange the 7 non-S letters (M, I×4, P×2): 7!/(4!·2!) = 105. Place the 4 S's in distinct gaps out of 8: C(8,4) = 70. Product: 105 × 70 = 7350.
Answer: 7350
Confidence: high

**S7.** C20 = C(40,20)/21 = 137846528820/21 = 6564120420.
Answer: 6564120420
Confidence: high

**S8.** F60 = 1548008755920, so the last three digits are 920.
Answer: 920
Confidence: high

**S9.** `next` yields 0. `send(5)` makes x = 5. `next` sends None, so x = 5 + 1 = 6. `send(None)` makes x = 7.
Answer: 0 5 6 7
Confidence: high

**S10.** `self.x = self.x + [1]` creates a new instance list `[1]` each time and leaves the class list untouched. The later append changes the shared class list, which B inherits.
Answer: [1] [1] [9] [9]
Confidence: high

**S11.** The pieces are: `1,234.57`; `-0.0` (negative zero keeps its sign); `0x00ff` (width 6 includes the prefix); `ab` right-aligned in width 5; 3.5 rounds to 4 and 2.5 rounds to 2 (round-half-even).
Answer: 1,234.57|-0.0|0x00ff|   ab|4|2
Confidence: high

**S12.** 0.1*3 is 0.30000000000000004. 0.1+0.2 is not equal to 0.3. 1e16+1 rounds back to 1e16 (spacing is 2 at that magnitude, tie goes to even). float(2**53+1) rounds to 2**53, and the comparison with the exact integer 2**53+1 is False.
Answer: 0.30000000000000004 False True False
Confidence: high

**S13.** F must be 1. The solutions are 734, 765, 836, 846, 867, 928 and 938 (for example 765 + 765 = 1530).
Answer: 7
Confidence: high

**S14.** ~5 = −6; 5^3 = 6; −17>>2 = −5 (floor); −17%5 = 3; 7 & −8 = 0; 2^70 > 2^69 is True.
Answer: -6 6 -5 3 0 True
Confidence: high

**S15.** Python strings have no `reverse()` method; calling it raises AttributeError. Only lists have `reverse()` (in place, returning None). To reverse a string, use `s[::-1]` or `''.join(reversed(s))`.
Answer: False premise — str has no reverse() method (AttributeError); use s[::-1]
Confidence: high

**S16.**
- 5/2 = 2 (integer division).
- 5/2.0 = 2.5.
- 5%-3 = 2 and -5%3 = -2 (the result takes the sign of the left operand).
- 'a'||1+1 = 1, because `||` binds tighter than `+`, so it is ('a1') + 1, and 'a1' converts to 0.
- typeof(1/2) = 'integer'.
- 1=1.0 gives 1.
- '1'=1 gives 0 (a text literal and an integer literal have no affinity, so no conversion happens).

Answer: 2 | 2.5 | 2 | -2 | 1 | integer | 1 | 0
Confidence: medium
