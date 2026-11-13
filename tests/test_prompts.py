from conclave.models import DelegateResult, DelegateStatus
from conclave.prompts import build_arbiter_prompt, build_critic_prompt, build_delegate_prompt


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


def test_critic_prompt_excludes_failed_provider_error():
    prompt = build_critic_prompt(
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
                error="secret provider failure",
            ),
        ],
    )

    assert "Use design A." in prompt
    assert "secret provider failure" not in prompt
    assert "Do not synthesize a final answer" in prompt


def test_arbiter_prompt_includes_successful_critic():
    critic = DelegateResult(
        name="critic",
        status=DelegateStatus.SUCCEEDED,
        raw_response="The evidence for A is weak.",
    )
    prompt = build_arbiter_prompt(
        question="Which design?",
        delegate_results=[
            DelegateResult(
                name="a",
                status=DelegateStatus.SUCCEEDED,
                raw_response="Use design A.",
                model="model-a",
            ),
        ],
        critic_result=critic,
    )

    assert "Use design A." in prompt
    assert "The evidence for A is weak." in prompt
    assert "Prefer evidence" in prompt
