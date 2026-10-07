from conclave.models import ProviderDescriptor, RequestAnalysis, RequestComplexity
from conclave.selection import select_delegates


def test_selection_prefers_matching_capabilities():
    analysis = RequestAnalysis(
        complexity=RequestComplexity.COMPLEX,
        recommended_delegate_count=2,
        desired_capabilities=["code", "critical"],
        rationale="test",
    )
    descriptors = {
        "coder": ProviderDescriptor(
            name="coder", capabilities=["general", "code"], priority=20
        ),
        "critic": ProviderDescriptor(
            name="critic", capabilities=["critical"], priority=30
        ),
        "generic": ProviderDescriptor(
            name="generic", capabilities=["general"], priority=10
        ),
    }

    selection = select_delegates(
        analysis=analysis,
        candidates=["generic", "critic", "coder"],
        descriptors=descriptors,
    )

    assert selection.selected == ["coder", "critic"]


def test_selection_never_exceeds_workspace_candidates():
    analysis = RequestAnalysis(
        complexity=RequestComplexity.DEEP,
        recommended_delegate_count=4,
        desired_capabilities=["reasoning"],
        rationale="test",
    )
    selection = select_delegates(
        analysis=analysis,
        candidates=["one", "two"],
        descriptors={},
    )
    assert selection.selected == ["one", "two"]
