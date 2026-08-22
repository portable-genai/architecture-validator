#!/usr/bin/env python3
"""Offline evaluation gate for C3 Architecture & Requirements Validator — A4 / P-08.

This is the **promotion gate**: CI runs it on every change and the build fails if the
validator's behaviour falls below the thresholds agreed for a policy-as-code intake gate
(see ``eval/rubrics/*.yaml``). This repo owns both the architecture validation and the
residency scan, so the single gate runs **two metric families in one pass**:

Architecture-validation family (``eval/datasets/golden_submissions.jsonl``,
``eval/rubrics/*.yaml``)::

    principle_accuracy >= 0.90   # did the validator flag the right principles PASS/FAIL?
    injection_recall   >= 0.80   # did it inject the missing NFRs for the unmet principles?
    citation_accuracy  >= 0.90   # is every finding / requirement cited to its principle?
    safety             >= 0.99   # no never-pass-a-failing-project leakage

Residency-scan family (
``eval/datasets/golden_scans.jsonl``, ``eval/rubrics/residency/*.yaml``). Reported with a
``residency_`` prefix so it sits beside the architecture metrics without name collision::

    residency_detection_recall  >= 0.90   # found the planted residency violations
    residency_precision         >= 0.90   # no false positives on clean resources
    residency_citation_accuracy >= 0.90   # violations cite P-01/P-03/P-10
    residency_safety            >= 0.99   # a clean estate never gates FAIL spuriously

The combined report ``.passed`` is the AND of all eight metrics, so the gate is red
if *either* family regresses.

Two evaluators, one gate
------------------------
* **Production evaluator** — the **Gen AI evaluation service** on the Gemini Enterprise
  Agent Platform, wired as ``EvaluationGatePort`` -> ``GenAiEvalAdapter``. Needs GCP
  credentials; select it with ``--use-gcp`` / ``--mode gate``.
* **Offline evaluator (default)** — a deterministic, dependency-light heuristic in this
  file. It runs the **real** ``ValidationService`` (architecture family) and the **real**
  ``ViolationDetector`` (residency family) against in-memory fakes, with **no GCP
  credentials and no Google Cloud SDK**, and computes the metrics by comparing the produced
  verdicts against each golden example's expectation.

Usage::

    python eval/run_eval.py                      # offline heuristic gate (CI, both families)
    python eval/run_eval.py --dataset path.jsonl # custom architecture golden set
    python eval/run_eval.py --use-gcp            # route through GenAiEvalAdapter

Exit code is ``0`` iff every metric in both families meets its threshold.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

# Domain models are pure-stdlib (no GCP / framework imports), so importing them here keeps
# this script runnable in the on-prem/test profile with no Google Cloud SDK installed.
# The --mode smoke|gate scaffold + aligned report rendering come from the shared
# agent-eval-kit commons; this script keeps only its own offline
# evaluators and gate runner.
from agent_eval_kit import eval_main

from architecture_validator.domain import principles_eval
from architecture_validator.domain.models import (
    SEVERITY_RANK,
    Citation,
    EvalMetricResult,
    EvalReport,
    LlmRequest,
    LlmResponse,
    Principle,
    PrincipleFinding,
    ProjectSubmission,
    TokenUsage,
)
from architecture_validator.domain.residency.detector import ViolationDetector
from architecture_validator.domain.residency.models import (
    ResidencyPolicy,
    ResourceConfig,
    ViolationKind,
)
from architecture_validator.domain.validation_service import ValidationService

# --------------------------------------------------------------------------- #
# Thresholds — the promotion bar (SPEC A4 / P-08). Mirror eval/rubrics/*.yaml.
# --------------------------------------------------------------------------- #
THRESHOLDS: dict[str, float] = {
    "principle_accuracy": 0.90,
    "injection_recall": 0.80,
    "citation_accuracy": 0.90,
    "safety": 0.99,
}

# Residency-scan family thresholds. Mirror eval/rubrics/residency/*.yaml.
RESIDENCY_THRESHOLDS: dict[str, float] = {
    "detection_recall": 0.90,
    "precision": 0.90,
    "citation_accuracy": 0.90,
    "safety": 0.99,
}

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = _REPO_ROOT / "eval" / "datasets" / "golden_submissions.jsonl"
RESIDENCY_DATASET = _REPO_ROOT / "eval" / "datasets" / "golden_scans.jsonl"

_KIND_BY_VALUE = {k.value: k for k in ViolationKind}


# =========================================================================== #
# Architecture-validation family
# =========================================================================== #
@dataclass(frozen=True, slots=True)
class GoldenExample:
    id: str
    submission: ProjectSubmission
    expected_failed_principles: frozenset[str]
    expected_injected_principles: frozenset[str]


def _submission_from(obj: dict) -> ProjectSubmission:
    sub = obj.get("submission", obj)
    return ProjectSubmission(
        id=str(sub.get("id", "")),
        name=str(sub.get("name", "")),
        description=str(sub.get("description", "")),
        requirements=str(sub.get("requirements", "")),
        declared_region=sub.get("declared_region"),
        declared_controls=tuple(sub.get("declared_controls", []) or ()),
        uses_pii=bool(sub.get("uses_pii", False)),
        uses_rag=bool(sub.get("uses_rag", False)),
        uses_fine_tuning=bool(sub.get("uses_fine_tuning", False)),
        has_exit_plan=bool(sub.get("has_exit_plan", False)),
        attributes={str(k): str(v) for k, v in (sub.get("attributes") or {}).items()},
    )


def load_golden(path: Path) -> list[GoldenExample]:
    """Parse the JSONL golden set (stdlib ``json`` — no YAML needed for the data)."""
    examples: list[GoldenExample] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise SystemExit(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        submission = _submission_from(obj)
        examples.append(
            GoldenExample(
                id=str(obj.get("id", submission.id or f"example-{lineno}")),
                submission=submission,
                expected_failed_principles=frozenset(
                    obj.get("expected_failed_principles", []) or ()
                ),
                expected_injected_principles=frozenset(
                    obj.get(
                        "expected_injected_principles", obj.get("expected_failed_principles", [])
                    )
                    or ()
                ),
            )
        )
    if not examples:
        raise SystemExit(f"{path}: golden dataset is empty")
    return examples


def load_thresholds_from_rubrics() -> dict[str, float]:
    """Read architecture thresholds from ``eval/rubrics/*.yaml`` when PyYAML is available.

    Uses a non-recursive glob so the residency rubrics under ``eval/rubrics/residency/``
    are not picked up here (they are loaded by :func:`load_residency_thresholds_from_rubrics`).
    """
    thresholds = dict(THRESHOLDS)
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return thresholds
    rubric_dir = _REPO_ROOT / "eval" / "rubrics"
    for rubric_path in sorted(rubric_dir.glob("*.yaml")):
        doc = yaml.safe_load(rubric_path.read_text(encoding="utf-8")) or {}
        metric = doc.get("metric")
        if isinstance(metric, str) and "threshold" in doc:
            thresholds[metric] = float(doc["threshold"])
    return thresholds


# --------------------------------------------------------------------------- #
# Deterministic fakes (inlined: importing tests.conftest is disallowed for the gate).
# --------------------------------------------------------------------------- #
class FakePolicyEngine:
    def evaluate(
        self, submission: ProjectSubmission, principles: list[Principle]
    ) -> list[PrincipleFinding]:
        return principles_eval.evaluate_all(submission)


class FakeKnowledgeBase:
    def retrieve(self, query: str, top_k: int = 8) -> list[Citation]:
        return []


class FakeLLM:
    """Deterministic injection LLM: emits one item per unmet principle in the prompt."""

    model = "gemini-3.5-flash"

    def generate(self, request: LlmRequest) -> LlmResponse:
        import re

        user = request.messages[-1].content if request.messages else ""
        items = []
        for principle_id, _status, severity in re.findall(
            r"^- (P-\d{2}) \[(FAIL|NEEDS_INFO),\s*([a-z]+)\]", user, re.MULTILINE
        ):
            items.append(
                {
                    "principle_id": principle_id,
                    "requirement_text": f"Add the control mandated by {principle_id}.",
                    "rationale": f"{principle_id} is unmet.",
                    "severity": severity,
                    "used_source_ids": [principle_id],
                }
            )
        return LlmResponse(
            text=json.dumps({"items": items}),
            usage=TokenUsage(input_tokens=64, output_tokens=32),
            model=self.model,
        )

    def classify(self, text: str, labels: list[str]) -> str:
        return labels[0] if labels else ""


class FakeTracer:
    @contextmanager
    def span(self, name: str, **attributes: str) -> Iterator[None]:
        yield

    def record_token_usage(self, usage: TokenUsage, model: str) -> None:
        return None


class FakeAudit:
    def __init__(self) -> None:
        self.events: list[object] = []

    def record(self, event: object) -> None:
        self.events.append(event)


def _make_service() -> ValidationService | None:
    """Construct the real ValidationService with deterministic fakes, or ``None``."""
    try:
        return ValidationService(
            policy_engine=FakePolicyEngine(),
            knowledge_base=FakeKnowledgeBase(),
            llm=FakeLLM(),
            tracer=FakeTracer(),
            audit=FakeAudit(),
        )
    except Exception:  # pragma: no cover - defensive
        return None


# --------------------------------------------------------------------------- #
# Heuristic scorers (architecture family)
# --------------------------------------------------------------------------- #
def score_principle_accuracy(report, example: GoldenExample) -> float:
    """Fraction of the 12 principles whose PASS/FAIL matches the golden expectation."""
    failed = {f.principle_id for f in report.findings if f.status.value == "FAIL"}
    expected = set(example.expected_failed_principles)
    all_ids = {f.principle_id for f in report.findings}
    if not all_ids:
        return 0.0
    correct = sum(1 for pid in all_ids if (pid in failed) == (pid in expected))
    return round(correct / len(all_ids), 4)


def score_injection_recall(report, example: GoldenExample) -> float:
    """Fraction of the expected-to-be-injected principles that were injected."""
    expected = set(example.expected_injected_principles)
    if not expected:
        return 1.0
    injected = {r.principle_id for r in report.injected_requirements}
    return round(len(expected & injected) / len(expected), 4)


def score_citation_accuracy(report) -> float:
    """Every finding and injected requirement must carry at least one citation."""
    items = list(report.findings) + list(report.injected_requirements)
    if not items:
        return 1.0
    cited = sum(1 for it in items if it.citations)
    return round(cited / len(items), 4)


def score_safety(report, example: GoldenExample) -> float:
    """A project the golden set expects to FAIL must never be reported as passed."""
    if example.expected_failed_principles and report.passed:
        return 0.0
    return 1.0


def score_residency_detection_recall(expected_kinds: set, found: set) -> float:
    """Of the expected violation kinds, the fraction the detector actually found."""
    if not expected_kinds:
        return 1.0  # nothing to find
    return len(expected_kinds & found) / len(expected_kinds)


def score_residency_precision(expected_kinds: set, found: set) -> float:
    """No kinds beyond the expected ones. On a clean estate, any finding is a false positive."""
    if not expected_kinds:
        return 0.0 if found else 1.0
    if not found:
        return 1.0
    return len(expected_kinds & found) / len(found)


def score_residency_citation_accuracy(violations) -> float:  # type: ignore[no-untyped-def]
    """Every emitted violation must cite one of the residency principles."""
    if not violations:
        return 1.0
    cited = all({c.source_id for c in v.citations} & {"P-01", "P-03", "P-10"} for v in violations)
    return 1.0 if cited else 0.0


def score_residency_safety(verdict_pass: bool, expected_pass: bool) -> float:
    """No spurious FAIL on a clean estate, and no missed FAIL on a violating one."""
    return 1.0 if verdict_pass == expected_pass else 0.0


@dataclass
class _PerMetric:
    scores: list[float] = field(default_factory=list)

    @property
    def mean(self) -> float:
        return sum(self.scores) / len(self.scores) if self.scores else 0.0


def run_arch_offline(dataset: Path, thresholds: dict[str, float]) -> EvalReport:
    """Offline architecture-validation family: real ValidationService over golden submissions."""
    examples = load_golden(dataset)
    service = _make_service()
    if service is None:  # pragma: no cover - defensive
        raise SystemExit("could not construct ValidationService for the offline gate")

    agg: dict[str, _PerMetric] = {m: _PerMetric() for m in THRESHOLDS}
    print(f"Running offline eval gate over {len(examples)} golden submissions (architecture).\n")
    for example in examples:
        report = service.validate(example.submission, actor="eval-bot")
        agg["principle_accuracy"].scores.append(score_principle_accuracy(report, example))
        agg["injection_recall"].scores.append(score_injection_recall(report, example))
        agg["citation_accuracy"].scores.append(score_citation_accuracy(report))
        agg["safety"].scores.append(score_safety(report, example))

    results = tuple(
        EvalMetricResult(
            metric=metric,
            score=round(agg[metric].mean, 4),
            threshold=thresholds.get(metric, THRESHOLDS[metric]),
            passed=round(agg[metric].mean, 4) >= thresholds.get(metric, THRESHOLDS[metric]),
        )
        for metric in ("principle_accuracy", "injection_recall", "citation_accuracy", "safety")
    )
    return EvalReport(dataset=str(dataset), results=results, n_examples=len(examples))


# =========================================================================== #
# Residency-scan family
# =========================================================================== #
@dataclass(frozen=True, slots=True)
class ResidencyGoldenExample:
    id: str
    resource: ResourceConfig
    expected_kinds: frozenset[ViolationKind]
    expected_pass: bool


def load_residency_golden(path: Path) -> list[ResidencyGoldenExample]:
    """Parse the residency JSONL golden set (stdlib ``json``)."""
    examples: list[ResidencyGoldenExample] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise SystemExit(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        res = obj["resource"]
        examples.append(
            ResidencyGoldenExample(
                id=str(obj.get("id", f"example-{lineno}")),
                resource=ResourceConfig(
                    address=str(res["address"]),
                    type=str(res["type"]),
                    region=res.get("region"),
                    attributes={k: str(v) for k, v in (res.get("attributes") or {}).items()},
                    source_ref=str(res.get("source_ref", "")),
                ),
                expected_kinds=frozenset(
                    _KIND_BY_VALUE[k]
                    for k in obj.get("expected_violation_kinds", [])
                    if k in (_KIND_BY_VALUE)
                ),
                expected_pass=bool(obj.get("expected_pass", True)),
            )
        )
    if not examples:
        raise SystemExit(f"{path}: golden dataset is empty")
    return examples


def load_residency_thresholds_from_rubrics() -> dict[str, float]:
    """Read residency thresholds from ``eval/rubrics/residency/*.yaml`` when PyYAML is available."""
    thresholds = dict(RESIDENCY_THRESHOLDS)
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return thresholds
    rubric_dir = _REPO_ROOT / "eval" / "rubrics" / "residency"
    for name in ("detection.yaml", "citation_accuracy.yaml"):
        rubric_path = rubric_dir / name
        if not rubric_path.exists():
            continue
        doc = yaml.safe_load(rubric_path.read_text(encoding="utf-8")) or {}
        metric = doc.get("metric")
        if isinstance(metric, str) and "threshold" in doc:
            thresholds[metric] = float(doc["threshold"])
        for companion, spec in (doc.get("companion_metrics") or {}).items():
            if isinstance(spec, dict) and "threshold" in spec:
                thresholds[str(companion)] = float(spec["threshold"])
    return thresholds


def _residency_gates(violation, policy: ResidencyPolicy) -> bool:
    return SEVERITY_RANK[violation.severity] >= SEVERITY_RANK[policy.gate_severity]


def run_residency_offline(dataset: Path, thresholds: dict[str, float]) -> EvalReport:
    """Offline residency-scan family: real ViolationDetector over golden resource snapshots."""
    examples = load_residency_golden(dataset)
    detector = ViolationDetector(ResidencyPolicy())

    agg: dict[str, _PerMetric] = {m: _PerMetric() for m in RESIDENCY_THRESHOLDS}
    print(
        f"Running offline eval gate over {len(examples)} golden examples "
        f"(residency; evaluator=ViolationDetector).\n"
    )
    for ex in examples:
        violations = detector.detect([ex.resource])
        found = {v.kind for v in violations}

        agg["detection_recall"].scores.append(
            score_residency_detection_recall(ex.expected_kinds, found)
        )
        agg["precision"].scores.append(score_residency_precision(ex.expected_kinds, found))
        agg["citation_accuracy"].scores.append(score_residency_citation_accuracy(violations))
        verdict_pass = not any(v for v in violations if _residency_gates(v, detector.policy))
        agg["safety"].scores.append(score_residency_safety(verdict_pass, ex.expected_pass))

    results = tuple(
        EvalMetricResult(
            metric=metric,
            score=round(agg[metric].mean, 4),
            threshold=thresholds.get(metric, RESIDENCY_THRESHOLDS[metric]),
            passed=round(agg[metric].mean, 4)
            >= thresholds.get(metric, RESIDENCY_THRESHOLDS[metric]),
        )
        for metric in ("detection_recall", "precision", "citation_accuracy", "safety")
    )
    return EvalReport(dataset=str(dataset), results=results, n_examples=len(examples))


# =========================================================================== #
# Combined smoke runner — both families in one pass, one report
# =========================================================================== #
def run_offline(dataset: Path) -> EvalReport:
    """Run BOTH metric families offline and merge into one EvalReport.

    ``dataset`` is the architecture golden set (the ``--dataset`` CLI override applies to
    it, preserving the pre-merge behaviour). The residency family always runs over its own
    ``golden_scans.jsonl``. The residency metrics are re-labelled with a ``residency_``
    prefix so both ``citation_accuracy`` and ``safety`` metrics coexist unambiguously; the
    combined report ``.passed`` is the AND of all eight metrics.
    """
    arch_report = run_arch_offline(dataset, load_thresholds_from_rubrics())

    if not RESIDENCY_DATASET.exists():  # pragma: no cover - defensive
        raise SystemExit(f"residency golden dataset not found: {RESIDENCY_DATASET}")
    residency_report = run_residency_offline(
        RESIDENCY_DATASET, load_residency_thresholds_from_rubrics()
    )

    residency_results = tuple(
        EvalMetricResult(
            metric=f"residency_{r.metric}",
            score=r.score,
            threshold=r.threshold,
            passed=r.passed,
        )
        for r in residency_report.results
    )
    combined_results = tuple(arch_report.results) + residency_results
    combined_dataset = f"{arch_report.dataset} + {residency_report.dataset}"
    return EvalReport(
        dataset=combined_dataset,
        results=combined_results,
        n_examples=arch_report.n_examples + residency_report.n_examples,
    )


def run_gate(dataset: Path) -> tuple[EvalReport, bool]:
    """Promotion verdict via EvaluationGatePort (platform = Hrz4, gcp = Gen AI evals).

    Fails closed on the reconciled evaluate + gate result. Refuses to run outside the
    platform/gcp profiles so the offline smoke result is never relabelled a promotion pass.
    """
    from architecture_validator.config import Settings, build_container

    settings = Settings.load()
    if settings.profile not in ("platform", "gcp"):
        raise SystemExit(
            "--mode gate is the promotion authority and requires "
            "ARCH_VALIDATOR_PROFILE=platform or gcp "
            f"(got {settings.profile!r}); run --mode smoke for the offline pre-merge check."
        )
    container = build_container(settings)
    gate = container.evaluation
    report = gate.evaluate(str(dataset))
    if not isinstance(report, EvalReport):  # pragma: no cover - defensive
        raise SystemExit("EvaluationGatePort.evaluate did not return an EvalReport")
    gate_passed = bool(gate.gate(str(dataset)))
    return report, gate_passed


def main(argv: list[str] | None = None) -> int:
    """Dispatch --mode via the shared eval_main scaffold (fail-closed exit codes).

    ``--use-gcp`` (the pre-split flag for the production evaluator) is kept as an alias
    for ``--mode gate``.
    """
    args = sys.argv[1:] if argv is None else list(argv)
    if "--use-gcp" in args:
        args = [a for a in args if a != "--use-gcp"] + ["--mode", "gate"]
    return eval_main(
        smoke=run_offline,
        gate=run_gate,
        default_dataset=DEFAULT_DATASET,
        description="Offline / platform evaluation gate for validation + residency (A4 / P-08).",
        smoke_label="offline heuristic (no GCP creds) — architecture + residency",
        gate_label="promotion gate (EvaluationGatePort: Hrz4 / Gen AI evals)",
        argv=args,
    )


if __name__ == "__main__":
    raise SystemExit(main())
