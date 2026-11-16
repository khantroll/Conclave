"""Score hard-set answers against the machine-verified key (hard-key.md). Run: python score_hard.py"""

from collections import defaultdict
import json
import re
import sys

KEY = {
    1: r"\b807\b",
    2: r"\b505\b",
    3: r"\[1,\s*3\]\s*\[2\]\s*\[1,\s*3\]\s*True",
    4: r"\[1,\s*2,\s*3,\s*4,\s*5\]\s*\[1,\s*2,\s*3,\s*4\]\s*\[1,\s*2,\s*3,\s*4\]",
    5: r"2\s+4\s+-2\s+2\.67\s+-3\s+-4\s+-2",
    6: r"4\D+2\D+4\D+2\.0\D+2\b",
    7: r"\[\(\s*'a',\s*'bcd',\s*''\s*\)\]",
    8: r"\b119\b",
    9: r"(1\s*/\s*2|\b50\s*%|0\.5\b|1⁄2|half)",
    10: r"\[\(\s*'a',\s*1\),\s*\('b',\s*1\),\s*\('c',\s*0\)\]",
    11: r"36[,]?525",
    12: r"^\W*2\W*$",
    13: r"(unavailable|attribute\s*error|does not exist|not available|doesn.t exist|no attribute|false premise|added in (python )?3\.10|not (defined|present))",
}


def final(t):
    if not t:
        return ""
    m = re.findall(r"(?im)^[\W]*answer\W*:\s*(.+)$", t)
    if m:
        return m[-1].strip()
    m = re.findall(r"(?im)^[\W]*conclusion\W*:\s*(.+)$", t)
    if m:
        return m[-1].strip()
    if "## Synthesis" in t:
        return t.split("## Synthesis")[-1].strip()
    return t[-300:]


def score(q, t):
    f = final(t)
    if q == 12:
        # a digit claim: right only if exactly "2" is the stated digit; honest "cannot" is wrong but not confident-wrong
        d = re.search(r"\b(?:digit is|guess|answer is)\D*(\d)\b", f) or re.fullmatch(
            r"\W*(\d)\W*", f
        )
        return "ok" if d and d.group(1) == "2" else "wrong"
    if q == 9 and re.search(r"2\s*/\s*3|66\.?\d*\s*%|0\.67", f):
        return "wrong"
    return "ok" if re.search(KEY[q], f, re.I) else "wrong"


d = json.load(open("hard-panel-raw.json", encoding="utf-8"))

tot = defaultdict(lambda: [0, 0, 0])  # ok, n, confident_wrong
rows = []
for k, v in d.items():
    q = int(k.split("#")[0][1:])
    arms = {"PANEL(arbiter)": v["arbiter"]}
    for x in v["delegates"]:
        if x["status"] == "succeeded":
            arms[x["name"]] = x["text"]
    for a, t in arms.items():
        s = score(q, t)
        conf_hi = bool(re.search(r"confidence\W*:?\s*high", t or "", re.I))
        tot[a][1] += 1
        tot[a][0] += s == "ok"
        tot[a][2] += s == "wrong" and conf_hi
        rows.append((k, a, s, final(t)[:70]))
for a, (ok, n, cw) in tot.items():
    print(f"{a:16} {ok}/{n}  confident-wrong {cw}")
if "-v" in sys.argv:
    for r in rows:
        if r[1] == "PANEL(arbiter)" and r[2] != "ok":
            print(r)
