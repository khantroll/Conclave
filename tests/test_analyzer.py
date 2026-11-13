from conclave.analyzer import analyze_request
from conclave.models import RequestComplexity


def test_short_fact_question_stays_single_model():
    result = analyze_request("What is RAID 10?")
    assert result.complexity == RequestComplexity.SIMPLE
    assert result.recommended_delegate_count == 1
    assert result.desired_capabilities == ["general"]


def test_decision_question_recommends_panel():
    result = analyze_request(
        "Compare these two architecture strategies, evaluate implementation risk, "
        "failure modes, tradeoffs, and recommend a roadmap with evidence and a security review."
    )
    assert result.complexity in {RequestComplexity.COMPLEX, RequestComplexity.DEEP}
    assert result.recommended_delegate_count >= 3
    assert result.signals
    assert "reasoning" in result.desired_capabilities
    assert "critical" in result.desired_capabilities
