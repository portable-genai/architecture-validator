"""Unit tests for ResidencyScanService — the SPEC §5 scan pipeline.

Pipeline (SPEC §5):
    parse/scan target -> detector.detect -> compute verdict
      -> llm best-effort remediation -> review policy -> audit.record

These tests use only in-memory fakes (no Google Cloud SDK). They assert: the verdict
gates correctly, the audit record is written, HIGH/CRITICAL flags human review, a
file-path target uses the stdlib parser (not the live scanner), and an LLM failure
never changes the verdict.
"""

from __future__ import annotations

import pytest
from tests.conftest import BlowingUpLLM, FakeScanner, load_service
from tests.fixtures import sample_resources as f

from architecture_validator.domain.models import Decision
from architecture_validator.domain.residency.detector import ViolationDetector
from architecture_validator.domain.residency.models import ResidencyScan

ACTOR = f.SAMPLE_ACTOR


# --------------------------------------------------------------------------- #
# Clean estate -> PASS, exit 0, no human review, audited as PASSED.
# --------------------------------------------------------------------------- #
def test_clean_resources_pass(llm, tracer, audit):
    service = load_service("ResidencyScanService")(
        FakeScanner(list(f.CLEAN_RESOURCES)), ViolationDetector(), llm, tracer, audit
    )
    scan = service.scan_resources("clean-set", list(f.CLEAN_RESOURCES), ACTOR)

    assert isinstance(scan, ResidencyScan)
    assert scan.passed is True
    assert scan.verdict.exit_code == 0
    assert scan.requires_human_review is False
    assert scan.violations == ()
    # The unified kernel AuditEvent carries C3's Decision (a clean scan maps to ALLOWED);
    # the scan-native PASSED verdict is retained verbatim in metadata["scan_decision"].
    assert any(e.decision is Decision.ALLOWED for e in audit.events)
    assert any(e.metadata["scan_decision"] == "passed" for e in audit.events)


# --------------------------------------------------------------------------- #
# Violating estate -> FAIL, exit 1, human review, audited as ESCALATED.
# --------------------------------------------------------------------------- #
def test_violations_fail_and_escalate(scan_service, audit):
    scan = scan_service.scan_resources("mixed", list(f.MIXED_RESOURCES), ACTOR)

    assert scan.passed is False
    assert scan.verdict.exit_code == 1
    assert scan.requires_human_review is True  # CRITICAL/HIGH present
    assert scan.violations
    # A CRITICAL region violation is at/above the HIGH gate -> the build fails and the
    # scan escalates; the scan-native ESCALATED maps 1:1 onto C3's Decision.ESCALATED.
    assert any(e.decision is Decision.ESCALATED for e in audit.events)
    assert any(e.metadata["scan_decision"] == "escalated" for e in audit.events)


def test_audit_summary_counts_by_severity(scan_service, audit):
    scan_service.scan_resources("mixed", list(f.MIXED_RESOURCES), ACTOR)
    assert audit.events
    event = audit.events[-1]
    assert event.target == "mixed"
    # The unified AuditEvent's verdict text is ``summary_response`` (kernel field rename).
    assert "violation" in event.summary_response
    assert event.metadata["passed"] == "false"
    # Citations carried on the audit record so the WORM trail is provenance-bearing.
    assert event.citations


# --------------------------------------------------------------------------- #
# A file-path target uses the stdlib parser, not the live scanner.
# --------------------------------------------------------------------------- #
def test_file_target_uses_parser_not_scanner(llm, tracer, audit):
    scanner = FakeScanner()  # would return MIXED if used
    service = load_service("ResidencyScanService")(scanner, ViolationDetector(), llm, tracer, audit)
    scan = service.scan_target(str(f.SAMPLE_PLAN_JSON), ACTOR)

    # The live scanner must NOT be touched for a file path.
    assert scanner.calls == []
    # The parser found the 6 resources in the sample plan.
    assert scan.resources_scanned == 6
    assert scan.passed is False  # the plan plants region/global/cmek/public violations


def test_project_target_uses_scanner(scan_service, scanner):
    scan_service.scan_target("projects/acme-sg", ACTOR, action="scan_project")
    # A non-path scope goes through the live IaCScannerPort.
    assert scanner.calls == ["projects/acme-sg"]


# --------------------------------------------------------------------------- #
# A scan is wrapped in a trace span.
# --------------------------------------------------------------------------- #
def test_scan_opens_trace_span(scan_service, tracer):
    scan_service.scan_resources("mixed", list(f.MIXED_RESOURCES), ACTOR)
    assert tracer.spans


# --------------------------------------------------------------------------- #
# An LLM failure (remediation prose) never changes the deterministic verdict.
# --------------------------------------------------------------------------- #
def test_llm_failure_does_not_change_verdict(tracer, audit):
    service = load_service("ResidencyScanService")(
        FakeScanner(), ViolationDetector(), BlowingUpLLM(), tracer, audit
    )
    scan = service.scan_resources("mixed", list(f.MIXED_RESOURCES), ACTOR)
    # The detector / verdict are unaffected by the LLM blowing up.
    assert scan.passed is False
    assert scan.violations


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
