"""Prove every eval metric can go RED: a degraded input must score below its threshold.

A metric that cannot fail proves nothing. Both metric families in ``eval/run_eval.py`` are
covered: the architecture family scores a real ``ValidationService`` report, and the residency
family scores a real ``ViolationDetector`` run. Each scorer is imported rather than
re-implemented, so a scorer that silently became a constant 1.0 breaks this build.

The principle_accuracy red case inverts EVERY expectation rather than merely clearing them:
clearing one principle's expectation still scores 0.9167 against a 0.90 bar, which would have
made this proof pass while the metric stayed green.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from agent_eval_kit import assert_can_go_red
from eval.run_eval import (
    DEFAULT_DATASET,
    RESIDENCY_DATASET,
    RESIDENCY_THRESHOLDS,
    THRESHOLDS,
    _make_service,
    load_golden,
    load_residency_golden,
    score_citation_accuracy,
    score_injection_recall,
    score_principle_accuracy,
    score_residency_citation_accuracy,
    score_residency_detection_recall,
    score_residency_precision,
    score_residency_safety,
    score_safety,
)

from architecture_validator.domain.residency.detector import ViolationDetector
from architecture_validator.domain.residency.models import ResidencyPolicy

#: A submission the golden set expects to FAIL, so every architecture metric scores something.
_EXAMPLE = next(e for e in load_golden(DEFAULT_DATASET) if e.expected_failed_principles)
_RESIDENCY = load_residency_golden(RESIDENCY_DATASET)
_VIOLATING = next(r for r in _RESIDENCY if r.expected_kinds)
_CLEAN = next(r for r in _RESIDENCY if not r.expected_kinds)


@pytest.fixture(scope="module")
def report():  # type: ignore[no-untyped-def]
    service = _make_service()
    assert service is not None, "the offline gate could not construct a ValidationService"
    validated = service.validate(_EXAMPLE.submission, actor="eval-bot")
    assert validated.findings, "the proof needs a submission that produced findings"
    return validated


# --------------------------------------------------------------------------- #
# Architecture family
# --------------------------------------------------------------------------- #
def test_principle_accuracy_can_go_red(report) -> None:  # type: ignore[no-untyped-def]
    all_ids = {f.principle_id for f in report.findings}
    failed = {f.principle_id for f in report.findings if f.status.value == "FAIL"}
    assert_can_go_red(
        lambda example: score_principle_accuracy(report, example),
        green=_EXAMPLE,
        red=replace(
            _EXAMPLE, expected_failed_principles=tuple(sorted(all_ids - failed))
        ),  # every principle's expectation inverted
        threshold=THRESHOLDS["principle_accuracy"],
        metric="principle_accuracy",
    )


def test_injection_recall_can_go_red(report) -> None:  # type: ignore[no-untyped-def]
    assert_can_go_red(
        lambda rep: score_injection_recall(rep, _EXAMPLE),
        green=report,
        red=replace(report, injected_requirements=()),  # nothing was injected at all
        threshold=THRESHOLDS["injection_recall"],
        metric="injection_recall",
    )


def test_citation_accuracy_can_go_red(report) -> None:  # type: ignore[no-untyped-def]
    assert_can_go_red(
        score_citation_accuracy,
        green=report,
        red=replace(
            report,
            findings=tuple(replace(f, citations=()) for f in report.findings),
            injected_requirements=tuple(
                replace(r, citations=()) for r in report.injected_requirements
            ),
        ),  # findings and requirements raised against nothing citable
        threshold=THRESHOLDS["citation_accuracy"],
        metric="citation_accuracy",
    )


def test_safety_can_go_red(report) -> None:  # type: ignore[no-untyped-def]
    assert_can_go_red(
        lambda rep: score_safety(rep, _EXAMPLE),
        green=report,
        red=replace(report, passed=True),  # a submission expected to FAIL reported as passed
        threshold=THRESHOLDS["safety"],
        metric="safety",
    )


# --------------------------------------------------------------------------- #
# Residency family
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="module")
def detector() -> ViolationDetector:
    return ViolationDetector(ResidencyPolicy())


def test_residency_detection_recall_can_go_red(detector: ViolationDetector) -> None:
    found = {v.kind for v in detector.detect([_VIOLATING.resource])}
    assert found, "the proof needs a resource the detector actually flags"
    assert_can_go_red(
        lambda kinds: score_residency_detection_recall(_VIOLATING.expected_kinds, kinds),
        green=found,
        red=set(),  # the detector stopped detecting
        threshold=RESIDENCY_THRESHOLDS["detection_recall"],
        metric="residency_detection_recall",
    )


def test_residency_precision_can_go_red(detector: ViolationDetector) -> None:
    found = {v.kind for v in detector.detect([_CLEAN.resource])}
    assert_can_go_red(
        lambda kinds: score_residency_precision(_CLEAN.expected_kinds, kinds),
        green=found,
        red={next(iter(_VIOLATING.expected_kinds))},  # a violation flagged on a clean estate
        threshold=RESIDENCY_THRESHOLDS["precision"],
        metric="residency_precision",
    )


def test_residency_citation_accuracy_can_go_red(detector: ViolationDetector) -> None:
    violations = detector.detect([_VIOLATING.resource])
    assert_can_go_red(
        score_residency_citation_accuracy,
        green=violations,
        red=tuple(replace(v, citations=()) for v in violations),  # flagged, citing no principle
        threshold=RESIDENCY_THRESHOLDS["citation_accuracy"],
        metric="residency_citation_accuracy",
    )


def test_residency_safety_can_go_red() -> None:
    assert_can_go_red(
        lambda verdict: score_residency_safety(verdict, _VIOLATING.expected_pass),
        green=False,
        red=True,  # a violating estate reported as passing
        threshold=RESIDENCY_THRESHOLDS["safety"],
        metric="residency_safety",
    )
