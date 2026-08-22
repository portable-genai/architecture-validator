"""ReviewRouterPort: the boundary that routes an escalated validation report to Hrz7 (rule R8).

C3 is the intake *gate*, never an autonomous approver: a non-clean :class:`ValidationReport`
(any FAIL, or a HIGH/CRITICAL open finding) sets ``requires_human_review`` under the maker-checker
policy (P-06). The residency scan does the same via :class:`ResidencyScan` (any
HIGH/CRITICAL residency breach). Rule R8 says a producer that sets ``requires_human_review`` MUST
route the item to the Hrz7 Human-Review & Maker-Checker Console rather than terminate the escalation
in a per-repo boolean. This port is that hand-off for both artifact kinds. The domain stays pure:
the adapter (not this port) depends on the shared ``review-kit`` client and does the S2S
submission.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import ValidationReport
from ..domain.residency.models import ResidencyScan

#: The two escalatable artifacts R8 routes: an intake report or a residency scan.
Routable = ValidationReport | ResidencyScan


@runtime_checkable
class ReviewRouterPort(Protocol):
    def route(self, item: Routable, *, maker: str, tenant: str = "") -> None:
        """Route an escalated report or residency scan to Hrz7 (idempotent per item is ideal)."""
        ...
