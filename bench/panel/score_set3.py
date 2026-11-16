"""Score set-3 answers against the machine-verified key (set3-key.md). Run: python score_set3.py [-v]"""

from collections import defaultdict
import json
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")

KEY = {
    1: r"\b293\b",
    2: r"\b4,?998\b",
    3: r"\b14,?833\b",
    4: r"\b115\b",
    5: r"\b1,?142\b",
    6: r"\b7,?350\b",
    7: r"6,?564,?120,?420",
    8: r"\b920\b",
    9: r"0\s+5\s+6\s+7",
    10: r"\[1\]\s*\[1\]\s*\[9\]\s*\[9\]",
    11: r"1,234\.57\|-0\.0\|0x00ff\|\s+ab\|4\|2",
    12: r"0\.30000000000000004\s+False\s+True\s+False",
    13: r"\b7\b",
    14: r"-6\s+6\s+-5\s+3\s+0\s+True",
    15: r"(no (attribute|method)|attribute\s*error|false premise|does not exist|doesn.t exist|has no|not a valid|no such)",
    16: r"2\s*\|?\s*,?\s*2\.5\s*\|?\s*,?\s*2\s*\|?\s*,?\s*-2\s*\|?\s*,?\s*1\s*\|?\s*,?\s*'?integer'?\s*\|?\s*,?\s*1\s*\|?\s*,?\s*0\b",
}


def final(t):
    if not t:
        return ""
    for lab in ("answer", "conclusion"):
        m = re.findall(rf"(?im)^[\W]*{lab}\W*:\s*(.+)$", t)
        if m:
            return m[-1].strip()
    if "## Synthesis" in t:
        return t.split("## Synthesis")[-1].strip()
    return t[-300:]


def score(q, t):
    return "ok" if re.search(KEY[q], final(t), re.I) else "wrong"


if __name__ == "__main__":
    d = json.load(open("set3-panel-raw.json", encoding="utf-8"))
    tot = defaultdict(lambda: [0, 0, 0])
    rows = []
    for k, v in d.items():
        q = int(k.split("#")[0][1:])
        arms = {"PANEL(arbiter)": v["arbiter"]}
        for x in v["delegates"]:
            if x["status"] == "succeeded":
                arms[x["name"]] = x["text"]
        for a, t in arms.items():
            s = score(q, t)
            hi = bool(re.search(r"confidence\W*:?\s*high", t or "", re.I))
            tot[a][1] += 1
            tot[a][0] += s == "ok"
            tot[a][2] += s == "wrong" and hi
            rows.append((k, a, s, final(t)[:90]))
    print(len(d), "deliberations")
    for a, (ok, n, cw) in tot.items():
        print(f"{a:16} {ok}/{n}  confident-wrong {cw}")
    if "-v" in sys.argv:
        for r in rows:
            if r[2] != "ok":
                print(r)
