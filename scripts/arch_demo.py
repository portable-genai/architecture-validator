"""Runnable demo of the C3 intake-gate flow (synthetic, fictional data).

Runs the real :class:`~architecture_validator.domain.services.ValidationService` under the
SDK-free ``local`` profile over the repo's built-in synthetic submissions — a
non-compliant onboarding bot that the gate BLOCKS, and a clean policy assistant that
CLEARS intake — printing a per-case summary and writing the cited audit-view JSON the
static renderer and the live demo server consume.

Run it::

    PYTHONPATH=src:tests python scripts/arch_demo.py [out.json]

No cloud, no API key, no LLM call to a managed service: the principle evaluation is a
deterministic pure function (replayable by an auditor) and the LLM port is the offline
default narrator. The verdict is a normal artifact — a FAIL is not an error.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("ARCH_VALIDATOR_PROFILE", "local")

from architecture_validator.api import deps  # noqa: E402  (env set first, then import)
from architecture_validator.config import build_container  # noqa: E402
from architecture_validator.domain.models import ProjectSubmission  # noqa: E402
from architecture_validator.domain.serialization import to_jsonable  # noqa: E402
from fixtures.sample_projects import (  # noqa: E402
    COMPLIANT_SUBMISSION,
    NON_COMPLIANT_SUBMISSION,
)

ACTOR = "demo.reviewer@bank.example"

# The two scripted cases, in presentation order: the BLOCKED case first (the headline —
# the gate doing its job), then the clean case that CLEARS intake.
CASES: list[tuple[str, ProjectSubmission]] = [
    ("blocked", NON_COMPLIANT_SUBMISSION),
    ("clean", COMPLIANT_SUBMISSION),
]


def _validate(submission: ProjectSubmission) -> dict:
    """Run the real ValidationService once (local profile) and project to JSON."""
    svc = deps.build_validation_service(build_container())
    report = svc.validate(submission, actor=ACTOR)
    return to_jsonable(report)


def _summarise(key: str, report: dict) -> None:
    sub = report["submission"]
    verdict = "PASS" if report["passed"] else "FAIL"
    findings = report["findings"]
    fails = [f for f in findings if f["status"] == "FAIL"]
    needs = [f for f in findings if f["status"] == "NEEDS_INFO"]
    injected = report["injected_requirements"]
    print(f"-- Case '{key}'  {sub['id']}: {sub['name']}")
    print(f"   verdict: {verdict}   (human review required: {report['requires_human_review']})")
    print(f"   region: {sub['declared_region']}   controls: {len(sub['declared_controls'])}")
    print(
        f"   findings: {len(findings)} checked · {len(fails)} FAIL · "
        f"{len(needs)} NEEDS_INFO · {len(findings) - len(fails) - len(needs)} other"
    )
    if fails:
        print("   failing principles: " + ", ".join(f["principle_id"] for f in fails))
    print(f"   injected requirements: {len(injected)}\n")


def main(out_path: str) -> None:
    payload: dict = {"actor": ACTOR, "cases": []}
    print("C3 Architecture & Requirements Validator — intake gate demo (profile=local)\n")
    for key, submission in CASES:
        report = _validate(submission)
        _summarise(key, report)
        payload["cases"].append({"key": key, "report": report})

    out = Path(out_path)
    if out.parent and not out.parent.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"Wrote audit-view JSON -> {out_path}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "arch_demo.json")
