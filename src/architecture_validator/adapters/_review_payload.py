"""Shared conversion from an escalated validation report to an ``review-kit`` Review payload.

Lives in the adapter layer (not the pure domain) because it depends on the kit. C3 is an
architecture *intake* validator: it reasons over project metadata (submission id/name, declared
region and controls, the 12 General Principles) and never handles customer PII, so there is no
redaction adapter and no ``pii-kit`` in this repo. The payload is therefore kept minimal and
non-identifying by construction; the only scrubbing applied is whitespace normalisation, so a
descriptor or finding snippet cannot smuggle newlines into the console. human-review-console still
redacts again before its own audit write (defense in depth). The maker (the analyst/service that
produced the report) and the tenant are asserted here and trusted by human-review-console because
this is an authenticated S2S caller (per-hop OBO is the deferred next layer).
"""

from __future__ import annotations

import re

from review_kit import Citation as KitCitation
from review_kit import Review

from ..domain.models import SEVERITY_RANK, CheckStatus, Severity, ValidationReport
from ..domain.residency.models import ResidencyScan

# Cap the citations carried on the wire: enough to let a reviewer trace the verdict back to the
# principles and regulator instruments without copying the entire evidence set into the console.
_MAX_CITATIONS = 8

# Ordered weakest -> strongest so ``max`` picks the report's most severe open finding.
_SEVERITY_ORDER: tuple[Severity, ...] = (
    Severity.LOW,
    Severity.MEDIUM,
    Severity.HIGH,
    Severity.CRITICAL,
)

# Statuses that represent an *open* (unmet) principle — the ones whose stakes drive the escalation.
_OPEN_STATUSES: frozenset[CheckStatus] = frozenset({CheckStatus.FAIL, CheckStatus.NEEDS_INFO})


def _scrub(text: str) -> str:
    """Collapse whitespace before the wire (no PII patterns: C3 carries no customer data)."""
    return re.sub(r"\s+", " ", text).strip()


def _overall_severity(report: ValidationReport) -> Severity:
    """The report's most severe *open* finding, floored at HIGH when intake FAILs.

    A failing principle blocks intake (``passed`` is False), so it is high-stakes regardless of
    the individual finding severity; a clean-but-flagged report (a HIGH/CRITICAL ``NEEDS_INFO``)
    carries the severity of its strongest open finding.
    """
    open_sevs = [f.severity for f in report.findings if f.status in _OPEN_STATUSES]
    sev = max(open_sevs, key=_SEVERITY_ORDER.index) if open_sevs else Severity.LOW
    if not report.passed:
        sev = max(sev, Severity.HIGH, key=_SEVERITY_ORDER.index)
    return sev


def _kit_citations(report: ValidationReport) -> tuple[KitCitation, ...]:
    seen: set[str] = set()
    out: list[KitCitation] = []
    for finding in report.findings:
        for c in finding.citations:
            if c.source_id in seen:
                continue
            seen.add(c.source_id)
            out.append(KitCitation(source_id=c.source_id, title=c.title, snippet=_scrub(c.snippet)))
            if len(out) >= _MAX_CITATIONS:
                return tuple(out)
    return tuple(out)


def report_to_review(report: ValidationReport, *, maker: str, tenant: str = "") -> Review:
    """Build the review a producer submits to human-review-console when a validation report
    escalates (R8).
    """
    submission = report.submission
    descriptor = (
        f"Architecture intake validation for {submission.name} "
        f"(id={submission.id}, region={submission.declared_region or 'unknown'})"
    )
    failed = report.failed_principle_ids
    summary = (
        f"verdict={'PASS' if report.passed else 'FAIL'}; "
        f"failed={','.join(failed) or 'none'}; "
        f"findings={len(report.findings)}; injected={len(report.injected_requirements)}"
    )
    severity = _overall_severity(report)
    # Dual control for a blocking FAIL or any high-stakes open finding; single sign-off otherwise.
    dual = (not report.passed) or severity in (Severity.HIGH, Severity.CRITICAL)
    return Review(
        action="arch_validation:intake",
        subject=_scrub(descriptor),
        maker=maker,
        tenant=tenant,
        summary=_scrub(summary),
        severity=severity.value,
        required_approvals=2 if dual else 1,
        sod_group="arch-intake-maker-checker",
        case_ref=submission.id,
        citations=_kit_citations(report),
    )


def _scan_wire_severity(scan: ResidencyScan) -> str:
    """Map the residency scan verdict to the review console's severity band.

    A gating (HIGH/CRITICAL) residency breach is ``high`` and warrants dual control; a scan whose
    worst finding is MEDIUM is ``medium``; a clean scan is ``low``. In practice a scan only reaches
    this routing path when it already carries a HIGH/CRITICAL violation (that is what sets
    ``requires_human_review``), so ``high`` / dual-control is the common case.
    """
    worst = max((SEVERITY_RANK[v.severity] for v in scan.violations), default=-1)
    if worst >= SEVERITY_RANK[Severity.HIGH]:
        return "high"
    if worst == SEVERITY_RANK[Severity.MEDIUM]:
        return "medium"
    return "low"


def _scan_kit_citations(scan: ResidencyScan) -> tuple[KitCitation, ...]:
    """Dedupe the scan violations' regulatory citations by source, capped for the wire."""
    seen: set[str] = set()
    out: list[KitCitation] = []
    for violation in scan.violations:
        for c in violation.citations:
            if c.source_id in seen:
                continue
            seen.add(c.source_id)
            out.append(KitCitation(source_id=c.source_id, title=c.title, snippet=_scrub(c.snippet)))
            if len(out) >= _MAX_CITATIONS:
                return tuple(out)
    return tuple(out)


def scan_to_review(scan: ResidencyScan, *, maker: str, tenant: str = "") -> Review:
    """Build the review a producer submits to human-review-console when a residency scan escalates
    (R8).

    The residency-scan counterpart to :func:`report_to_review`: an escalated
    :class:`ResidencyScan` carries no ``findings``, so its review is assembled from the scan's
    violations/verdict instead. Same non-identifying, whitespace-scrubbed shape (the scanner
    reads infrastructure config, not customer PII), routed to the residency maker-checker SoD
    group with four-eyes on a gating breach.
    """
    counts = ", ".join(f"{c.count} {c.severity.value}" for c in scan.verdict.counts) or "none"
    descriptor = (
        f"Residency scan of {scan.target}: {len(scan.violations)} violation(s) "
        f"across {scan.resources_scanned} resource(s)"
    )
    summary = (
        f"verdict={'PASS' if scan.passed else 'FAIL'}; "
        f"violations={scan.verdict.total_violations} ({counts}); "
        f"gate={scan.verdict.gate_severity.value}"
    )
    severity = _scan_wire_severity(scan)
    # Dual control for a gating (HIGH/CRITICAL) residency breach; a waiver needs four eyes.
    dual = severity == "high"
    return Review(
        action="residency_scan",
        subject=_scrub(descriptor),
        maker=maker,
        tenant=tenant,
        summary=_scrub(summary),
        severity=severity,
        required_approvals=2 if dual else 1,
        sod_group="residency-maker-checker",
        case_ref=scan.target,
        citations=_scan_kit_citations(scan),
    )
