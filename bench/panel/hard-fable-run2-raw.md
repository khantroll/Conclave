# Fable 5.2 hard set, run 2 (subagent, no tools, 2026-11-15), unedited

**H1.** 7^4 = 2401 ≡ 401 (mod 1000), and 401^5 ≡ 1 + 5·400 ≡ 1, so 7^20 ≡ 1. Since 2025 mod 20 = 5, the result is 7^5 = 16807 ≡ 807.
Answer: 807
Confidence: high

**H2.** Count factors of 5: 405 + 81 + 16 + 3 = 505.
Answer: 505
Confidence: high

**H3.** The default list is shared between the first and third calls; the second call uses its own list.
Answer: [1, 3] [2] [1, 3] True
Confidence: high

**H4.** `a += [4]` mutates the list in place (so `b` and `c` see it); `a = a + [5]` creates a new list.
Answer: [1, 2, 3, 4, 5] [1, 2, 3, 4] [1, 2, 3, 4]
Confidence: high

**H5.** Banker's rounding gives 2, 4, -2; 2.675 is stored slightly below, so it rounds to 2.67; `int` truncates toward zero; floor division and modulo follow the sign of the divisor.
Answer: 2 4 -2 2.67 -3 -4 -2
Confidence: high

**H6.** Aggregates ignore NULLs except `COUNT(*)`; `SUM` stays an integer and `AVG` is a float.
Answer: 4 | 2 | 4 | 2.0 | 2
Confidence: high

**H7.** The first alternative `a` is tried first, then `c` fails at 'b' and `bcd` matches, leaving `d*` empty.
Answer: [('a', 'bcd', '')]
Confidence: high

**H8.** The remainder conditions mean n ≡ -1 (mod 60), so n is 59, 119, ...; 59 is not divisible by 7, and 119 = 7·17.
Answer: 119
Confidence: high

**H9.** Because the host opened at random, the goat reveal is equally likely whether the car is behind door 1 or door 2, so the two are equally likely afterwards.
Answer: 1/2
Confidence: high

**H10.** `reverse=True` keeps the sort stable, so the tied elements stay in original order.
Answer: [('a', 1), ('b', 1), ('c', 0)]
Confidence: high

**H11.** 100 years of 365 days plus 25 leap days (1904 through 1996 gives 24, plus 29 Feb 2000; 1900 was not a leap year and its February precedes the start anyway).
Answer: 36525
Confidence: high

**H12.** I cannot work this out reliably without computation, and I do not have the digit memorised; the figure below is a guess.
Answer: Cannot determine reliably; guess 5
Confidence: low

**H13.** False premise: `itertools.pairwise` was added in Python 3.10, so on 3.9 it does not exist.
Answer: False premise — raises AttributeError on Python 3.9 (pairwise was added in 3.10)
Confidence: high
