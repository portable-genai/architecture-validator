"""Verdict computation — turn violations into a PASS/FAIL gate result.

Pure decision logic over a list of :class:`ResidencyViolation` and the
:class:`ResidencyPolicy` gate severity. A scan PASSES iff it has **no** violation at or
above the gate severity; the per-severity counts drive the CI log and the exit code. No
Google Cloud / framework imports — only the domain models.
"""

from __future__ import annotations

from ..models import SEVERITY_RANK, Severity
from .models import (
    ResidencyPolicy,
    ResidencyViolation,
    ScanVerdict,
    SeverityCount,
)


def severity_counts(violations: list[ResidencyViolation]) -> tuple[SeverityCount, ...]:
    """Per-severity counts, ordered LOW -> CRITICAL (zero-count levels omitted)."""
    tally: dict[Severity, int] = dict.fromkeys(Severity, 0)
    for v in violations:
        tally[v.severity] += 1
    return tuple(
        SeverityCount(severity=s, count=tally[s])
        for s in sorted(Severity, key=lambda x: SEVERITY_RANK[x])
        if tally[s]
    )


def gating_violations(
    violations: list[ResidencyViolation], gate_severity: Severity
) -> list[ResidencyViolation]:
    """Violations at or above ``gate_severity`` (the ones that fail the gate)."""
    floor = SEVERITY_RANK[gate_severity]
    return [v for v in violations if SEVERITY_RANK[v.severity] >= floor]


def compute_verdict(violations: list[ResidencyViolation], policy: ResidencyPolicy) -> ScanVerdict:
    """Build the :class:`ScanVerdict` for ``violations`` under ``policy``.

    PASS iff there is no violation at or above ``policy.gate_severity``. Sub-gate
    violations (e.g. a MEDIUM when the gate is HIGH) are still reported in the counts
    but do not fail the build.
    """
    gating = gating_violations(violations, policy.gate_severity)
    return ScanVerdict(
        passed=not gating,
        gate_severity=policy.gate_severity,
        total_violations=len(violations),
        counts=severity_counts(violations),
    )
