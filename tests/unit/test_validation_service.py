"""Unit tests for ValidationService — the SPEC §5 intake pipeline.

Pipeline (SPEC §5 / brief):
    load principles -> policy_engine.evaluate -> for FAIL/NEEDS_INFO fetch KB citations
    + best-effort control mapping / residency -> llm drafts injected requirements ->
    assemble ValidationReport (passed = no FAIL) -> review policy -> audit.

These tests use only in-memory fakes (no Google Cloud SDK).
"""

from __future__ import annotations

import pytest
from tests.conftest import FakePolicyEngine, load_service
from tests.fixtures import sample_projects

from architecture_validator.domain.errors import PolicyEvaluationError
from architecture_validator.domain.models import CheckStatus, Decision, ValidationReport

ACTOR = "arb.reviewer@bank.test"


# --------------------------------------------------------------------------- #
# Clean submission -> PASS, no review, audited ALLOWED, no injected reqs.
# --------------------------------------------------------------------------- #
def test_compliant_submission_passes(validation_service, audit):
    report = validation_service.validate(sample_projects.COMPLIANT_SUBMISSION, actor=ACTOR)

    assert isinstance(report, ValidationReport)
    assert report.passed is True
    assert report.failed_principle_ids == ()
    assert report.requires_human_review is True
    assert report.injected_requirements == (), "a clean submission needs no injected NFRs"

    assert audit.events
    assert audit.events[-1].decision is Decision.ALLOWED
    assert audit.events[-1].action == "validate"


# --------------------------------------------------------------------------- #
# Non-compliant -> FAIL, requires review, audited ESCALATED, NFRs injected.
# --------------------------------------------------------------------------- #
def test_non_compliant_submission_fails_and_injects(validation_service, audit):
    report = validation_service.validate(sample_projects.NON_COMPLIANT_SUBMISSION, actor=ACTOR)

    assert report.passed is False
    assert set(sample_projects.NON_COMPLIANT_EXPECTED_FAILS) <= set(report.failed_principle_ids)
    assert report.requires_human_review is True

    # One injected requirement per unmet (FAIL/NEEDS_INFO) principle, each tied to a
    # principle and cited.
    unmet = {
        f.principle_id
        for f in report.findings
        if f.status in (CheckStatus.FAIL, CheckStatus.NEEDS_INFO)
    }
    injected_ids = {r.principle_id for r in report.injected_requirements}
    assert injected_ids == unmet, "every unmet principle yields exactly one injected NFR"
    for req in report.injected_requirements:
        assert req.requirement_text and req.rationale
        assert req.citations, "injected requirements must be cited"

    assert any(e.decision is Decision.ESCALATED for e in audit.events)


def test_report_has_one_finding_per_principle(validation_service):
    report = validation_service.validate(sample_projects.NON_COMPLIANT_SUBMISSION, actor=ACTOR)
    assert [f.principle_id for f in report.findings] == [f"P-{i:02d}" for i in range(1, 13)]


def test_validation_wrapped_in_tracer_span(validation_service, tracer):
    validation_service.validate(sample_projects.COMPLIANT_SUBMISSION, actor=ACTOR)
    assert "validate" in tracer.spans


# --------------------------------------------------------------------------- #
# KB context is fetched only when there are unmet principles.
# --------------------------------------------------------------------------- #
def test_kb_queried_only_when_unmet_findings(validation_service, knowledge_base):
    validation_service.validate(sample_projects.COMPLIANT_SUBMISSION, actor=ACTOR)
    assert knowledge_base.calls == [], "no KB retrieval when nothing is unmet"


def test_kb_queried_when_unmet_findings(validation_service, knowledge_base):
    validation_service.validate(sample_projects.NON_COMPLIANT_SUBMISSION, actor=ACTOR)
    assert knowledge_base.calls, "KB context fetched for the unmet principles"


# --------------------------------------------------------------------------- #
# OPA failure falls back to the deterministic evaluator (resilience, P-10).
# --------------------------------------------------------------------------- #
class _RaisingPolicyEngine(FakePolicyEngine):
    def evaluate(self, submission, principles):
        raise PolicyEvaluationError("OPA service unreachable")


def test_policy_engine_failure_falls_back_to_deterministic(
    knowledge_base, llm, tracer, audit, control_mapping, residency
):
    service = load_service("ValidationService")(
        _RaisingPolicyEngine(), knowledge_base, llm, tracer, audit, control_mapping, residency
    )
    report = service.validate(sample_projects.NON_COMPLIANT_SUBMISSION, actor=ACTOR)
    # Even with the OPA path down, the deterministic evaluator produces a full verdict.
    assert len(report.findings) == 12
    assert report.passed is False


# --------------------------------------------------------------------------- #
# Best-effort sibling outage never aborts the validation.
# --------------------------------------------------------------------------- #
class _RaisingClient:
    def coverage(self, scope):
        raise RuntimeError("control mapping down")

    def findings(self, scope):
        raise RuntimeError("residency down")


def test_sibling_outage_degrades_gracefully(policy_engine, knowledge_base, llm, tracer, audit):
    service = load_service("ValidationService")(
        policy_engine, knowledge_base, llm, tracer, audit, _RaisingClient(), _RaisingClient()
    )
    report = service.validate(sample_projects.NON_COMPLIANT_SUBMISSION, actor=ACTOR)
    assert report.passed is False  # validation still completes


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
