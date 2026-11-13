"""Machinery for the adversarial suite (P1-2): scenarios, traces and containment checks.

A *scenario* is one route by which hostile model text reaches a later prompt: a delegate
answer going to the Critic or the Arbiter, Critic output going to the Arbiter, the three kinds
of retry (each rebuilds judge prompts from stored results), and fallback judges. Each scenario
is run twice: once with the hostile text and once with a short benign *control* in the same
slot. Whatever the model text says, the two runs must behave identically.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from conclave.models import DeliberationRequest, DeliberationResult
from conclave.orchestrator import Orchestrator
from conclave.prompts import marker_token
from conclave.providers.fake import FakeProvider

CORPUS_PATH = Path(__file__).with_name("corpus.json")
SEED = "adversarial-seed-0123456789abcdef"
TOKEN = marker_token(SEED)

BENIGN = "A neutral, benign answer."
HONEST = "Honest answer."
CRITIC_OK = "Benign critique."
CONTEXT = "Workspace context: the project is local-first."

SYNTHESIS = "Benign synthesis."
JUDGES = {"critic", "critic-fb", "arbiter", "arbiter-fb"}
DELEGATES = {"attacker", "honest"}

# A well-formed marker block, whatever its label. Model text cannot contain a literal
# ``<<<`` once escaped, so this can only match the markers Conclave itself wrote.
BLOCK = re.compile(rf"<<<(?:RESPONSE [A-Z]+|CRITIC) {TOKEN}>>>.*?<<<END [A-Z]+ {TOKEN}>>>", re.S)


def expand(text) -> str:
    """Turn a corpus ``text`` value into the string it describes."""
    if isinstance(text, str):
        return text.replace("{{TOKEN}}", TOKEN)
    if "repeat" in text:
        return expand(text["repeat"]) * text["times"]
    return "".join(expand(part) for part in text["parts"])


def load_fixtures() -> list[dict]:
    data = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    return [{**item, "text": expand(item["text"])} for item in data["fixtures"]]


class Recorder(FakeProvider):
    """A fake provider that records every prompt it is sent, in order."""

    def __init__(self, name, log, response, *, error=None, model="fake-model"):
        super().__init__(response, error=error, model=model)
        self.name = name
        self.log = log

    async def ask(self, prompt):
        self.log.append((self.name, prompt))
        return await super().ask(prompt)


def make_orchestrator(log, *, attacker=BENIGN, critic=CRITIC_OK, attacker_error=None,
                      critic_error=None, arbiter_error=None, attacker_model="attacker-model"):
    providers = {
        "attacker": Recorder("attacker", log, attacker, error=attacker_error, model=attacker_model),
        "honest": Recorder("honest", log, HONEST, model="honest-model"),
        "critic": Recorder("critic", log, critic, error=critic_error, model="critic-model"),
        "critic-fb": Recorder("critic-fb", log, CRITIC_OK, model="critic-fb-model"),
        "arbiter": Recorder("arbiter", log, "Benign synthesis.", error=arbiter_error, model="arbiter-model"),
        "arbiter-fb": Recorder("arbiter-fb", log, "Benign synthesis.", model="arbiter-fb-model"),
    }
    return Orchestrator(providers), providers


def make_request() -> DeliberationRequest:
    return DeliberationRequest(
        question="What should we do?",
        delegates=["attacker", "honest"],
        critic="critic",
        critic_fallbacks=["critic-fb"],
        arbiter="arbiter",
        arbiter_fallbacks=["arbiter-fb"],
        workspace_context=CONTEXT,
        minimum_successes=2,
        seed=SEED,
        single_source_mode="return_answer",
    )


@dataclass
class Run:
    calls: list  # [(provider name, prompt)] for the part of the scenario under test
    result: DeliberationResult


# ---------------------------------------------------------------- scenarios
# Each takes the text to place in the hostile slot and returns a Run.


async def delegate_to_critic(text):
    log = []
    orchestrator, _ = make_orchestrator(log, attacker=text)
    return Run(log, await orchestrator.deliberate(make_request()))


async def delegate_to_arbiter(text):
    return await delegate_to_critic(text)  # the same run; the Arbiter prompt is checked too


async def critic_to_arbiter(text):
    log = []
    orchestrator, _ = make_orchestrator(log, critic=text)
    return Run(log, await orchestrator.deliberate(make_request()))


async def hostile_model_metadata(text):
    """The provider's reply names its model with hostile text, which sits in a prompt header."""
    log = []
    orchestrator, _ = make_orchestrator(log, attacker_model=text)
    return Run(log, await orchestrator.deliberate(make_request()))


async def below_quorum(text):
    """Only the attacker's source answers while the quorum is 2: no judge may ever run."""
    log = []
    orchestrator, providers = make_orchestrator(log, attacker=text)
    providers["honest"].error = RuntimeError("down")
    return Run(log, await orchestrator.deliberate(make_request()))


async def retry_delegate(text):
    log = []
    orchestrator, providers = make_orchestrator(log, attacker_error=RuntimeError("down"))
    request = make_request()
    first = await orchestrator.deliberate(request)  # quorum unmet: no judge has run yet
    providers["attacker"].error = None
    providers["attacker"].response = text
    start = len(log)
    retried = await orchestrator.retry_delegate(
        request=request, prior_result=first, delegate_name="attacker"
    )
    return Run(log[start:], retried)


async def retry_critic(text):
    log = []
    orchestrator, _ = make_orchestrator(log, attacker=text)
    request = make_request()
    first = await orchestrator.deliberate(request)
    start = len(log)
    retried = await orchestrator.retry_critic(request=request, prior_result=first)
    return Run(log[start:], retried)


async def retry_arbiter(text):
    log = []
    orchestrator, _ = make_orchestrator(log, attacker=text, critic=text)
    request = make_request()
    first = await orchestrator.deliberate(request)
    start = len(log)
    retried = await orchestrator.retry_arbiter(request=request, prior_result=first)
    return Run(log[start:], retried)


async def fallback_critic(text):
    log = []
    orchestrator, _ = make_orchestrator(log, attacker=text, critic_error=RuntimeError("critic down"))
    return Run(log, await orchestrator.deliberate(make_request()))


async def fallback_arbiter(text):
    log = []
    orchestrator, _ = make_orchestrator(
        log, attacker=text, critic=text, arbiter_error=RuntimeError("arbiter down")
    )
    return Run(log, await orchestrator.deliberate(make_request()))


@dataclass(frozen=True)
class Scenario:
    name: str
    run: object
    delegate_hostile: bool  # the hostile text is a delegate answer
    critic_hostile: bool  # the hostile text is Critic output
    judges: bool = True  # a judge is expected to run (False when the quorum cannot be met)


SCENARIOS = [
    Scenario("delegate_to_critic", delegate_to_critic, True, False),
    Scenario("delegate_to_arbiter", delegate_to_arbiter, True, False),
    Scenario("critic_to_arbiter", critic_to_arbiter, False, True),
    Scenario("below_quorum", below_quorum, True, False, judges=False),
    Scenario("retry_delegate", retry_delegate, True, False),
    Scenario("retry_critic", retry_critic, True, False),
    Scenario("retry_arbiter", retry_arbiter, True, True),
    Scenario("fallback_critic", fallback_critic, True, False),
    Scenario("fallback_arbiter", fallback_arbiter, True, True),
]
# Not in the main grid: the hostile text is metadata, not a response, so the prompt's header
# line (outside the markers) legitimately differs from the control and is checked separately.
METADATA_SCENARIO = Scenario("hostile_model_metadata", hostile_model_metadata, False, False)
SCENARIO_BY_NAME = {s.name: s for s in [*SCENARIOS, METADATA_SCENARIO]}


@lru_cache(maxsize=None)
def run_scenario(name: str, fixture_id: str | None) -> Run:
    """Run a scenario with a fixture's hostile text, or with the benign control if None."""
    text = BENIGN if fixture_id is None else FIXTURES_BY_ID[fixture_id]["text"]
    return asyncio.run(SCENARIO_BY_NAME[name].run(text))


FIXTURES = load_fixtures()
FIXTURES_BY_ID = {item["id"]: item for item in FIXTURES}


# ------------------------------------------------------------------- traces


def trace(run: Run) -> dict:
    """Everything about what the orchestration *did*, and nothing about what was said."""
    result = run.result
    panel = result.panel
    return {
        "calls": [name for name, _ in run.calls],
        # A delegate's prompt is a function of the question and context alone, so another
        # model's output can never reach it.
        "delegate_prompts": {name: prompt for name, prompt in run.calls if name in DELEGATES},
        "delegates": [(d.name, d.status.value, d.error_kind) for d in panel.delegates],
        "critic": (result.critic.name, result.critic.status.value) if result.critic else None,
        "arbiter": (result.arbiter.name, result.arbiter.status.value) if result.arbiter else None,
        "sources": panel.independent_source_count,
        "single_source": result.single_source,
        "quorum": panel.quorum.status if panel.quorum else None,
        "synthesizeable": panel.synthesizeable,
        "answer_returned": result.single_source_answer is not None,
    }


def judge_prompts(run: Run) -> list[tuple[str, str]]:
    return [(name, prompt) for name, prompt in run.calls if name in JUDGES]


def outside_markers(prompt: str) -> str:
    return BLOCK.sub("", prompt)


def block_count(prompt: str) -> int:
    return len(BLOCK.findall(prompt))
