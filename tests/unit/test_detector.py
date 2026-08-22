"""Unit tests for the deterministic ViolationDetector (the heart of the residency scan, SPEC §5).

The detector is pure: given resources + a policy it returns violations with no LLM,
no network, no SDK. These tests assert each rule fires on exactly the right resource,
that clean resources produce nothing, and that every violation cites P-01/P-03.
"""

from __future__ import annotations

import pytest
from tests.fixtures import sample_resources as f

from architecture_validator.domain.models import Severity
from architecture_validator.domain.residency.detector import ViolationDetector
from architecture_validator.domain.residency.models import (
    ResidencyControl,
    ResidencyPolicy,
    ViolationKind,
)


@pytest.fixture
def detector() -> ViolationDetector:
    return ViolationDetector()


def _kinds(violations, address):
    return {v.kind for v in violations if v.resource.address == address}


# --------------------------------------------------------------------------- #
# Clean resources produce no violations.
# --------------------------------------------------------------------------- #
def test_compliant_resources_have_no_violations(detector):
    violations = detector.detect(list(f.CLEAN_RESOURCES))
    assert violations == []


# --------------------------------------------------------------------------- #
# Each planted violation kind fires on exactly the right resource.
# --------------------------------------------------------------------------- #
def test_region_not_allowed_detected(detector):
    violations = detector.detect([f.BUCKET_WRONG_REGION])
    assert ViolationKind.REGION_NOT_ALLOWED in _kinds(violations, f.BUCKET_WRONG_REGION.address)
    v = next(v for v in violations if v.kind is ViolationKind.REGION_NOT_ALLOWED)
    assert v.severity is Severity.CRITICAL
    assert v.found_region == "us-central1"


def test_global_endpoint_detected(detector):
    violations = detector.detect([f.BUCKET_GLOBAL])
    assert ViolationKind.GLOBAL_ENDPOINT in _kinds(violations, f.BUCKET_GLOBAL.address)


def test_missing_cmek_detected(detector):
    violations = detector.detect([f.BUCKET_NO_CMEK])
    kinds = _kinds(violations, f.BUCKET_NO_CMEK.address)
    assert ViolationKind.MISSING_CMEK in kinds
    # In-region with public prevented and a perimeter -> only the CMEK gap fires.
    assert ViolationKind.REGION_NOT_ALLOWED not in kinds


def test_public_egress_detected(detector):
    violations = detector.detect([f.SQL_PUBLIC])
    assert ViolationKind.PUBLIC_EGRESS in _kinds(violations, f.SQL_PUBLIC.address)


def test_unknown_region_detected_for_data_resource(detector):
    violations = detector.detect([f.DATASET_NO_REGION])
    assert ViolationKind.UNKNOWN_REGION in _kinds(violations, f.DATASET_NO_REGION.address)


def test_missing_vpc_sc_detected(detector):
    violations = detector.detect([f.BUCKET_NO_VPCSC])
    assert ViolationKind.RESIDENCY_CONTROL_MISSING in _kinds(violations, f.BUCKET_NO_VPCSC.address)


# --------------------------------------------------------------------------- #
# Every violation cites P-01 / P-03 (citation accuracy).
# --------------------------------------------------------------------------- #
def test_all_violations_cite_a_residency_principle(detector):
    violations = detector.detect(list(f.VIOLATING_RESOURCES))
    assert violations
    for v in violations:
        source_ids = {c.source_id for c in v.citations}
        assert source_ids & {"P-01", "P-03", "P-10"}, f"{v.rule_id} cites no residency principle"
        # Evidence carries the source_ref so a reviewer can locate the offending line.
        assert v.evidence


# --------------------------------------------------------------------------- #
# A non-data resource is region-checked but not held to data controls.
# --------------------------------------------------------------------------- #
def test_non_data_resource_not_held_to_data_controls(detector):
    # google_cloud_run_service in-region with no CMEK/VPC-SC attrs -> no violation.
    violations = detector.detect([f.COMPLIANT_SERVICE])
    assert violations == []


# --------------------------------------------------------------------------- #
# Policy is configurable: relaxing required controls drops those findings.
# --------------------------------------------------------------------------- #
def test_policy_without_cmek_requirement_skips_cmek():
    policy = ResidencyPolicy(
        required_controls=frozenset({ResidencyControl.VPC_SC, ResidencyControl.NO_PUBLIC_EGRESS})
    )
    detector = ViolationDetector(policy)
    violations = detector.detect([f.BUCKET_NO_CMEK])
    assert ViolationKind.MISSING_CMEK not in {v.kind for v in violations}


def test_policy_allowing_us_region_passes_us_bucket():
    policy = ResidencyPolicy(allowed_regions=frozenset({"asia-southeast1", "us-central1"}))
    detector = ViolationDetector(policy)
    violations = detector.detect([f.BUCKET_WRONG_REGION])
    assert ViolationKind.REGION_NOT_ALLOWED not in {v.kind for v in violations}


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
