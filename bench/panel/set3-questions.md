Answer each of the 16 questions independently, from your own knowledge and reasoning only (no tools, no web, no code execution). Reason as carefully as you need, but keep each reply under 250 words. End each reply with two lines in exactly this form:
Answer: <the final answer only, as short as possible>
Confidence: high | medium | low
If a question rests on a false premise, say so in the Answer line. If you cannot work something out reliably, say so and give your best guess with Confidence: low instead of presenting a guess as certain.

S1. In how many ways can you make change for exactly 100 cents using any number of coins of 1, 5, 10, 25, 50 and 100 cents? (Order does not matter.)

S2. How many five-digit numbers (10000 to 99999) have digits that sum to 20?

S3. How many permutations of 8 distinct items leave no item in its original position?

S4. What is the sum of the decimal digits of 2^100?

S5. How many integers from 1 to 10000 are divisible by exactly two of the numbers 3, 5 and 7?

S6. How many distinct arrangements of the letters of MISSISSIPPI have no two S's next to each other?

S7. What is the 20th Catalan number (with C0 = 1, C1 = 1, C2 = 2, C3 = 5)?

S8. What are the last three digits of the 60th Fibonacci number (F1 = F2 = 1)?

S9. What does this print?
def g():
    x = 0
    while True:
        y = yield x
        x = x + (y or 1)
it = g(); a = next(it); b = it.send(5); c = next(it); d = it.send(None)
print(a, b, c, d)

S10. What does this print?
class A:
    x = []
    def __init__(self): self.x = self.x + [1]
class B(A): pass
a = A(); b = B(); A.x.append(9)
print(a.x, b.x, A.x, B.x)

S11. What does this print (one line)?
print(f"{1234.5678:,.2f}|{-0.0:+.1f}|{255:#06x}|{'ab':>5}|{7/2:.0f}|{5/2:.0f}")

S12. What does this print (one line, space separated)?
print(0.1*3, 0.1+0.2==0.3, 1e16+1==1e16, float(2**53+1)==2**53+1)

S13. How many solutions does the cryptarithm TWO + TWO = FOUR have, if each letter is a different digit and neither T nor F is zero?

S14. What does this print (one line, space separated)?
print(~5, 5 ^ 3, -17 >> 2, -17 % 5, 7 & -8, 1 << 70 > 2**69)

S15. What does the str.reverse() method do in Python 3.12, and what does it return?

S16. In SQLite, what does SELECT 5/2, 5/2.0, 5%-3, -5%3, 'a'||1+1, typeof(1/2), 1=1.0, '1'=1 return?
