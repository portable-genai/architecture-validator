"""Unit tests for the deterministic principle evaluator — the heart of C3 (SPEC §5).

Each of the 12 General Principles is checked against a submission and produces a
PrincipleFinding with a status (PASS | FAIL | NEEDS_INFO | NOT_APPLICABLE), a rule_id,
evidence, a severity and a principle citation. These tests pin the FAIL / NEEDS_INFO /
NOT_APPLICABLE boundaries the brief calls out (e.g. P-03 region, P-04 PII+DLP, P-08 eval
gate, P-12 exit plan).
"""

from __future__ import annotations

import dataclasses

import pytest
from tests.fixtures import sample_projects

from architecture_validator.domain import principles_eval
from architecture_validator.domain.models import CheckStatus, ProjectSubmission, Regulator


def _sub(**overrides) -> ProjectSubmission:
    return dataclasses.replace(sample_projects.COMPLIANT_SUBMISSION, **overrides)


def _status(submission: ProjectSubmission, principle_id: str) -> CheckStatus:
    return principles_eval.evaluate_principle(submission, principle_id).status


# --------------------------------------------------------------------------- #
# evaluate_all covers exactly the 12 principles, in order, all cited.
# --------------------------------------------------------------------------- #
def test_evaluate_all_returns_twelve_ordered_cited_findings():
    findings = principles_eval.evaluate_all(sample_projects.COMPLIANT_SUBMISSION)
    assert [f.principle_id for f in findings] == [f"P-{i:02d}" for i in range(1, 13)]
    for f in findings:
        assert f.rule_id, "every finding carries the rule that produced it"
        assert f.citations, "every finding cites its principle"
        # The principle provenance citation is CROSS with the principle id as source_id.
        assert any(
            c.regulator is Regulator.CROSS and c.source_id == f.principle_id for c in f.citations
        )


def test_compliant_submission_has_no_fail():
    findings = principles_eval.evaluate_all(sample_projects.COMPLIANT_SUBMISSION)
    assert not [f for f in findings if f.status is CheckStatus.FAIL]


def test_non_compliant_submission_fails_expected_principles():
    findings = principles_eval.evaluate_all(sample_projects.NON_COMPLIANT_SUBMISSION)
    failed = {f.principle_id for f in findings if f.status is CheckStatus.FAIL}
    assert set(sample_projects.NON_COMPLIANT_EXPECTED_FAILS) <= failed


# --------------------------------------------------------------------------- #
# P-03 region: allowed / disallowed / signed-off exception / missing.
# --------------------------------------------------------------------------- #
def test_p03_allowed_region_passes():
    assert _status(_sub(declared_region="asia-southeast1"), "P-03") is CheckStatus.PASS


def test_p03_disallowed_region_fails():
    assert _status(_sub(declared_region="us-east1"), "P-03") is CheckStatus.FAIL


def test_p03_disallowed_region_with_signed_exception_passes():
    sub = _sub(declared_region="us-east1", attributes={"region_exception": "signed_off"})
    assert _status(sub, "P-03") is CheckStatus.PASS


def test_p03_missing_region_needs_info():
    assert _status(_sub(declared_region=None), "P-03") is CheckStatus.NEEDS_INFO


# --------------------------------------------------------------------------- #
# P-04 PII + DLP: NOT_APPLICABLE without PII, NEEDS_INFO with PII and no DLP.
# --------------------------------------------------------------------------- #
def test_p04_not_applicable_without_pii():
    assert _status(_sub(uses_pii=False), "P-04") is CheckStatus.NOT_APPLICABLE


def test_p04_needs_info_when_pii_without_dlp():
    sub = _sub(uses_pii=True, declared_controls=("vpc_sc",))
    assert _status(sub, "P-04") is CheckStatus.NEEDS_INFO


def test_p04_pass_when_pii_with_dlp():
    sub = _sub(uses_pii=True, declared_controls=("dlp",))
    assert _status(sub, "P-04") is CheckStatus.PASS


# --------------------------------------------------------------------------- #
# P-05 grounding over fine-tuning.
# --------------------------------------------------------------------------- #
def test_p05_fail_when_fine_tuning_on_pii():
    sub = _sub(uses_fine_tuning=True, uses_pii=True)
    assert _status(sub, "P-05") is CheckStatus.FAIL


def test_p05_needs_info_when_fine_tuning_without_rag():
    sub = _sub(uses_fine_tuning=True, uses_pii=False, uses_rag=False)
    assert _status(sub, "P-05") is CheckStatus.NEEDS_INFO


# --------------------------------------------------------------------------- #
# Control-gated FAILs: P-08 eval gate, P-06 maker-checker, P-12 exit plan.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "principle_id,control",
    [("P-08", "eval_gate"), ("P-06", "maker_checker"), ("P-01", "vpc_sc"), ("P-09", "cmek")],
)
def test_missing_control_fails_principle(principle_id: str, control: str):
    remaining = tuple(
        c for c in sample_projects.COMPLIANT_SUBMISSION.declared_controls if c != control
    )
    assert _status(_sub(declared_controls=remaining), principle_id) is CheckStatus.FAIL


def test_p12_fail_without_exit_plan():
    assert _status(_sub(has_exit_plan=False), "P-12") is CheckStatus.FAIL


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
