"""P1-14: the documents describe the repository as it is. Every relative link resolves, and the
claims that go stale fastest are checked against the code."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MARKDOWN = sorted([ROOT / "README.md", *(ROOT / "docs").glob("*.md"), *(ROOT / "bench").rglob("*.md")])
LINK = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)\)")


def slug(heading: str) -> str:
    """GitHub's anchor for a heading."""
    text = re.sub(r"[`*_]", "", heading.strip().lower())
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    return {slug(m.group(1)) for m in re.finditer(r"^#{1,6}\s+(.+?)\s*$", path.read_text(encoding="utf-8"), re.M)}


def relative_links(path: Path):
    in_fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if in_fence:
            continue
        for match in LINK.finditer(line):
            target = match.group(1)
            if not re.match(r"[a-z][a-z0-9+.-]*:", target):  # not http:, mailto: and so on
                yield target


@pytest.mark.parametrize("path", MARKDOWN, ids=lambda p: str(p.relative_to(ROOT)))
def test_every_relative_link_resolves(path):
    for target in relative_links(path):
        file_part, _, fragment = target.partition("#")
        resolved = (path.parent / file_part).resolve() if file_part else path
        assert resolved.exists(), f"{path.relative_to(ROOT)}: {target} does not exist"
        if fragment and resolved.suffix == ".md":
            assert fragment in anchors(resolved), f"{path.relative_to(ROOT)}: no heading for #{fragment} in {resolved.name}"


def test_the_link_checker_would_notice_a_broken_link(tmp_path):
    doc = tmp_path / "a.md"
    doc.write_text("[ok](a.md) [bad](missing.md) [web](https://example.com) [anchor](#nope)\n", encoding="utf-8")
    assert list(relative_links(doc)) == ["a.md", "missing.md", "#nope"]
    assert not (tmp_path / "missing.md").exists() and "nope" not in anchors(doc)


def test_the_readme_names_the_python_versions_ci_runs():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8")
    assert "Requires Python 3.11+" in readme
    for version in re.findall(r"CI runs on (\d+\.\d+) and (\d+\.\d+)", readme)[0]:
        assert f'"{version}"' in workflow  # every version the README promises is in the CI matrix
    assert "python-version: ${{ matrix.python-version }}" in workflow


def test_the_status_does_not_describe_a_pre_alpha_that_no_longer_exists_or_overclaims():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    status = readme.split("## Status", 1)[1].split("## Limitations", 1)[0]
    assert "1.0.0" in status and "v1.0.0" in status
    assert "2026-11-15" in status and "V1-RELEASE-STATUS" in status
    assert "Pre-alpha" not in status
    for stale in ("real-provider MVP pipeline validated", "Manual testing has now produced"):
        assert stale not in readme


def test_the_readme_states_every_limitation_the_roadmap_requires():
    text = (ROOT / "README.md").read_text(encoding="utf-8").split("## Limitations", 1)[1].split("## Research", 1)[0].lower()
    for phrase in (
        "agreement is not evidence of correctness",
        "copies, not shared bias",
        "reveal its author",
        "no authority, not immunity",
        "never billed",
        "whether a panel is better than one model has not been measured",
    ):
        assert phrase in text, phrase


def test_the_critic_default_statement_matches_the_benchmark_results_file():
    import collections

    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    results = (ROOT / "bench" / "judge" / "RESULTS.md").read_text(encoding="utf-8")
    rows = [json.loads(line) for line in (ROOT / "bench" / "judge" / "results.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    per_judge = collections.Counter((r["judge"], r.get("prompt", "original")) for r in rows)
    complete = [k for k, n in per_judge.items() if n == 144]
    for (judge, prompt), n in per_judge.items():
        if n < 144:
            assert f"{n} of 144" in results and f"{n} of 144" in readme, (judge, prompt)  # incomplete sets say how incomplete
    assert "no default" in readme.lower()
    if complete:  # a decision exists for these judges; the README must name it and its limit
        assert "144 of 144" in results and "judge models" in results.lower()
        assert "default off" in results.lower() and "default off" in readme.lower()
    else:
        assert "no decision" in results.lower()


def test_no_document_claims_what_is_not_built():
    docs = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "README.md", ROOT / "docs" / "MVP.md", ROOT / "docs" / "ARCHITECTURE.md"))
    assert "extract intent, constraints, entities" not in docs.lower()
    assert "Extract intent, constraints, entities" not in docs


def test_the_numbers_the_readme_quotes_match_the_benchmark_files():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    data = json.loads((ROOT / "tests" / "benchmark" / "fixtures.json").read_text(encoding="utf-8"))
    assert f"scripts {len(data['fixtures'])} panels" in readme
    assert f"plus {len(data['http_fixtures'])} scripted HTTP failure sequences" in readme
    cases = json.loads((ROOT / "bench" / "judge" / "cases.json").read_text(encoding="utf-8"))["cases"]
    assert f"{len(cases)} cases" in readme
    assert "thirteen invariants" in readme


def test_the_development_notes_point_only_at_files_that_exist_on_main():
    notes = (ROOT / "docs" / "DEVELOPMENT_NEXT_STEPS.md").read_text(encoding="utf-8")
    for name in re.findall(r"`((?:docs|bench|tests)/[\w./-]+)`", notes):
        assert (ROOT / name).exists(), name
    for name in re.findall(r"`([A-Z_0-9-]+\.md)`", notes):
        assert any(ROOT.rglob(name)), name
