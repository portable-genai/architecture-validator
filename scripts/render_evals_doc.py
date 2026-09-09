#!/usr/bin/env python3
"""Regenerate the derived half of ``docs/evals.md`` from the rubrics, golden sets and floors.

A page that lists metrics and thresholds by hand goes stale the first time a bar moves, and
nothing notices. This repository had exactly that: the bars lived in a Python dict AND in the
rubric files, and the two could disagree without anything failing. The dicts are gone; this
makes the prose derived too.

    make evals-doc          # rewrite the generated sections
    make evals-doc-check    # non-zero when the page and the artifacts disagree (runs in check)

Only the sections named in :data:`BLOCKS` are generated. Everything else on the page is
hand-written prose addressed to a reviewer, and this script does not touch it: the point is a
document a person wrote, whose FACTS cannot drift from the artifacts they describe.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml
from agent_eval_kit import load_jsonl, load_rubrics, render_main, required_positives
from agent_eval_kit.rubrics import Rubric

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "eval"))
sys.path.insert(0, str(_REPO_ROOT / "src"))

DOC = _REPO_ROOT / "docs" / "evals.md"
RUBRICS = _REPO_ROOT / "eval" / "rubrics"
GOLDEN = _REPO_ROOT / "eval" / "datasets" / "golden_submissions.jsonl"
SCANS = _REPO_ROOT / "eval" / "datasets" / "golden_scans.jsonl"

#: The headings this script owns. Each runs from its heading to the next `\n## `.
BLOCKS = (
    "## What is measured, and against what bar",
    "## What is exercised",
)


def _denominator_kind(rubric: Rubric) -> str:
    """What a rubric says its bar is measured over. Read, never guessed from the number.

    0.99 is both the bar a leak metric carries (one leak anywhere fails it) and a perfectly
    ordinary rate. Guessing from the number would print "needs 100 cases" beside a metric a
    corpus of one already gates correctly, which is a confident wrong answer.
    """
    document = yaml.safe_load(Path(rubric.source).read_text(encoding="utf-8")) or {}
    declared = document.get("denominator") or {}
    node = declared.get(rubric.metric, declared) if isinstance(declared, dict) else {}
    if not isinstance(node, dict):
        node = {}
    return str(node.get("kind", "rate"))


def _metrics_block() -> list[str]:
    rubrics = load_rubrics(RUBRICS)
    lines = [
        BLOCKS[0],
        "",
        "Two families, scored in one run and reported in one table. They share metric NAMES and",
        "do not share bars, which is why the residency rubrics live in their own directory: a",
        "design review and a data-residency scan are different questions with the same words.",
        "",
        "| Family | Metric | Bar | Denominator | What it measures |",
        "|---|---|---|---|---|",
    ]
    for group, label in (("", "architecture"), ("residency", "residency")):
        for rubric in rubrics.group(group):
            if _denominator_kind(rubric) == "all-or-nothing":
                needs = "all or nothing"
            else:
                needs = f"a rate; needs {required_positives(rubric.threshold)} positives"
            lines.append(
                f"| {label} | `{rubric.metric}` | {rubric.threshold:g} | {needs} | "
                f"{rubric.description} |"
            )
    lines.append("")
    return lines


def _exercised_block() -> list[str]:
    submissions = load_jsonl(GOLDEN)
    scans = load_jsonl(SCANS)
    kinds = sum(len(row["expected_violation_kinds"]) for row in scans)
    multi = sum(1 for row in scans if len(row["expected_violation_kinds"]) > 1)
    clean = sum(1 for row in scans if not row["expected_violation_kinds"])
    return [
        BLOCKS[1],
        "",
        f"- **{len(submissions)} golden submissions** in",
        "  `eval/datasets/golden_submissions.jsonl`, with the principles a reviewer expected to",
        "  fail and the requirements they expected to be injected.",
        f"- **{len(scans)} golden residency scans** in `eval/datasets/golden_scans.jsonl`,",
        f"  carrying **{kinds} expected violation kinds**. That count is what",
        "  `residency_detection_recall` is measured over, not the scan count.",
        f"- **{multi} of the scans carry more than one violation at once.** Every violating scan",
        "  used to carry exactly one, so nothing measured whether the scanner reports the second",
        "  problem once it has reported the first.",
        f"- **{clean} clean scans**, which is what a false positive can fire on.",
        "",
    ]


def render() -> str:
    """The page, with the generated blocks replaced and the hand-written prose untouched."""
    text = DOC.read_text(encoding="utf-8")
    missing = [heading for heading in BLOCKS if heading not in text]
    if missing:
        raise SystemExit(
            f"{DOC}: missing generated section(s) {missing}. This script replaces named "
            "headings; it does not invent them, because a page it could create from nothing "
            "would silently replace one a person wrote."
        )
    generated = {
        BLOCKS[0]: _metrics_block(),
        BLOCKS[1]: _exercised_block(),
    }
    out: list[str] = []
    skipping = False
    for line in text.splitlines():
        if line in generated:
            out.extend(generated[line])
            skipping = True
            continue
        if skipping:
            if line.startswith("## "):
                skipping = False
            else:
                continue
        out.append(line)
    return "\n".join(out).rstrip("\n") + "\n"


if __name__ == "__main__":
    raise SystemExit(
        render_main(
            output=DOC,
            render=render,
            description="Regenerate docs/evals.md from the rubrics, golden sets and floors.",
            argv=sys.argv[1:],
        )
    )
