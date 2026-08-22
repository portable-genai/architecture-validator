"""Unit tests for the verdict logic and the maker-checker review policy (SPEC §5).

* compute_verdict: PASS iff no violation at/above the gate severity; counts by severity.
* HumanReviewPolicy.requires_review: any HIGH/CRITICAL violation forces review (P-06).
"""

from __future__ import annotations

import pytest
from tests.conftest import load_policy
from tests.fixtures import sample_resources as f

from architecture_validator.domain.models import Severity
from architecture_validator.domain.residency.detector import ViolationDetector
from architecture_validator.domain.residency.models import (
    ResidencyPolicy,
    ResidencyViolation,
    ResourceConfig,
    ViolationKind,
)
from architecture_validator.domain.residency.verdict import compute_verdict, severity_counts


def _violation(severity: Severity) -> ResidencyViolation:
    return ResidencyViolation(
        resource=ResourceConfig(address="r", type="google_storage_bucket"),
        kind=ViolationKind.RESIDENCY_CONTROL_MISSING,
        found_region="asia-southeast1",
        allowed_regions=("asia-southeast1",),
        severity=severity,
        rule_id="x",
        remediation="fix",
        evidence="r",
    )


# --------------------------------------------------------------------------- #
# Verdict
# --------------------------------------------------------------------------- #
def test_clean_scan_passes():
    verdict = compute_verdict([], ResidencyPolicy())
    assert verdict.passed is True
    assert verdict.exit_code == 0
    assert verdict.total_violations == 0


def test_high_violation_fails_default_gate():
    verdict = compute_verdict([_violation(Severity.HIGH)], ResidencyPolicy())
    assert verdict.passed is False
    assert verdict.exit_code == 1


def test_medium_violation_below_high_gate_passes():
    # Default gate is HIGH: a MEDIUM finding is reported but does not fail the build.
    verdict = compute_verdict([_violation(Severity.MEDIUM)], ResidencyPolicy())
    assert verdict.passed is True
    assert verdict.total_violations == 1


def test_gate_severity_medium_fails_on_medium():
    policy = ResidencyPolicy(gate_severity=Severity.MEDIUM)
    verdict = compute_verdict([_violation(Severity.MEDIUM)], policy)
    assert verdict.passed is False


def test_severity_counts_ordered_low_to_critical():
    violations = [_violation(Severity.CRITICAL), _violation(Severity.LOW), _violation(Severity.LOW)]
    counts = severity_counts(violations)
    # LOW(2) before CRITICAL(1); zero-count severities are omitted.
    assert counts[0].severity is Severity.LOW
    assert counts[0].count == 2
    assert counts[-1].severity is Severity.CRITICAL


# --------------------------------------------------------------------------- #
# HumanReviewPolicy
# --------------------------------------------------------------------------- #
def test_high_violation_requires_review():
    policy = load_policy("HumanReviewPolicy")()
    assert policy.requires_review([_violation(Severity.HIGH)]) is True


def test_critical_violation_requires_review():
    policy = load_policy("HumanReviewPolicy")()
    assert policy.requires_review([_violation(Severity.CRITICAL)]) is True


def test_medium_only_does_not_require_review():
    policy = load_policy("HumanReviewPolicy")()
    assert policy.requires_review([_violation(Severity.MEDIUM)]) is False


def test_no_violations_does_not_require_review():
    policy = load_policy("HumanReviewPolicy")()
    assert policy.requires_review([]) is False


# --------------------------------------------------------------------------- #
# End-to-end: the real detected violations gate the mixed estate to FAIL.
# --------------------------------------------------------------------------- #
def test_detected_mixed_estate_fails_gate():
    violations = ViolationDetector().detect(list(f.MIXED_RESOURCES))
    verdict = compute_verdict(violations, ResidencyPolicy())
    assert verdict.passed is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
