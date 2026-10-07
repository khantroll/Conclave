from __future__ import annotations

import re

from .models import RequestAnalysis, RequestComplexity

_COMPLEX_TERMS = re.compile(
    r"\b(compare|evaluate|architecture|design|tradeoff|trade-off|strategy|research|"
    r"recommend|why|risk|failure|implementation|plan|analyze|analyse)\b",
    re.IGNORECASE,
)
_DEEP_TERMS = re.compile(
    r"\b(comprehensive|deep dive|adversarial|evidence|sources|multi-step|roadmap|"
    r"benchmark|root cause|security review|threat model)\b",
    re.IGNORECASE,
)


def analyze_request(question: str) -> RequestAnalysis:
    text = question.strip()
    signals: list[str] = []
    score = 0

    word_count = len(text.split())
    if word_count >= 80:
        score += 2
        signals.append("long request")
    elif word_count >= 35:
        score += 1
        signals.append("moderate request length")

    complex_hits = len(_COMPLEX_TERMS.findall(text))
    if complex_hits >= 3:
        score += 2
        signals.append("multiple analysis/decision terms")
    elif complex_hits:
        score += 1
        signals.append("analysis/decision term")

    if _DEEP_TERMS.search(text):
        score += 2
        signals.append("deep-reasoning signal")

    if text.count("?") >= 3 or text.count("\n") >= 4:
        score += 1
        signals.append("multi-part request")

    if score <= 1:
        return RequestAnalysis(
            complexity=RequestComplexity.SIMPLE,
            recommended_delegate_count=1,
            signals=signals,
            rationale="A single model is likely sufficient; a panel would add overhead.",
        )
    if score <= 3:
        return RequestAnalysis(
            complexity=RequestComplexity.STANDARD,
            recommended_delegate_count=2,
            signals=signals,
            rationale="A second independent perspective is likely useful.",
        )
    if score <= 5:
        return RequestAnalysis(
            complexity=RequestComplexity.COMPLEX,
            recommended_delegate_count=3,
            signals=signals,
            rationale="The request benefits from multiple independent perspectives and synthesis.",
        )
    return RequestAnalysis(
        complexity=RequestComplexity.DEEP,
        recommended_delegate_count=4,
        signals=signals,
        rationale="The request is broad or high-complexity enough to justify a full panel.",
    )
