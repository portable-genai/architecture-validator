"""Human-in-the-loop (maker-checker) policy for residency scans — General Principle P-06.

The residency scan is a *gate*, not an autonomous approver. The gate verdict (PASS/FAIL)
is deterministic and machine-enforced, but granting an *exception* to a residency
violation is consequential and must be reviewed by a human. This module centralises that
gate so the scan service applies one rule and the threshold is auditable in one place.

Policy:
* Any HIGH or CRITICAL violation present in a scan flags the scan
  ``requires_human_review`` — a residency breach of that severity must not be waived by
  an automated process; a maker (the validator) proposes, a checker (a qualified human)
  disposes before any exception is granted.
* A clean scan, or one with only LOW/MEDIUM findings, does not require review.

Named :class:`HumanReviewPolicy` to stay distinct from C3's own ``hitl.ReviewPolicy``
(the principle-finding maker-checker gate).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import SEVERITY_RANK, Severity
from .models import ResidencyViolation

#: Severities that force human review of a scan before an exception can be granted.
_REVIEW_FLOOR: Severity = Severity.HIGH


@dataclass(frozen=True, slots=True)
class HumanReviewPolicy:
    """Maker-checker gate (P-06) for residency scans. Pure decision logic; no side effects.

    Args:
        review_floor: the lowest severity that forces human review. Defaults to HIGH,
            so any HIGH/CRITICAL residency violation is escalated.
    """

    review_floor: Severity = _REVIEW_FLOOR

    def requires_review(self, violations: list[ResidencyViolation]) -> bool:
        """Whether ``violations`` must be routed to a human checker before a waiver."""
        floor = SEVERITY_RANK[self.review_floor]
        return any(SEVERITY_RANK[v.severity] >= floor for v in violations)
