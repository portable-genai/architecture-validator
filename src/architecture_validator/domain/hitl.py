"""Human-in-the-loop (maker-checker) review policy — General Principle P-06.

C3 is the intake *gate*, never an autonomous approver. P-06 requires a human to review
any consequential or non-clean validation result before a project proceeds. This
module centralises that gate so the verdict threshold is auditable in one place.

Policy (SPEC §5 / brief):
* Any FAIL finding forces human review (a failing principle blocks intake).
* Any *open* finding (FAIL or NEEDS_INFO) at HIGH or CRITICAL severity forces review
  (a high-stakes NEEDS_INFO gets a second pair of eyes). A satisfied principle's
  severity is the stakes of the principle, not an open risk, so a PASS / NOT_APPLICABLE
  finding never forces review on severity alone.
* Every report requires a checker. This is an immutable safety floor; configuration can
  tune escalation signals but cannot remove independent review from a consequential report.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from .models import CheckStatus, PrincipleFinding, Severity

#: Severities considered high-stakes enough to force review.
_HIGH_SEVERITIES: frozenset[Severity] = frozenset({Severity.HIGH, Severity.CRITICAL})

#: Statuses that represent an *open* (unmet) principle.
_OPEN_STATUSES: frozenset[CheckStatus] = frozenset({CheckStatus.FAIL, CheckStatus.NEEDS_INFO})


@dataclass(frozen=True, slots=True)
class ReviewPolicy:
    """Maker-checker gate (P-06). Pure decision logic; no side effects.

    Args:
        review_on_needs_info: when True (default), a HIGH/CRITICAL ``NEEDS_INFO``
            finding forces review as well as any FAIL. Set False to gate on FAIL only.
    """

    review_on_needs_info: bool = True
    review_all_reports: bool = True
    high_severities: frozenset[Severity] = _HIGH_SEVERITIES

    def __post_init__(self) -> None:
        if not self.review_all_reports:
            raise ValueError("review_all_reports is an immutable maker-checker safety floor")

    def requires_review(self, findings: Iterable[PrincipleFinding]) -> bool:
        """Decide whether the validation result must be routed to a human checker.

        Args:
            findings: the per-principle findings for the submission.

        Returns:
            True if a human must review before the project proceeds through intake.
        """
        # ``__post_init__`` makes this branch invariant. Keep the configured fields on
        # the type because they drive review severity/routing elsewhere, but no report
        # can auto-release from this consequential intake gate.
        del findings
        return True

    @staticmethod
    def passed(findings: Iterable[PrincipleFinding]) -> bool:
        """A report passes intake only when no principle FAILs (SPEC §5 / brief)."""
        return not any(f.status is CheckStatus.FAIL for f in findings)
