# Fable 5.2 hard set, run 1 (subagent, no tools, 2026-11-15), unedited

**H1.** 7^4 = 2401 ≡ 401 (mod 1000), and 401^5 ≡ 1 + 5·400 ≡ 1, so 7^20 ≡ 1. Since 2025 ≡ 5 (mod 20), 7^2025 ≡ 7^5 = 16807 ≡ 807.
Answer: 807
Confidence: high

**H2.** Count factors of 5: 405 + 81 + 16 + 3 = 505.
Answer: 505
Confidence: high

**H3.** The default list is shared between the calls `f(1)` and `f(3)`, so x and z are the same object; y uses its own list.
Answer: [1, 3] [2] [1, 3] True
Confidence: high

**H4.** `a += [4]` mutates the list in place (b and c still point to it); `a = a + [5]` creates a new list.
Answer: [1, 2, 3, 4, 5] [1, 2, 3, 4] [1, 2, 3, 4]
Confidence: high

**H5.** Python rounds halves to even; 2.675 is stored slightly below 2.675; `int` truncates toward zero; `//` floors; `%` takes the sign of the divisor.
Answer: 2 4 -2 2.67 -3 -4 -2
Confidence: high

**H6.** `COUNT(*)` counts all rows; the other aggregates ignore NULLs; `AVG` returns a float.
Answer: 4 | 2 | 4 | 2.0 | 2
Confidence: high

**H7.** Group 1 tries `a` first; then `c` fails at "b", `bcd` matches, and `d*` matches the empty string.
Answer: [('a', 'bcd', '')]
Confidence: high

**H8.** The remainder conditions mean N ≡ −1 (mod 60), so N = 60k − 1. Divisibility by 7 needs 4k ≡ 1 (mod 7), so k = 2 and N = 119 = 7·17.
Answer: 119
Confidence: high

**H9.** Because the host opened a door at random, seeing a goat is equally likely whether the car is behind door 1 or door 2 (each 1/3 · 1/2). The two cases stay equally likely.
Answer: 1/2
Confidence: high

**H10.** Python's sort is stable even with `reverse=True`, so the tied elements keep their original order.
Answer: [('a', 1), ('b', 1), ('c', 0)]
Confidence: high

**H11.** 100 years × 365 = 36500, plus 25 leap days (29 Feb in 1904, 1908, …, 2000; 1900 was not a leap year and is before the start anyway).
Answer: 36525
Confidence: high

**H12.** I cannot compute or recall this digit reliably without tools; the digit below is a guess, not a worked result.
Answer: Cannot determine reliably; best guess 8
Confidence: low

**H13.** False premise: `itertools.pairwise` was added in Python 3.10, so on 3.9 it does not exist. (On 3.10+ it returns an iterator yielding (1, 2), (2, 3), not a list.)
Answer: False premise — it returns nothing; raises AttributeError: module 'itertools' has no attribute 'pairwise'
Confidence: high
