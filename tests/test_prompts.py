from conclave.models import DelegateResult, DelegateStatus
from conclave.prompts import build_arbiter_prompt, build_delegate_prompt


def test_delegate_prompt_includes_role_context_and_question():
    prompt = build_delegate_prompt(
        question="Should we build it?",
        role="Be a skeptical product reviewer.",
        workspace_context="Project is local-first.",
    )

    assert "skeptical product reviewer" in prompt
    assert "Project is local-first" in prompt
    assert "Should we build it?" in prompt
    assert "independently" in prompt


def test_arbiter_prompt_includes_only_successful_responses():
    prompt = build_arbiter_prompt(
        question="Which design?",
        delegate_results=[
            DelegateResult(
                name="a",
                status=DelegateStatus.SUCCEEDED,
                raw_response="Use design A.",
                model="model-a",
            ),
            DelegateResult(
                name="b",
                status=DelegateStatus.FAILED,
                error="boom",
            ),
        ],
    )

    assert "Use design A." in prompt
    assert "model-a" in prompt
    assert "boom" not in prompt
    assert "Prefer evidence" in prompt
