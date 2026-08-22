"""Unit tests for RequirementInjectionService and the ReviewPolicy (SPEC §5).

* RequirementInjectionService.inject(submission, findings, kb_citations)
    -> one InjectedRequirement per unmet (FAIL/NEEDS_INFO) principle, LLM-drafted with
       a deterministic fallback.
* ReviewPolicy.requires_review(findings) -> bool (P-06): any FAIL or HIGH/CRITICAL.
"""

from __future__ import annotations

import pytest
from tests.conftest import load_policy, load_service
from tests.fixtures import sample_projects

from architecture_validator.domain import principles_eval
from architecture_validator.domain.models import (
    CheckStatus,
    PrincipleFinding,
    Severity,
)


def _findings(submission):
    return principles_eval.evaluate_all(submission)


# --------------------------------------------------------------------------- #
# RequirementInjectionService
# --------------------------------------------------------------------------- #
def test_inject_one_per_unmet_principle(injection_service):
    findings = _findings(sample_projects.NON_COMPLIANT_SUBMISSION)
    unmet = {
        f.principle_id for f in findings if f.status in (CheckStatus.FAIL, CheckStatus.NEEDS_INFO)
    }
    injected = injection_service.inject(
        sample_projects.NON_COMPLIANT_SUBMISSION,
        findings,
        list(sample_projects.SAMPLE_KB_CITATIONS),
    )
    assert {r.principle_id for r in injected} == unmet
    for req in injected:
        assert req.id and req.requirement_text and req.rationale
        assert req.citations


def test_inject_nothing_for_clean_submission(injection_service):
    findings = _findings(sample_projects.COMPLIANT_SUBMISSION)
    injected = injection_service.inject(sample_projects.COMPLIANT_SUBMISSION, findings, [])
    assert injected == []


class _DeadLLM:
    """An LLM that always fails, to exercise the deterministic injection fallback."""

    def generate(self, request):
        raise RuntimeError("model unavailable")

    def classify(self, text, labels):
        return ""


def test_inject_falls_back_to_remediation_when_llm_dead():
    service = load_service("RequirementInjectionService")(_DeadLLM(), None)
    findings = _findings(sample_projects.NON_COMPLIANT_SUBMISSION)
    unmet = [f for f in findings if f.status in (CheckStatus.FAIL, CheckStatus.NEEDS_INFO)]
    injected = service.inject(sample_projects.NON_COMPLIANT_SUBMISSION, findings, [])
    # Still one requirement per unmet principle, sourced from the finding remediation.
    assert {r.principle_id for r in injected} == {f.principle_id for f in unmet}
    for req in injected:
        assert req.requirement_text


# --------------------------------------------------------------------------- #
# ReviewPolicy
# --------------------------------------------------------------------------- #
def _finding(status: CheckStatus, severity: Severity) -> PrincipleFinding:
    return PrincipleFinding(
        principle_id="P-01",
        status=status,
        rule_id="rule_p_01",
        evidence="e",
        severity=severity,
    )


def test_review_required_on_any_fail():
    policy = load_policy("ReviewPolicy")()
    findings = [_finding(CheckStatus.PASS, Severity.LOW), _finding(CheckStatus.FAIL, Severity.LOW)]
    assert policy.requires_review(findings) is True


def test_review_required_on_high_severity_needs_info():
    policy = load_policy("ReviewPolicy")()
    findings = [_finding(CheckStatus.NEEDS_INFO, Severity.HIGH)]
    assert policy.requires_review(findings) is True


def test_clean_low_severity_report_still_requires_review():
    policy = load_policy("ReviewPolicy")()
    findings = [
        _finding(CheckStatus.PASS, Severity.LOW),
        _finding(CheckStatus.NOT_APPLICABLE, Severity.LOW),
    ]
    assert policy.requires_review(findings) is True


def test_review_all_reports_is_an_immutable_floor():
    with pytest.raises(ValueError, match="immutable maker-checker safety floor"):
        load_policy("ReviewPolicy")(review_all_reports=False)


def test_passed_is_true_only_without_fail():
    policy = load_policy("ReviewPolicy")
    assert policy.passed([_finding(CheckStatus.PASS, Severity.LOW)]) is True
    assert policy.passed([_finding(CheckStatus.FAIL, Severity.LOW)]) is False


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
