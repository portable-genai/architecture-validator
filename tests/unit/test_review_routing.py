"""R8 routing: a non-clean validation report is routed to human-review-console via the shared
review-kit.

C3 is the intake *gate* and never an autonomous approver: a report with any FAIL (or a HIGH/CRITICAL
open finding) sets ``requires_human_review`` under the maker-checker policy (P-06), and rule R8 says
it MUST be handed to the human-review-console rather than left as a boolean. These tests prove the
producer half of that loop end-to-end against the offline local router (an in-memory outbox), plus
the verdict -> severity / dual-control mapping in the payload.

C3 carries project metadata, not customer PII, so there is no redaction adapter in this repo and
no redact-before-wire test; the payload is minimal and non-identifying by construction.

Fictional data only.
"""

from __future__ import annotations

import pytest
from tests.conftest import load_service
from tests.fixtures import sample_projects
from tests.fixtures import sample_resources as f

from architecture_validator.adapters._review_payload import report_to_review
from architecture_validator.adapters.local.review_router import LocalReviewRouter
from architecture_validator.config import Settings
from architecture_validator.domain.models import (
    CheckStatus,
    Citation,
    Jurisdiction,
    PrincipleFinding,
    ProjectSubmission,
    Regulator,
    Severity,
    ValidationReport,
)

ACTOR = "reviewer@bank.test"
TENANT = "demo-bank"


def _service_with_router(
    policy_engine,
    knowledge_base,
    llm,
    tracer,
    audit,
    control_mapping,
    residency,
    router,
):
    return load_service("ValidationService")(
        policy_engine,
        knowledge_base,
        llm,
        tracer,
        audit,
        control_mapping,
        residency,
        review_router=router,
    )


def test_validate_routes_escalated_report_to_outbox(
    policy_engine, knowledge_base, llm, tracer, audit, control_mapping, residency
):
    """A non-clean validation enqueues exactly one review to the router's outbox (R8)."""
    router = LocalReviewRouter(Settings())
    service = _service_with_router(
        policy_engine, knowledge_base, llm, tracer, audit, control_mapping, residency, router
    )
    assert not router.outbox.pending()

    report = service.validate(sample_projects.NON_COMPLIANT_SUBMISSION, actor=ACTOR, tenant=TENANT)
    assert report.requires_human_review

    pending = router.outbox.pending()
    assert len(pending) == 1, (
        "the escalated report must be routed to human-review-console exactly once"
    )
    review = pending[0].review
    assert review.action == "arch_validation:intake"
    assert review.case_ref == report.submission.id
    assert review.maker == ACTOR
    assert review.tenant == TENANT


def test_clean_report_is_still_routed_for_maker_checker(
    policy_engine, knowledge_base, llm, tracer, audit, control_mapping, residency
):
    """The shipped policy routes even a clean report for independent approval."""
    router = LocalReviewRouter(Settings())
    service = _service_with_router(
        policy_engine, knowledge_base, llm, tracer, audit, control_mapping, residency, router
    )
    report = service.validate(sample_projects.COMPLIANT_SUBMISSION, actor=ACTOR, tenant=TENANT)
    assert report.requires_human_review is True
    assert len(router.outbox.pending()) == 1


def _submission() -> ProjectSubmission:
    return ProjectSubmission(
        id="proj-fictional-042",
        name="Fictional onboarding assistant",
        description="A synthetic submission for tests only.",
        requirements="Ship with the mandated controls.",
        declared_region="us-central1",
    )


def _fail_report() -> ValidationReport:
    """A blocking report: one FAIL finding carrying a KB citation."""
    cite = Citation(
        source_id="mas-trm-guidelines",
        regulator=Regulator.MAS,
        jurisdiction=Jurisdiction.SG,
        title="MAS Technology Risk Management Guidelines",
        url="https://example.test/mas/trm",
        page=42,
        snippet="Pin data and processing to an approved in-country region.",
    )
    finding = PrincipleFinding(
        principle_id="P-03",
        status=CheckStatus.FAIL,
        rule_id="region.allowed",
        evidence="declared_region us-central1 is not in the allowlist",
        severity=Severity.MEDIUM,
        citations=(cite,),
    )
    return ValidationReport(
        submission=_submission(),
        findings=(finding,),
        passed=False,
        requires_human_review=True,
    )


def test_payload_maps_fail_to_high_severity_and_dual_control():
    """A blocking FAIL floors severity at HIGH and requires dual control (R8)."""
    review = report_to_review(_fail_report(), maker=ACTOR, tenant=TENANT)

    assert review.tenant == TENANT
    assert review.severity == "high", "a failing principle blocks intake -> high stakes"
    assert review.required_approvals == 2, "a blocking FAIL warrants four-eyes"
    assert review.sod_group == "arch-intake-maker-checker"
    assert "verdict=FAIL" in review.summary
    assert "P-03" in review.summary
    # The finding's KB citation is carried so a reviewer can trace the verdict.
    assert any(c.source_id == "mas-trm-guidelines" for c in review.citations)


def test_payload_maps_needs_info_to_medium_single_control():
    """A passed report with only a MEDIUM open finding maps to medium / single sign-off."""
    finding = PrincipleFinding(
        principle_id="P-04",
        status=CheckStatus.NEEDS_INFO,
        rule_id="dlp.declared",
        evidence="DLP posture unclear",
        severity=Severity.MEDIUM,
    )
    report = ValidationReport(
        submission=_submission(),
        findings=(finding,),
        passed=True,
        requires_human_review=False,
    )
    review = report_to_review(report, maker=ACTOR, tenant=TENANT)
    assert review.severity == "medium"
    assert review.required_approvals == 1


def test_no_router_still_returns_report(
    policy_engine, knowledge_base, llm, tracer, audit, control_mapping, residency
):
    """Routing is optional: with no router bound, validation still returns the escalated report."""
    service = _service_with_router(
        policy_engine, knowledge_base, llm, tracer, audit, control_mapping, residency, None
    )
    report = service.validate(sample_projects.NON_COMPLIANT_SUBMISSION, actor=ACTOR)
    assert report.requires_human_review


# --------------------------------------------------------------------------- #
# Rule R8 — the residency scan routes the SAME way: an escalated
# ``ResidencyScan`` (no ``findings``, only violations) is converted to a review and
# handed to human-review-console via the shared router, through the ``scan_to_review`` payload and
# the
# isinstance dispatch. Both paths are asserted here.
# --------------------------------------------------------------------------- #
SCAN_ACTOR = f.SAMPLE_ACTOR
SCAN_TENANT = "acme-sg"


def _scan_service(scanner, detector, llm, tracer, audit, router):
    """Build a ResidencyScanService wired with an explicit review router."""
    return load_service("ResidencyScanService")(
        scanner, detector, llm, tracer, audit, review_router=router
    )


def test_escalated_scan_routes_exactly_one_review(scanner, detector, llm, tracer, audit):
    """An escalated residency scan enqueues exactly one residency_scan review (R8)."""
    router = LocalReviewRouter(Settings())
    service = _scan_service(scanner, detector, llm, tracer, audit, router)

    scan = service.scan_resources("mixed", list(f.MIXED_RESOURCES), SCAN_ACTOR, tenant=SCAN_TENANT)

    assert scan.requires_human_review is True
    pending = router.outbox.pending()
    assert len(pending) == 1, (
        "an escalated scan must route exactly one review to human-review-console"
    )
    review = pending[0].review
    assert review.action == "residency_scan"
    assert review.maker == SCAN_ACTOR
    assert review.tenant == SCAN_TENANT
    assert review.case_ref == "mixed"
    # Citations to the breached principle(s)/regulator(s) travel with the review.
    assert review.citations


def test_clean_scan_routes_nothing(scanner, detector, llm, tracer, audit):
    """A clean scan (no gating violation) is audited but never routed."""
    router = LocalReviewRouter(Settings())
    service = _scan_service(scanner, detector, llm, tracer, audit, router)

    scan = service.scan_resources("clean-set", list(f.CLEAN_RESOURCES), SCAN_ACTOR)

    assert scan.requires_human_review is False
    assert router.outbox.pending() == (), "a clean scan must not route a review"


def test_gating_scan_breach_routes_high_with_dual_control(scanner, detector, llm, tracer, audit):
    """A gating (HIGH/CRITICAL) residency breach routes at high severity with four-eyes."""
    router = LocalReviewRouter(Settings())
    service = _scan_service(scanner, detector, llm, tracer, audit, router)

    service.scan_resources("mixed", list(f.MIXED_RESOURCES), SCAN_ACTOR)

    review = router.outbox.pending()[0].review
    assert review.severity == "high"
    assert review.required_approvals == 2, "a gating residency breach warrants four-eyes"
    assert review.sod_group == "residency-maker-checker"


def test_scan_router_is_optional(scanner, detector, llm, tracer, audit):
    """With no router bound the scan still grades identically (best-effort R8)."""
    service = load_service("ResidencyScanService")(scanner, detector, llm, tracer, audit)

    scan = service.scan_resources("mixed", list(f.MIXED_RESOURCES), SCAN_ACTOR)

    assert scan.passed is False
    assert scan.requires_human_review is True
    assert scan.violations


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
