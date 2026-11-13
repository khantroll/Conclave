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
_CAPABILITY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("code", re.compile(r"\b(code|coding|bug|debug|repository|repo|api|software|programming)\b", re.I)),
    ("research", re.compile(r"\b(research|sources|evidence|current|latest|documentation|docs)\b", re.I)),
    ("reasoning", re.compile(r"\b(compare|evaluate|strategy|tradeoff|trade-off|architecture|why|decision)\b", re.I)),
    ("critical", re.compile(r"\b(risk|failure|critic|skeptical|adversarial|weakness|threat model|security review)\b", re.I)),
    ("creative", re.compile(r"\b(write|creative|story|character|brainstorm|name|design concept)\b", re.I)),
    ("fast", re.compile(r"\b(quick|simple|short|brief|fast)\b", re.I)),
]


def _desired_capabilities(text: str) -> list[str]:
    capabilities: list[str] = []
    for capability, pattern in _CAPABILITY_PATTERNS:
        if pattern.search(text):
            capabilities.append(capability)
    if not capabilities:
        capabilities.append("general")
    return capabilities


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

    desired = _desired_capabilities(text)

    if score <= 1:
        return RequestAnalysis(
            complexity=RequestComplexity.SIMPLE,
            recommended_delegate_count=1,
            desired_capabilities=desired,
            signals=signals,
            rationale="A single model is likely sufficient; a panel would add overhead.",
        )
    if score <= 3:
        return RequestAnalysis(
            complexity=RequestComplexity.STANDARD,
            recommended_delegate_count=2,
            desired_capabilities=desired,
            signals=signals,
            rationale="A second independent perspective is likely useful.",
        )
    if score <= 5:
        return RequestAnalysis(
            complexity=RequestComplexity.COMPLEX,
            recommended_delegate_count=3,
            desired_capabilities=desired,
            signals=signals,
            rationale="The request benefits from multiple independent perspectives and synthesis.",
        )
    return RequestAnalysis(
        complexity=RequestComplexity.DEEP,
        recommended_delegate_count=4,
        desired_capabilities=desired,
        signals=signals,
        rationale="The request is broad or high-complexity enough to justify a full panel.",
    )
