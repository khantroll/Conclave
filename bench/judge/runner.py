"""Run the judge benchmark (P1-13): real judge models on scripted panels.

This spends money (or free-tier quota), so it never starts without an explicit approval of its
estimated cost::

    python -m bench.judge.runner --config conclave.json --judge mistral --dry-run
    python -m bench.judge.runner --config conclave.json --judge mistral --approve-cost 0.50
    python -m bench.judge.runner --summarize

Delegate answers are fixed texts, so only judge calls cost anything and every case is exactly
repeatable. Two arms run on identical inputs (the Arbiter alone; the Critic then the Arbiter,
the same model in both roles), three repeats each, on up to two judge models: 24 cases x
(3 + 6) = 216 calls per judge model.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from conclave.config import ConclaveConfig, load_config
from conclave.models import DeliberationRequest
from conclave.orchestrator import Orchestrator
from conclave.prompts import ARBITER_FORMAT_REQUEST
from conclave.providers.base import Provider, ProviderResponse
from conclave.providers.factory import build_providers
from conclave.providers.fake import FakeProvider
from conclave.sources import ProviderIdentity

from . import scoring

HERE = Path(__file__).parent
DEFAULT_OUT = HERE / "results.jsonl"
DEFAULT_REPEATS = 3
# Trials recorded before the Arbiter was told to state coverage have no ``prompt`` field. Results
# are kept apart by the Arbiter instruction they were produced under, so a changed prompt is
# measured afresh and never mixed with, or skipped as, an older run.
ORIGINAL_PROMPT = "original"
PROMPT_VERSION = hashlib.sha1(ARBITER_FORMAT_REQUEST.encode()).hexdigest()[:8]


def prompt_of(trial: dict) -> str:
    return trial.get("prompt", ORIGINAL_PROMPT)
MAX_JUDGES = 2
# Planning figures for the estimate only; the real numbers come from the ledger afterwards.
ASSUMED_OUTPUT_TOKENS = 900
CHARS_PER_TOKEN = 4


@dataclass(frozen=True)
class Arm:
    name: str
    use_critic: bool


ARM_LIST = (Arm("arbiter", False), Arm("critic", True))


def seed_for(case_id: str, repeat: int) -> str:
    """The same seed in both arms, so labels and order are identical and the arms are paired."""
    return hashlib.sha256(f"judge-bench|{case_id}|{repeat}".encode()).hexdigest()[:32]


def scripted_panel(case: dict) -> tuple[dict[str, Provider], dict[str, ProviderIdentity], list[str]]:
    """Fake delegates for a case, with distinct source identities unless a delegate is ``same_as``."""
    by_name = {d["name"]: d for d in case["delegates"]}
    providers: dict[str, Provider] = {}
    identities: dict[str, ProviderIdentity] = {}
    for delegate in case["delegates"]:
        name = delegate["name"]
        ident = by_name[delegate["same_as"]] if "same_as" in delegate else delegate
        identities[name] = ProviderIdentity(
            base_url=f"https://{ident['name']}.bench.example/v1", model=f"bench-{ident['name']}"
        )
        if delegate.get("fail"):
            providers[name] = FakeProvider(error=RuntimeError("scripted failure"))
            continue
        text = delegate["text"]
        if delegate.get("conclusion"):
            text += f"\n\nConclusion: {delegate['conclusion']}"
        if delegate.get("confidence"):
            text += f"\nConfidence: {delegate['confidence']}"
        providers[name] = FakeProvider(text, model=f"bench-{ident['name']}")
    return providers, identities, [d["name"] for d in case["delegates"]]


def build_request(
    case: dict, names: list[str], arm: Arm, judge: str, seed: str, critic: str | None = None
) -> DeliberationRequest:
    return DeliberationRequest(
        question=case["question"],
        delegates=names,
        arbiter=judge,
        critic=(critic or judge) if arm.use_critic else None,
        minimum_successes=2,
        seed=seed,
        timeout_seconds=30,
        critic_timeout_seconds=180,
        arbiter_timeout_seconds=180,
    )


class Stub(Provider):
    """A judge stand-in used for estimates and tests: records prompts, answers with fixed text."""

    def __init__(self, text: str, log: list[str]) -> None:
        self.text, self.log = text, log

    async def ask(self, prompt: str) -> ProviderResponse:
        self.log.append(prompt)
        return ProviderResponse(text=self.text)


def stub_answer() -> str:
    body = " ".join(["word"] * (ASSUMED_OUTPUT_TOKENS * CHARS_PER_TOKEN // 5))
    return f"## Common ground\n- {body} [A]\n\n## Disagreements\nNone.\n\n## Uncertainty\n- x [A]\n\n## Synthesis\nDone."


# ------------------------------------------------------------------------------ estimate


def estimate(cases: list[dict], judges: list[str], config: ConclaveConfig, repeats: int, critic: str | None = None) -> dict:
    """Calls, tokens and cost for the whole run, from the prompts it would send and the prices
    in the configuration. Unpriced judges make the cost unknown rather than zero."""
    prices = {p.name: p for p in config.providers}
    prompts_per_arm: dict[str, int] = {"arbiter": 0, "critic": 0}
    calls_per_pass = {"arbiter": 0, "critic": 0}
    for case in cases:
        for arm in ARM_LIST:
            log: list[str] = []
            providers, identities, names = scripted_panel(case)
            providers["judge"] = Stub(stub_answer(), log)
            request = build_request(case, names, arm, "judge", seed_for(case["id"], 0))
            asyncio.run(Orchestrator(providers, identities).deliberate(request))
            prompts_per_arm[arm.name] += sum(len(p) for p in log)
            calls_per_pass[arm.name] += len(log)
    per_judge = []
    for judge in judges:
        cfg = prices.get(judge)
        in_price = cfg.input_cost_per_million if cfg is not None else None
        out_price = cfg.output_cost_per_million if cfg is not None else None
        if critic is not None:
            # Both roles are priced at the dearer of the two models, input and output separately,
            # so the estimate is an upper bound. A Critic with no price makes the cost unknown.
            other = prices.get(critic)
            if other is None or None in (in_price, out_price, other.input_cost_per_million, other.output_cost_per_million):
                in_price = out_price = None
            else:
                in_price = max(in_price, other.input_cost_per_million)
                out_price = max(out_price, other.output_cost_per_million)
        calls = repeats * sum(calls_per_pass.values())
        tokens_in = repeats * sum(prompts_per_arm.values()) // CHARS_PER_TOKEN
        tokens_out = calls * ASSUMED_OUTPUT_TOKENS
        cost = (
            tokens_in / 1e6 * in_price + tokens_out / 1e6 * out_price
            if in_price is not None and out_price is not None
            else None
        )
        per_judge.append({"judge": pair_label(judge, critic), "calls": calls, "tokens_in": tokens_in, "tokens_out": tokens_out, "cost_usd": cost})
    known = all(j["cost_usd"] is not None for j in per_judge)
    return {
        "cases": len(cases),
        "repeats": repeats,
        "calls": sum(j["calls"] for j in per_judge),
        "per_judge": per_judge,
        "cost_usd": sum(j["cost_usd"] for j in per_judge) if known else None,
        "assumptions": f"{ASSUMED_OUTPUT_TOKENS} output tokens per call, {CHARS_PER_TOKEN} characters per token",
    }


def describe(plan: dict) -> str:
    lines = [f"{plan['cases']} cases x 2 arms x {plan['repeats']} repeats; {plan['calls']} judge calls in total."]
    for j in plan["per_judge"]:
        cost = f"${j['cost_usd']:.4f}" if j["cost_usd"] is not None else "unknown (no price configured)"
        lines.append(f"  {j['judge']}: {j['calls']} calls, ~{j['tokens_in']:,} input / ~{j['tokens_out']:,} output tokens, estimated cost {cost}")
    total = f"${plan['cost_usd']:.4f}" if plan["cost_usd"] is not None else "unknown"
    lines.append(f"Estimated total: {total}  ({plan['assumptions']})")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------- running


class JudgeUnavailable(RuntimeError):
    """The judge call itself failed (rate limit, outage). That says nothing about the judge's
    judgment, so it is never recorded as a failed trial; the run stops and can be resumed.

    ``cost`` is what the attempt already spent (a Critic that finished before its Arbiter failed
    was paid for), so it is recorded as an operational outcome rather than lost."""

    def __init__(self, message: str, cost: dict | None = None, stages: list | None = None) -> None:
        super().__init__(message)
        self.cost = cost
        self.stages = stages or []


def pair_label(judge_name: str, critic_name: str | None) -> str:
    """The name results are filed under: the Arbiter alone, or "arbiter+critic" when the Critic is
    a different model, so the two setups never share a baseline or a resume key."""
    return f"{judge_name}+{critic_name}" if critic_name else judge_name


async def run_trial(
    case: dict, arm: Arm, judge_name: str, judge: Provider, repeat: int,
    critic: tuple[str, Provider] | None = None,
) -> dict:
    providers, identities, names = scripted_panel(case)
    providers[judge_name] = judge
    critic_name = None
    if critic is not None:
        critic_name = critic[0]
        same_model = getattr(judge, "model", None) and getattr(judge, "model", None) == getattr(critic[1], "model", None)
        if critic_name == judge_name or same_model:
            raise ValueError("the Critic must be a different provider and model from the Arbiter; omit --critic to use one model for both")
        providers[critic_name] = critic[1]
    seed = seed_for(case["id"], repeat)
    rows: list = []
    orchestrator = Orchestrator(providers, identities, ledger_sink=rows.append)
    result = await orchestrator.deliberate(build_request(case, names, arm, judge_name, seed, critic_name))
    stages = [s for s in (result.critic if arm.use_critic else None, result.arbiter) if s is not None or False]
    if result.arbiter is None or any(s.status.value != "succeeded" for s in stages):
        failed = next((s for s in stages if s.status.value != "succeeded"), None)
        failed_provider = failed.name if failed is not None else judge_name  # the stage records its own provider
        raise JudgeUnavailable(
            f"{failed_provider}: {failed.error_kind or failed.status.value if failed else 'no answer'}",
            cost=result.cost.model_dump() if result.cost else None,
            stages=[(s.name, s.status.value) for s in (result.critic, result.arbiter) if s is not None],
        )
    arbiter_text = result.arbiter.raw_response
    checks = scoring.score_trial(case, arbiter_text, set(result.label_map))
    return {
        "case": case["id"],
        "class": case["class"],
        "arm": arm.name,
        "repeat": repeat,
        "judge": pair_label(judge_name, critic_name),
        # The model behind the provider name when this ran: a provider can be re-pointed at
        # another model, and results from the old one must not be reused as the new one's.
        "model": pair_model(judge, critic),
        "prompt": PROMPT_VERSION,
        "scorer": scoring.SCORER_VERSION,
        "seed": seed,
        "arbiter": arbiter_text,
        "critic": result.critic.raw_response if result.critic else None,
        "arbiter_status": result.arbiter.status.value if result.arbiter else None,
        "results": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in checks],
        "cost": result.cost.model_dump() if result.cost else None,
    }


def pair_model(judge: Provider, critic: tuple[str, Provider] | None) -> str:
    model = getattr(judge, "model", None) or "unknown"
    return f"{model}+{getattr(critic[1], 'model', None) or 'unknown'}" if critic else model


def operational_path(out: Path) -> Path:
    return out.with_name("operational.jsonl")


def record_operational(
    out: Path, judge: str, case: str, arm: str, repeat: int, reason: str,
    cost: dict | None = None, stages: list | None = None,
) -> None:
    """Note that a trial could not run (quota, outage). Never scored, never part of a decision."""
    entry = {"at": datetime.now(timezone.utc).isoformat(), "judge": judge, "case": case,
             "arm": arm, "repeat": repeat, "reason": reason}
    if cost is not None:
        entry["cost"] = cost  # spent on the attempt even though it produced no scored trial
    if stages:
        entry["stages"] = stages
    with operational_path(out).open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(entry) + "\n")


def load_results(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def run_all(
    cases: list[dict], judges: dict[str, Provider], repeats: int, out: Path, *, log=print,
    max_spend_usd: float | None = None, critic: tuple[str, Provider] | None = None,
) -> list[dict]:
    """Run every missing trial, appending each to ``out`` as it finishes (so an interrupted run
    resumes where it stopped and nothing already paid for is run again)."""
    done = {
        (t["case"], t["arm"], t["repeat"], t["judge"], t.get("model", "unknown"))
        for t in load_results(out)
        if prompt_of(t) == PROMPT_VERSION
    }
    new: list[dict] = []
    spent = 0.0
    for judge_name, judge in judges.items():
        label = pair_label(judge_name, critic[0] if critic else None)
        for case in cases:
            for repeat in range(repeats):
                for arm in ARM_LIST:
                    if (case["id"], arm.name, repeat, label, pair_model(judge, critic)) in done:
                        continue
                    try:
                        trial = await run_trial(case, arm, judge_name, judge, repeat, critic)
                    except JudgeUnavailable as exc:
                        # An operational outcome (quota, outage): kept apart from the scored trials.
                        record_operational(out, label, case["id"], arm.name, repeat, str(exc), exc.cost, exc.stages)
                        log(f"stopped, not recorded: {exc}. Run again later to resume.")
                        return new
                    with out.open("a", encoding="utf-8", newline="\n") as handle:
                        handle.write(json.dumps(trial, ensure_ascii=False) + "\n")
                    new.append(trial)
                    spent += ((trial.get("cost") or {}).get("estimated_total_usd")) or 0.0
                    if max_spend_usd is not None and spent >= max_spend_usd:
                        log(f"stopped: this run has spent about ${spent:.2f}, at the --max-spend limit of ${max_spend_usd:.2f}. Run again to resume.")
                        return new
                    log(f"{label} {case['id']} {arm.name} #{repeat}: {sum(r['passed'] for r in trial['results'])}/{len(trial['results'])}")
    return new


# --------------------------------------------------------------------------------- reporting


def report(trials: list[dict], repeats: int = DEFAULT_REPEATS, operational: list[dict] | None = None) -> str:
    """A plain-text summary: counts per arm and class, and the decision rule applied.

    The rule is applied only to a complete set of trials. A partial file says how much is missing
    and gives no decision, because a decision from part of the cases could be the opposite of the
    one the whole set gives.
    """
    out = []
    for judge, version in sorted({(t["judge"], prompt_of(t)) for t in trials}):
        mine = [t for t in trials if t["judge"] == judge and prompt_of(t) == version]
        summary = scoring.summarize(mine)
        absent = scoring.missing_trials(mine, repeats)
        out.append(f"## {judge}, Arbiter prompt `{version}`  ({len(mine)} trials)")
        for arm in scoring.ARMS:
            cell = summary["arm"][arm]
            out.append(f"- {arm}: {cell['passed']}/{cell['total']} checks passed ({scoring.rate(cell):.1f}%)")
        for name in scoring.CLASSES:
            a, c = summary["class"]["arbiter"].get(name), summary["class"]["critic"].get(name)
            if a and c:
                out.append(f"  - {name}: arbiter {a['passed']}/{a['total']}, critic {c['passed']}/{c['total']}")
        if absent:
            out.append(
                f"- decision: **incomplete** ({absent} of {scoring.expected_trials(repeats)} trials are missing; "
                "no decision is made from part of the set)"
            )
        else:
            decision = scoring.decide(summary)
            out.append(f"- decision: **{decision['decision']}** ({decision['reason']})")
        out.append("")
    if operational:
        out.append(f"## Operational outcomes (not scored): {len(operational)} trial(s) could not run")
        for entry in operational:
            out.append(f"- {entry['judge']} {entry['case']} {entry['arm']} #{entry['repeat']}: {entry['reason']}")
        out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bench.judge.runner", description=__doc__.split("\n")[0])
    parser.add_argument("--config", default="conclave.json")
    parser.add_argument("--judge", action="append", default=[], help="a configured provider to use as the judge (up to two)")
    parser.add_argument("--critic", default=None, help="a configured provider to use as the Critic, different from the single --judge (default: the judge plays both roles)")
    parser.add_argument("--repeats", type=int, default=DEFAULT_REPEATS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--dry-run", action="store_true", help="print the estimate and stop; no model is called")
    parser.add_argument("--approve-cost", type=float, default=None, help="the most you approve spending, in USD")
    parser.add_argument("--max-spend", type=float, default=None, help="stop the run once its ledger-estimated spend reaches this many USD (a hard stop, checked after every trial)")
    parser.add_argument("--approve-unpriced", action="store_true", help="also approve a run whose cost cannot be estimated (no price configured)")
    parser.add_argument("--summarize", action="store_true", help="summarize --out and stop")
    parser.add_argument("--rescore", action="store_true", help="score the saved answers in --out again with the current scorer (no model is called) and stop")
    args = parser.parse_args(argv)

    if args.rescore:
        rows = scoring.rescore(load_results(args.out))
        args.out.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8", newline="\n")
        print(f"rescored {len(rows)} trials with scorer v{scoring.SCORER_VERSION}")
        return 0
    if args.summarize:
        print(report(load_results(args.out), args.repeats, load_results(operational_path(args.out))))
        return 0
    if args.critic and len(args.judge) != 1:
        parser.error("--critic needs exactly one --judge (the Arbiter)")
    if args.critic is not None and not args.critic:
        parser.error("--critic needs a provider name")
    if args.critic and args.critic == args.judge[0]:
        parser.error("--critic must differ from the --judge; omit it to use one model for both roles")
    if not args.judge or len(args.judge) > MAX_JUDGES:
        parser.error(f"name one or two judge providers with --judge (up to {MAX_JUDGES})")
    if len(set(args.judge)) != len(args.judge):
        parser.error("name each judge once: a repeated --judge would be paid for twice and run once")
    config = load_config(args.config, load_env=True)
    known = {p.name for p in config.providers}
    missing = [j for j in [*args.judge, *([args.critic] if args.critic else [])] if j not in known]
    if missing:
        parser.error(f"not in {args.config}: {', '.join(missing)}")

    if args.critic:
        priced = {p.name: p for p in config.providers}
        if priced[args.critic].model == priced[args.judge[0]].model:
            parser.error(f"--critic {args.critic} and --judge {args.judge[0]} use the same model ({priced[args.critic].model}); pick a different model or omit --critic")
        for role in (args.judge[0], args.critic):
            if priced[role].input_cost_per_million is None or priced[role].output_cost_per_million is None:
                parser.error(f"{role} has no price configured; with --critic both roles need prices (0 for a free tier) so the estimate and --max-spend cover both")
    cases = scoring.load_cases()
    plan = estimate(cases, args.judge, config, args.repeats, args.critic)
    print(describe(plan))
    if args.dry_run:
        return 0
    unpriced = [j["judge"] for j in plan["per_judge"] if j["cost_usd"] is None]
    priced_total = sum(j["cost_usd"] for j in plan["per_judge"] if j["cost_usd"] is not None)
    if unpriced and not args.approve_unpriced:
        print(f"\nThe cost of {', '.join(unpriced)} cannot be estimated because no price is configured. Free tiers"
              " are fine: pass --approve-unpriced to run anyway, or set input_cost_per_million and"
              " output_cost_per_million (0 for a free tier) on the provider.", file=sys.stderr)
        return 2
    if len(unpriced) < len(plan["per_judge"]) and (args.approve_cost is None or args.approve_cost < priced_total):
        # Priced judges always need a covering approval, whether or not another judge is unpriced.
        print(f"\nNot run: the estimate for the priced judges is ${priced_total:.4f} and --approve-cost "
              f"{'was not given' if args.approve_cost is None else f'is only {args.approve_cost}'}.", file=sys.stderr)
        return 2
    wanted = {*args.judge, *([args.critic] if args.critic else [])}
    providers = build_providers([p for p in config.providers if p.name in wanted])
    critic = (args.critic, providers[args.critic]) if args.critic else None
    asyncio.run(run_all(cases, {name: providers[name] for name in args.judge}, args.repeats, args.out, max_spend_usd=args.max_spend, critic=critic))
    print()
    print(report(load_results(args.out), args.repeats, load_results(operational_path(args.out))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
