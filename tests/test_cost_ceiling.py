"""The per-run cost ceiling: off by default, fails closed, counts estimates only."""

from conclave.budget import CEILING_ERROR_KIND, CostGuard, worst_case_cost
from conclave.models import DelegateStatus, DeliberationRequest
from conclave.orchestrator import Orchestrator
from conclave.providers.fake import FakeProvider


class Priced(FakeProvider):
    """A fake with the pricing attributes a real provider has: bound = $1 per call."""

    input_cost_per_million = 0.0
    output_cost_per_million = 1000.0
    max_output_tokens = 1000
    transient_max_retries = 0

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.calls = 0

    async def ask(self, prompt):
        self.calls += 1
        return await super().ask(prompt)


def _request(ceiling, delegates=("a",), **kw):
    return DeliberationRequest(
        question="q",
        delegates=list(delegates),
        arbiter="arb",
        max_estimated_cost_usd=ceiling,
        single_source_mode="arbiter_single_source",
        **kw,
    )


def test_bound_is_attempts_times_prompt_and_output_worst_case():
    p = Priced()
    p.input_cost_per_million = 2.0
    p.transient_max_retries = 2
    p.system_prompt = "xx"
    # (10 + 2 bytes) * 2/1e6 + 1000 * 1000/1e6 = 0.000024 + 1.0, three attempts
    assert abs(worst_case_cost(p, "x" * 10) - 3 * (12 * 2 + 1000 * 1000) / 1e6) < 1e-12


def test_a_provider_with_a_missing_price_or_token_limit_has_no_bound():
    p = Priced()
    p.max_output_tokens = None
    assert worst_case_cost(p, "q") is None
    assert worst_case_cost(FakeProvider(), "q") is None


async def test_no_ceiling_means_no_guard_and_nothing_changes():
    result = await Orchestrator({"a": FakeProvider("x"), "arb": FakeProvider("y")}).deliberate(
        _request(None)
    )
    assert result.stopped_reason is None and result.arbiter.status == DelegateStatus.SUCCEEDED


async def test_an_unboundable_provider_is_refused_not_guessed_at():
    a = FakeProvider("x")
    result = await Orchestrator({"a": a, "arb": Priced("y")}).deliberate(_request(100.0))
    delegate = result.panel.delegates[0]
    assert delegate.status == DelegateStatus.FAILED and delegate.error_kind == CEILING_ERROR_KIND
    assert result.stopped_reason == "cost_ceiling"
    assert result.cost.total_calls == 0


async def test_delegates_are_admitted_in_order_until_the_ceiling_is_reached():
    ps = {n: Priced(n, estimated_cost_usd=0.1, delay_seconds=0.05) for n in ("a", "b", "c")}
    ps["arb"] = Priced("final", estimated_cost_usd=0.1)
    request = _request(2.5, delegates=("a", "b", "c"), minimum_successes=2)
    result = await Orchestrator(ps).deliberate(request)
    kinds = [r.error_kind for r in result.panel.delegates]
    assert kinds == [None, None, CEILING_ERROR_KIND]  # concurrent calls cannot overshoot
    assert ps["c"].calls == 0
    assert result.stopped_reason == "cost_ceiling"


async def test_a_judge_that_would_not_fit_is_refused_with_the_panel_kept():
    ps = {"a": Priced("answer", estimated_cost_usd=0.9), "arb": Priced("final")}
    result = await Orchestrator(ps).deliberate(_request(1.5))
    assert result.panel.delegates[0].status == DelegateStatus.SUCCEEDED
    assert result.arbiter.error_kind == CEILING_ERROR_KIND
    assert ps["arb"].calls == 0
    assert result.stopped_reason == "cost_ceiling"


async def test_a_ceiling_that_fits_runs_everything():
    ps = {"a": Priced("answer", estimated_cost_usd=0.1), "arb": Priced("final")}
    result = await Orchestrator(ps).deliberate(_request(5.0))
    assert result.arbiter.status == DelegateStatus.SUCCEEDED
    assert result.stopped_reason is None


def test_the_guard_reserves_in_flight_bounds():
    guard = CostGuard(1.5)
    assert guard.admit(1.0)
    assert not guard.admit(1.0)
    guard.release(1.0)
    assert guard.admit(1.0)
