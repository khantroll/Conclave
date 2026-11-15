Answer each of the 13 questions independently, from your own knowledge and reasoning only (no tools, no web, no code execution). Work it out as carefully as you need, but keep each reply under 200 words. End each reply with two lines in exactly this form:
Answer: <the final answer only, as short as possible>
Confidence: high | medium | low
If a question rests on a false premise, say so in the Answer line. If you cannot work something out reliably, say so and give your best guess with Confidence: low instead of presenting a guess as certain.

H1. What are the last three digits of 7^2025?

H2. How many trailing zeros does 2026! (2026 factorial) have in base 10?

H3. What does this print?
def f(a, b=[]):
    b.append(a)
    return b
x = f(1); y = f(2, []); z = f(3)
print(x, y, z, x is z)

H4. What does this print?
a = [1, 2, 3]; b = a; a += [4]; c = a; a = a + [5]
print(a, b, c)

H5. What does this print (one line, space separated)?
print(round(2.5), round(3.5), round(-2.5), round(2.675, 2), int(-7/2), -7//2, 7 % -3)

H6. In SQLite, with CREATE TABLE t(x); INSERT INTO t VALUES (1),(NULL),(3),(NULL); what does SELECT COUNT(*), COUNT(x), SUM(x), AVG(x), COUNT(DISTINCT x) FROM t return?

H7. What does Python's re.findall(r'(a|ab)(c|bcd)(d*)', 'abcd') return?

H8. What is the smallest positive integer that leaves remainder 1 when divided by 2, remainder 2 when divided by 3, remainder 3 when divided by 4, remainder 4 when divided by 5, remainder 5 when divided by 6, and is divisible by 7?

H9. Monty Hall variant: three doors, one car. You pick door 1. The host, who does NOT know where the car is, opens door 2 or 3 at random; he happens to open door 3 and it shows a goat. What is the probability that you win the car if you switch to door 2?

H10. What does this print?
print(sorted([('a', 1), ('b', 1), ('c', 0)], key=lambda t: t[1], reverse=True))

H11. How many days are there from 1 March 1900 to 1 March 2000?

H12. What is the 1000th digit after the decimal point of the square root of 2?

H13. What does itertools.pairwise([1, 2, 3]) return when run on Python 3.9?
