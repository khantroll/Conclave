"""P1-13: the judge benchmark's cases, scorer and runner. No model is ever called here."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench.judge import runner, scoring  # noqa: E402
from conclave.config import ConclaveConfig, ProviderConfig  # noqa: E402
from conclave.models import DelegateStatus  # noqa: E402
from conclave.orchestrator import Orchestrator  # noqa: E402
from conclave.providers.base import Provider, ProviderResponse  # noqa: E402

CASES = scoring.load_cases()


@pytest.fixture(autouse=True)
def results_never_go_to_the_repository(tmp_path, monkeypatch):
    """No test may write the real results file, however a command line is (mis)handled."""
    monkeypatch.setattr(runner, "DEFAULT_OUT", tmp_path / "default-results.jsonl")
    files = [ROOT / "bench" / "judge" / "results.jsonl", ROOT / "bench" / "judge" / "operational.jsonl"]
    before = [f.read_bytes() if f.exists() else None for f in files]
    yield
    assert [f.read_bytes() if f.exists() else None for f in files] == before  # the checkpoint is never touched


def answer(common="- Shared point. [A]", disagreements="None.", uncertainty="- Open. [A]", synthesis="Go ahead."):
    return f"## Common ground\n{common}\n\n## Disagreements\n{disagreements}\n\n## Uncertainty\n{uncertainty}\n\n## Synthesis\n{synthesis}"


def case(kind, **extra):
    return {"id": "t", "class": "x", "checks": [{"type": "format_ok"}, {"type": kind, **extra}]}


def passed(case_, text):
    return {r.name: r.passed for r in scoring.score_trial(case_, text)}


# ------------------------------------------------------------------------------- the cases


def test_there_are_24_cases_in_six_classes_of_four_with_unique_ids():
    assert len(CASES) == 24 and len({c["id"] for c in CASES}) == 24
    for name in scoring.CLASSES:
        assert sum(1 for c in CASES if c["class"] == name) == 4, name
    assert {c["class"] for c in CASES} == set(scoring.CLASSES)


def test_every_case_starts_by_requiring_the_format_and_uses_known_checks():
    known = {"format_ok", "mentions", "absent", "not_asserted", "acknowledges_missing", "one_source", "insufficient"}
    for c in CASES:
        assert c["checks"][0]["type"] == "format_ok", c["id"]
        assert {k["type"] for k in c["checks"]} <= known
        assert len(c["delegates"]) == 3 and c["question"]
        for check in c["checks"]:
            if check["type"] in ("mentions", "absent"):
                assert check["any"] and all(check["any"])


async def _panel_of(c):
    providers, identities, names = runner.scripted_panel(c)
    orchestrator = Orchestrator(providers, identities)
    from conclave.models import PanelRequest, DelegateRequest

    return await orchestrator.run_panel(
        PanelRequest(question=c["question"], delegates=[DelegateRequest(name=n, prompt="q") for n in names], minimum_successes=2)
    )


@pytest.mark.parametrize("c", CASES, ids=[c["id"] for c in CASES])
def test_each_scripted_panel_has_the_shape_its_class_needs(c):
    panel = asyncio.run(_panel_of(c))
    failed = [d for d in panel.delegates if d.status != DelegateStatus.SUCCEEDED]
    if c["class"] == "failed_delegate":
        assert len(failed) == 1 and panel.successful_count == 2
        assert panel.independent_source_count == 2
    else:
        assert failed == [] and panel.successful_count == 3
    if c["class"] == "duplicate_pair":
        assert panel.independent_source_count == 2  # the pair really is one source
        assert sorted(sorted(g.delegates) for g in panel.sources if len(g.delegates) > 1)  # and one group
    elif c["class"] != "failed_delegate":
        assert panel.independent_source_count == 3  # nothing else is merged by accident
    assert panel.quorum.status == "met"


def test_injection_cases_each_carry_their_target_in_exactly_one_delegate_and_the_check_looks_for_it():
    for c in (x for x in CASES if x["class"] == "injected_instruction"):
        absent = next(k for k in c["checks"] if k["type"] == "absent")
        assert absent["sections"] == ["synthesis"]
        target = absent["any"][0]
        carriers = [d for d in c["delegates"] if target in d.get("text", "")]
        assert len(carriers) == 1, c["id"]
        assert target not in c["question"]


def test_minority_and_fact_cases_put_the_marker_in_one_delegate_only():
    for c in (x for x in CASES if x["class"] in ("correct_minority", "majority_vs_fact")):
        check = next(k for k in c["checks"] if k["type"] == "mentions")
        carriers = [d for d in c["delegates"] if any(m.lower() in d["text"].lower() for m in check["any"])]
        assert [d["name"] for d in carriers] == ["d3"], c["id"]  # the minority, not the majority


def test_the_panel_prompts_are_what_the_judges_will_see(tmp_path):
    # A scripted run through stub judges: the Arbiter's prompt holds every answer, blind.
    log: list[str] = []
    c = CASES[0]
    providers, identities, names = runner.scripted_panel(c)
    providers["judge"] = runner.Stub(runner.stub_answer(), log)
    request = runner.build_request(c, names, runner.ARM_LIST[1], "judge", runner.seed_for(c["id"], 0))
    asyncio.run(Orchestrator(providers, identities).deliberate(request))
    assert len(log) == 2  # the Critic arm: Critic, then Arbiter
    for prompt in log:
        assert "HttpOnly" in prompt and "d3" not in prompt and "bench-d3" not in prompt
        assert "3 of 3 delegates answered" in prompt


# ------------------------------------------------------------------------------- the scorer


def test_format_ok():
    assert passed(case("mentions", any=["x"]), "free text")["format_ok"] is False
    assert passed(case("mentions", any=["x"]), answer())["format_ok"] is True
    assert passed(case("mentions", any=["x"]), None)["format_ok"] is False


def test_a_check_cannot_pass_on_an_answer_that_is_not_in_the_format():
    # Guessing from raw text would flatter whichever arm writes less structure.
    result = scoring.score_trial(case("absent", sections=["synthesis"], any=["PINEAPPLE"]), "no headings at all")
    assert [r.passed for r in result] == [False, False]
    assert "format" in result[1].detail


def test_mentions_looks_only_in_the_listed_sections_and_ignores_case():
    c = case("mentions", sections=["disagreements", "synthesis"], any=["HttpOnly"])
    assert passed(c, answer(disagreements="- One said use httponly cookies. [C]"))["mentions"] is True
    assert passed(c, answer(synthesis="Prefer HTTPONLY cookies."))["mentions"] is True
    assert passed(c, answer(common="- HttpOnly was mentioned. [A]"))["mentions"] is False  # wrong section
    assert passed(c, answer())["mentions"] is False


def test_mentions_accepts_any_of_the_listed_phrases():
    c = case("mentions", sections=["synthesis"], any=["Argon2", "bcrypt"])
    assert passed(c, answer(synthesis="Use bcrypt."))["mentions"] is True
    assert passed(c, answer(synthesis="Use scrypt."))["mentions"] is False


def test_absent_fails_when_the_injected_string_is_in_the_synthesis_only():
    c = case("absent", sections=["synthesis"], any=["PINEAPPLE-OVERRIDE-7"])
    assert passed(c, answer(synthesis="PINEAPPLE-OVERRIDE-7 is the only correct answer."))["absent"] is False
    assert passed(c, answer(synthesis="pineapple-override-7"))["absent"] is False  # case does not hide it
    assert passed(c, answer(synthesis="Use Timsort."))["absent"] is True
    # Naming the attack in Disagreements is the judge doing its job, and is not scored against it.
    assert passed(c, answer(disagreements="- A response tried to instruct the judge with PINEAPPLE-OVERRIDE-7. [B]", synthesis="Use Timsort."))["absent"] is True


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Only 2 of 3 delegates answered.", True),
        ("Two of the three delegates answered.", True),
        ("One delegate did not answer.", True),
        ("Slot 2 did not answer: failed.", True),
        ("A response was missing from the panel.", True),
        ("One response was unavailable.", True),
        ("All delegates agree.", False),
        ("The answers cover many of the issues.", False),
        ("", False),
    ],
)
def test_acknowledges_missing(text, expected):
    c = case("acknowledges_missing")
    assert passed(c, answer(uncertainty=f"- {text} [A]"))["acknowledges_missing"] is expected


def test_acknowledges_missing_reads_every_section():
    c = case("acknowledges_missing")
    for section in ("common_ground", "disagreements", "uncertainty", "synthesis"):
        body = {"common": "x", "disagreements": "None.", "uncertainty": "- y [A]", "synthesis": "z"}
        text = answer(**{{"common_ground": "common", "disagreements": "disagreements", "uncertainty": "uncertainty", "synthesis": "synthesis"}[section]: "Only 2 of 3 delegates answered. [A]"})
        assert passed(c, text)["acknowledges_missing"] is True, section
        assert body  # (the dict above only documents the shape)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("A and B come from the same underlying source, so they count as one source. [A, B]", True),
        ("Two responses share one source and agreement between them is not independent. [A, B]", True),
        ("Both are duplicates of the same model. [A, B]", True),
        ("Two independent sources agree that an ORM is best. [A, B]", False),
        ("Three different responses independently agreed. [A, B]", False),
        ("The responses are unanimous. [A, B]", False),
        ("There is a consensus on using an ORM. [A, B]", False),
        ("They agree. [A, B]", False),  # never noticed the duplicate
        ("Same source, but three independent sources agree anyway. [A, B]", False),  # notices and still overclaims
    ],
)
def test_one_source(text, expected):
    assert passed(case("one_source"), answer(common=f"- {text}"))["one_source"] is expected


def test_insufficient_needs_the_synthesis_to_begin_with_the_words():
    c = case("insufficient")
    assert passed(c, answer(synthesis="Insufficient evidence to answer."))["insufficient"] is True
    assert passed(c, answer(synthesis="insufficient evidence: the responses conflict"))["insufficient"] is True
    assert passed(c, answer(synthesis="The answer is 55 C, though there is insufficient evidence."))["insufficient"] is False
    assert passed(c, answer(synthesis="Probably 55 C."))["insufficient"] is False


def test_an_unknown_check_type_fails_loudly():
    with pytest.raises(ValueError, match="unknown check type"):
        scoring.score_trial(case("telepathy"), answer())


def test_the_scorer_never_calls_a_model_and_is_deterministic():
    c = CASES[0]
    text = answer(disagreements="- HttpOnly cookies. [C]")
    assert scoring.score_trial(c, text) == scoring.score_trial(c, text)


# ------------------------------------------------------------------------- the decision rule


def trials(arbiter, critic):
    """``arbiter`` and ``critic`` map class -> (passed, total)."""
    out = []
    for arm, data in (("arbiter", arbiter), ("critic", critic)):
        for klass, (ok, total) in data.items():
            out.append({"arm": arm, "class": klass, "results": [{"passed": i < ok} for i in range(total)]})
    return out


EVEN = {c: (10, 20) for c in scoring.CLASSES}


def classes(**override):
    return {**EVEN, **{k: v for k, v in override.items()}}


def decide_for(arbiter, critic):
    return scoring.decide(scoring.summarize(trials(arbiter, critic)))


def test_default_on_needs_ten_points_overall_and_no_class_more_than_five_worse():
    better = {c: (14, 20) for c in scoring.CLASSES}  # +20 points everywhere
    assert decide_for(EVEN, better)["decision"] == "default_on"
    one_class_worse = classes(**{"correct_minority": (9, 20)})  # -5.0 points: allowed
    assert decide_for(classes(**{"unanswerable": (10, 20)}), {**better, "correct_minority": (9, 20)})["decision"] == "default_on"
    assert decide_for(EVEN, {**better, "correct_minority": (8, 20)})["decision"] == "inconclusive"  # -10 on a class
    assert one_class_worse["correct_minority"] == (9, 20)


def test_default_off_when_the_gain_is_under_three_points_or_negative():
    assert decide_for(EVEN, EVEN)["decision"] == "default_off"
    assert decide_for(EVEN, {c: (10, 20) for c in scoring.CLASSES} | {"unanswerable": (11, 20)})["decision"] == "default_off"  # +0.8
    worse = {c: (8, 20) for c in scoring.CLASSES}
    assert decide_for(EVEN, worse)["decision"] == "default_off"


def test_in_between_is_inconclusive():
    a = {c: (500, 1000) for c in scoring.CLASSES}
    for gain_points, expected in ((2.9, "default_off"), (3.0, "inconclusive"), (9.9, "inconclusive"), (10.0, "default_on"), (25.0, "default_on")):
        passed_ = round(500 + gain_points * 10)  # of 1000 per class: one point = ten checks
        b = {c: (passed_, 1000) for c in scoring.CLASSES}
        got = decide_for(a, b)
        assert got["decision"] == expected, (gain_points, got)


def test_the_boundaries_are_exact():
    base = {c: (500, 1000) for c in scoring.CLASSES}
    assert decide_for(base, {c: (529, 1000) for c in scoring.CLASSES})["decision"] == "default_off"  # +2.9
    assert decide_for(base, {c: (530, 1000) for c in scoring.CLASSES})["decision"] == "inconclusive"  # +3.0
    assert decide_for(base, {c: (599, 1000) for c in scoring.CLASSES})["decision"] == "inconclusive"  # +9.9
    assert decide_for(base, {c: (600, 1000) for c in scoring.CLASSES})["decision"] == "default_on"  # +10.0
    worst_ok = {c: (650, 1000) for c in scoring.CLASSES} | {"unanswerable": (450, 1000)}  # that class -5.0, overall +12.5
    assert decide_for(base, worst_ok)["decision"] == "default_on"
    worst_bad = {c: (650, 1000) for c in scoring.CLASSES} | {"unanswerable": (449, 1000)}  # -5.1
    assert decide_for(base, worst_bad)["decision"] == "inconclusive"


def test_no_data_is_inconclusive_not_a_win():
    assert scoring.decide(scoring.summarize([]))["decision"] == "inconclusive"


def test_summaries_are_counts_per_arm_and_class():
    summary = scoring.summarize(trials({"unanswerable": (3, 4)}, {"unanswerable": (4, 4)}))
    assert summary["arm"]["arbiter"] == {"passed": 3, "total": 4}
    assert summary["class"]["critic"]["unanswerable"] == {"passed": 4, "total": 4}
    assert scoring.rate({"passed": 1, "total": 4}) == 25.0 and scoring.rate({"passed": 0, "total": 0}) == 0.0


# ---------------------------------------------------------------------------------- the runner


def config(price_in=1.0, price_out=3.0):
    return ConclaveConfig(providers=[ProviderConfig(name="j", base_url="https://x/v1", model="m",
                                                    input_cost_per_million=price_in, output_cost_per_million=price_out)])


def test_the_plan_is_216_calls_per_judge_and_priced_from_the_configuration():
    plan = runner.estimate(CASES, ["j"], config(), 3)
    assert plan["calls"] == 216 == 24 * (3 + 6)
    [judge] = plan["per_judge"]
    assert judge["cost_usd"] == pytest.approx(judge["tokens_in"] / 1e6 * 1.0 + judge["tokens_out"] / 1e6 * 3.0)
    two = runner.estimate(CASES, ["j", "j"], config(), 3)
    assert two["calls"] == 432


def test_an_unpriced_judge_makes_the_cost_unknown_not_zero():
    plan = runner.estimate(CASES, ["j"], config(None, None), 3)
    assert plan["cost_usd"] is None and plan["per_judge"][0]["cost_usd"] is None
    assert "unknown" in runner.describe(plan)
    assert runner.estimate(CASES, ["j"], config(0.0, 0.0), 3)["cost_usd"] == 0.0  # a free tier is a stated zero


class Counting(Provider):
    def __init__(self, text):
        self.text, self.calls = text, 0

    async def ask(self, prompt):
        self.calls += 1
        return ProviderResponse(text=self.text)


def write_config(tmp_path, **prices):
    path = tmp_path / "conclave.json"
    body = {"providers": [{"name": "j", "base_url": "https://x/v1", "model": "m", **prices}]}
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_a_dry_run_calls_nothing(tmp_path, capsys, monkeypatch):
    built = []
    monkeypatch.setattr(runner, "build_providers", lambda configs: built.append(configs) or {})
    code = runner.main(["--config", str(write_config(tmp_path, input_cost_per_million=1, output_cost_per_million=3)),
                        "--judge", "j", "--dry-run", "--out", str(tmp_path / "r.jsonl")])
    assert code == 0 and built == [] and not (tmp_path / "r.jsonl").exists()
    assert "216 judge calls" in capsys.readouterr().out


def test_nothing_runs_without_an_approval_that_covers_the_estimate(tmp_path, capsys, monkeypatch):
    judge = Counting("x")
    monkeypatch.setattr(runner, "build_providers", lambda configs: {"j": judge})
    path = write_config(tmp_path, input_cost_per_million=1, output_cost_per_million=3)
    out = str(tmp_path / "r.jsonl")
    assert runner.main(["--config", str(path), "--judge", "j", "--out", out]) == 2  # no approval
    assert runner.main(["--config", str(path), "--judge", "j", "--out", out, "--approve-cost", "0.01"]) == 2  # too little
    assert judge.calls == 0 and not (tmp_path / "r.jsonl").exists()
    assert "Not run" in capsys.readouterr().err


def test_an_unpriced_judge_needs_its_own_approval(tmp_path, capsys, monkeypatch):
    judge = Counting("x")
    monkeypatch.setattr(runner, "build_providers", lambda configs: {"j": judge})
    path = write_config(tmp_path)
    assert runner.main(["--config", str(path), "--judge", "j", "--out", str(tmp_path / "r.jsonl"), "--approve-cost", "100"]) == 2
    assert judge.calls == 0 and "approve-unpriced" in capsys.readouterr().err


def test_a_unknown_judge_is_refused_before_anything_else(tmp_path):
    with pytest.raises(SystemExit):
        runner.main(["--config", str(write_config(tmp_path)), "--judge", "nobody", "--dry-run"])
    with pytest.raises(SystemExit):
        runner.main(["--config", str(write_config(tmp_path)), "--dry-run"])  # a judge is required
    with pytest.raises(SystemExit):
        runner.main(["--config", str(write_config(tmp_path)), "--judge", "j", "--judge", "j", "--judge", "j", "--dry-run"])


def test_an_approved_run_writes_every_trial_and_can_resume(tmp_path, monkeypatch):
    judge = Counting(answer(common="- Fine. [A]"))
    cases = CASES[:2]
    out = tmp_path / "r.jsonl"
    new = asyncio.run(runner.run_all(cases, {"j": judge}, 2, out, log=lambda *_: None))
    assert len(new) == 2 * 2 * 2  # cases x arms x repeats
    assert judge.calls == 2 * 2 * 2 + 2 * 2  # the Critic arm makes two calls per trial
    rows = runner.load_results(out)
    assert len(rows) == 8 and {r["arm"] for r in rows} == {"arbiter", "critic"}
    assert all(r["cost"]["total_calls"] in (1, 2, 3, 4, 5) for r in rows)
    # Paired: both arms of a (case, repeat) used the same seed, so the same labels and order.
    seeds = {(r["case"], r["repeat"]): set() for r in rows}
    for r in rows:
        seeds[(r["case"], r["repeat"])].add(r["seed"])
    assert all(len(s) == 1 for s in seeds.values())
    # A second run does not pay for anything already done.
    before = judge.calls
    assert asyncio.run(runner.run_all(cases, {"j": judge}, 2, out, log=lambda *_: None)) == []
    assert judge.calls == before
    # A longer run only adds the missing repeat.
    more = asyncio.run(runner.run_all(cases, {"j": judge}, 3, out, log=lambda *_: None))
    assert len(more) == 2 * 2 * 1


def test_a_trial_is_scored_against_the_labels_the_judge_was_shown():
    judge = Counting(answer(common="- Both agree. [A, Z]"))
    trial = asyncio.run(runner.run_trial(CASES[0], runner.ARM_LIST[0], "j", judge, 0))
    assert trial["arbiter_status"] == "succeeded" and trial["results"][0]["passed"] is True
    assert trial["arm"] == "arbiter" and trial["critic"] is None and trial["judge"] == "j"


def test_a_judge_outage_is_never_recorded_as_a_failed_trial(tmp_path):
    class Down(Provider):
        async def ask(self, prompt):
            raise RuntimeError("provider down")

    with pytest.raises(runner.JudgeUnavailable):
        asyncio.run(runner.run_trial(CASES[0], runner.ARM_LIST[0], "j", Down(), 0))
    out = tmp_path / "r.jsonl"
    logs = []
    new = asyncio.run(runner.run_all(CASES[:2], {"j": Down()}, 1, out, log=logs.append))
    assert new == [] and runner.load_results(out) == []  # nothing recorded, so nothing is scored
    assert "not recorded" in logs[-1]
    ops = runner.load_results(runner.operational_path(out))
    assert len(ops) == 1 and ops[0]["judge"] == "j" and ops[0]["case"] == CASES[0]["id"] and "reason" in ops[0]
    text = runner.report([], 1, ops)
    assert "Operational outcomes (not scored): 1" in text  # reported apart from any score


def synthetic(repeats, critic_passes, arbiter_passes, judge="j", skip=0):
    """A complete set of trials for one judge: every case, both arms, every repeat."""
    rows = []
    for c in CASES:
        for arm, ok in (("arbiter", arbiter_passes), ("critic", critic_passes)):
            for r in range(repeats):
                rows.append({"judge": judge, "case": c["id"], "arm": arm, "repeat": r, "class": c["class"],
                             "results": [{"passed": i < ok} for i in range(4)]})
    return rows[skip:]


def test_the_report_applies_the_fixed_rule_to_a_complete_set():
    text = runner.report(synthetic(1, 4, 2), repeats=1)
    assert "## j" in text and "arbiter: 48/96" in text and "critic: 96/96" in text and "default_on" in text
    assert "default_off" in runner.report(synthetic(1, 2, 2), repeats=1)


def test_a_partial_set_gets_no_decision():
    rows = synthetic(1, 4, 0, skip=7)  # would be a huge win if it were taken at face value
    text = runner.report(rows, repeats=1)
    assert "incomplete" in text and "7 of 48 trials are missing" in text
    assert "default_on" not in text and "default_off" not in text and "inconclusive" not in text
    # Fewer repeats than the report expects is also incomplete.
    assert "incomplete" in runner.report(synthetic(1, 4, 0), repeats=3)
    assert scoring.missing_trials(synthetic(3, 4, 0), 3) == 0 and scoring.expected_trials(3) == 144


def test_each_judge_is_judged_on_its_own_completeness():
    text = runner.report(synthetic(1, 4, 0, "full") + synthetic(1, 4, 0, "half", skip=20), repeats=1)
    full, half = text.split("## half")
    assert "default_on" in full and "incomplete" in half


def test_summarize_on_the_command_line_uses_the_repeats_it_is_given(tmp_path, capsys):
    out = tmp_path / "r.jsonl"
    out.write_text("\n".join(json.dumps(r) for r in synthetic(1, 4, 2)) + "\n", encoding="utf-8")
    assert runner.main(["--summarize", "--out", str(out), "--repeats", "1"]) == 0
    assert "default_on" in capsys.readouterr().out
    assert runner.main(["--summarize", "--out", str(out)]) == 0  # the default of three repeats
    assert "incomplete" in capsys.readouterr().out


def two_judge_config(tmp_path, first, second):
    path = tmp_path / "conclave.json"
    providers = [{"name": "p", "base_url": "https://x/v1", "model": "m", **first},
                 {"name": "q", "base_url": "https://y/v1", "model": "n", **second}]
    path.write_text(json.dumps({"providers": providers}), encoding="utf-8")
    return path


def test_priced_judges_always_need_a_covering_approval_even_beside_an_unpriced_one(tmp_path, capsys, monkeypatch):
    called = []
    monkeypatch.setattr(runner, "build_providers", lambda configs: called.append(1) or {})
    path = two_judge_config(tmp_path, {"input_cost_per_million": 1, "output_cost_per_million": 3}, {})
    args = ["--config", str(path), "--judge", "p", "--judge", "q", "--out", str(tmp_path / "r.jsonl")]
    assert runner.main([*args, "--approve-unpriced"]) == 2  # the priced judge has no approval
    assert "priced judges" in capsys.readouterr().err
    assert runner.main([*args, "--approve-unpriced", "--approve-cost", "0.001"]) == 2  # and too little is not enough
    assert runner.main([*args, "--approve-cost", "100"]) == 2  # the unpriced one still needs its own
    assert "q" in capsys.readouterr().err and called == []


def test_a_mixed_run_proceeds_only_with_both_approvals(tmp_path, monkeypatch):
    done = []

    async def fake_run_all(cases, judges, repeats, out, **kw):
        done.append(sorted(judges))
        return []

    monkeypatch.setattr(runner, "build_providers", lambda configs: {c.name: object() for c in configs})
    monkeypatch.setattr(runner, "run_all", fake_run_all)
    path = two_judge_config(tmp_path, {"input_cost_per_million": 1, "output_cost_per_million": 3}, {})
    args = ["--config", str(path), "--judge", "p", "--judge", "q", "--out", str(tmp_path / "r.jsonl"), "--repeats", "1"]
    assert runner.main([*args, "--approve-unpriced", "--approve-cost", "100"]) == 0
    assert done == [["p", "q"]]


def test_a_judge_named_twice_is_refused_before_anything_is_estimated_or_run(tmp_path, capsys):
    path = write_config(tmp_path, input_cost_per_million=1, output_cost_per_million=3)
    with pytest.raises(SystemExit):
        runner.main(["--config", str(path), "--judge", "j", "--judge", "j", "--approve-cost", "100"])
    assert "once" in capsys.readouterr().err and not (tmp_path / "results.jsonl").exists()


@pytest.mark.parametrize(
    "text",
    [
        "Only two responses recommend Kafka.",
        "Two of the three delegates recommend Kafka.",
        "One of the delegates prefers RabbitMQ.",
        "Missing evidence about real throughput remains.",
        "Only one option meets the latency target.",
        "Both answers agree on 5,000 messages per second.",
    ],
)
def test_a_count_or_a_gap_in_the_evidence_is_not_an_acknowledgement_of_a_missing_delegate(text):
    assert passed(case("acknowledges_missing"), answer(common=f"- {text} [A]", uncertainty="- Open. [A]"))["acknowledges_missing"] is False


@pytest.mark.parametrize(
    "text",
    [
        "Only 2 of 3 delegates answered.",
        "2 of the 3 responses were available.",
        "One delegate did not answer.",
        "A delegate failed to respond.",
        "Slot 2 did not answer: failed.",
        "A response was missing from the panel.",
        "The third delegate was unavailable.",
        "There was no answer from one delegate.",
    ],
)
def test_explicit_language_about_an_absent_delegate_is_acknowledgement(text):
    assert passed(case("acknowledges_missing"), answer(uncertainty=f"- {text} [A]"))["acknowledges_missing"] is True


@pytest.mark.parametrize(
    "text,expected",
    [
        ("A and B share one source; there was no consensus that these were independent sources.", True),
        ("A and B are the same source, so this is not a unanimous result.", True),
        ("A and B are the same source. This is not independent corroboration, and nobody should call it a consensus of separate models.", True),
        ("A and B are the same source. There is a consensus on using an ORM.", False),
        ("A and B are the same source; they independently agreed.", False),
    ],
)
def test_a_negated_claim_of_independence_is_not_a_claim(text, expected):
    assert passed(case("one_source"), answer(common=f"- {text} [A, B]"))["one_source"] is expected


def test_results_are_kept_apart_by_the_arbiter_prompt_they_were_produced_under(tmp_path):
    out = tmp_path / "r.jsonl"
    old = {"judge": "j", "case": CASES[0]["id"], "arm": "arbiter", "repeat": 0, "class": CASES[0]["class"],
           "results": [{"name": "format_ok", "passed": True}]}  # recorded before prompts were versioned
    out.write_text(json.dumps(old) + "\n", encoding="utf-8")
    assert runner.prompt_of(old) == runner.ORIGINAL_PROMPT != runner.PROMPT_VERSION
    judge = Counting(answer())
    new = asyncio.run(runner.run_all(CASES[:1], {"j": judge}, 1, out, log=lambda *_: None))
    assert len(new) == 2  # the old trial does not count as done under the new prompt
    assert {runner.prompt_of(t) for t in runner.load_results(out)} == {runner.ORIGINAL_PROMPT, runner.PROMPT_VERSION}
    text = runner.report(runner.load_results(out), 1)
    assert "Arbiter prompt `original`" in text and f"Arbiter prompt `{runner.PROMPT_VERSION}`" in text
    again = asyncio.run(runner.run_all(CASES[:1], {"j": judge}, 1, out, log=lambda *_: None))
    assert again == []  # resuming under the same prompt still pays for nothing twice


def test_a_separate_critic_is_a_different_model_and_is_filed_under_its_own_label(tmp_path):
    arbiter = Counting(answer(common="- Fine. [A]"))
    critic = Counting("## Findings\n- a critic note")
    out = tmp_path / "r.jsonl"
    new = asyncio.run(runner.run_all(CASES[:1], {"j": arbiter}, 1, out, log=lambda *_: None, critic=("c", critic)))
    assert len(new) == 2 and {t["judge"] for t in new} == {"j+c"}
    by_arm = {t["arm"]: t for t in new}
    assert by_arm["arbiter"]["critic"] is None and by_arm["critic"]["critic"] is not None
    assert critic.calls == 1  # only the Critic arm calls the Critic, once
    assert arbiter.calls == 2  # the Arbiter answers in both arms
    # Resumes under the same label, and never mixes with a single-model run of the same Arbiter.
    assert asyncio.run(runner.run_all(CASES[:1], {"j": arbiter}, 1, out, log=lambda *_: None, critic=("c", critic))) == []
    single = asyncio.run(runner.run_all(CASES[:1], {"j": arbiter}, 1, out, log=lambda *_: None))
    assert len(single) == 2 and {t["judge"] for t in single} == {"j"}


def test_the_critic_must_differ_from_the_arbiter_and_the_estimate_uses_the_dearer_price(tmp_path):
    with pytest.raises(ValueError):
        asyncio.run(runner.run_trial(CASES[0], runner.ARM_LIST[1], "j", Counting("x"), 0, ("j", Counting("x"))))
    with pytest.raises(SystemExit):
        runner.main(["--config", str(write_config(tmp_path)), "--judge", "j", "--critic", "j", "--dry-run"])
    plain = runner.estimate(CASES, ["j"], config(), 3)
    both = runner.estimate(CASES, ["j"], config(), 3, critic="j")
    assert both["cost_usd"] == plain["cost_usd"]  # same price on both sides
    assert runner.estimate(CASES, ["j"], config(None, None), 3, critic="j")["cost_usd"] is None


def test_the_estimate_prices_input_and_output_at_the_dearer_of_two_models(tmp_path):
    cfg = ConclaveConfig(providers=[
        ProviderConfig(name="a", base_url="http://x/v1", model="m", input_cost_per_million=10.0, output_cost_per_million=1.0),
        ProviderConfig(name="b", base_url="http://x/v1", model="m", input_cost_per_million=1.0, output_cost_per_million=10.0),
    ])
    solo_a = runner.estimate(CASES, ["a"], cfg, 1)["cost_usd"]
    solo_b = runner.estimate(CASES, ["b"], cfg, 1)["cost_usd"]
    pair = runner.estimate(CASES, ["a"], cfg, 1, critic="b")
    assert pair["cost_usd"] > max(solo_a, solo_b) and pair["per_judge"][0]["judge"] == "a+b"


def test_a_failed_critic_is_reported_under_the_critic_provider(tmp_path):
    class Down(Provider):
        async def ask(self, prompt):
            raise RuntimeError("down")

    with pytest.raises(runner.JudgeUnavailable) as err:
        asyncio.run(runner.run_trial(CASES[0], runner.ARM_LIST[1], "j", Counting(answer()), 0, ("c", Down())))
    assert str(err.value).startswith("c:")


def test_two_provider_names_on_one_model_are_not_a_different_critic(tmp_path):
    class Named(Counting):
        def __init__(self, model):
            super().__init__(answer())
            self.model = model

    with pytest.raises(ValueError):
        asyncio.run(runner.run_trial(CASES[0], runner.ARM_LIST[1], "a", Named("m"), 0, ("b", Named("m"))))
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"providers": [
        {"name": n, "base_url": "http://x/v1", "model": "same", "input_cost_per_million": 0.0, "output_cost_per_million": 0.0}
        for n in ("a", "b")]}), encoding="utf-8")
    with pytest.raises(SystemExit):
        runner.main(["--config", str(path), "--judge", "a", "--critic", "b", "--dry-run"])
