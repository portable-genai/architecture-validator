"""Deterministic, pure-Python evaluation of the 12 General Principles (SPEC §5).

This is the heart of C3. For a :class:`ProjectSubmission` it produces one
:class:`PrincipleFinding` per principle, applying the ``machine_rule`` of each
principle as a small, falsifiable check. The logic lives here (not in an adapter) so
**both** the bundled default policy engine and the test ``FakePolicyEngine`` can share
one well-tested implementation, and so the gcp/OPA path's rego bundle can be kept in
lockstep with a single source of truth.

Verdict semantics (SPEC §5 / brief):
* FAIL          — a hard, unambiguous violation of a principle's machine rule.
* NEEDS_INFO    — the submission omits information the rule needs to clear the principle.
* NOT_APPLICABLE— the principle does not bind this submission (e.g. P-04 with no PII).
* PASS          — the principle is satisfied by the declared controls / flags.

Pure domain code — only the domain models and the standard library.
"""

from __future__ import annotations

from collections.abc import Callable

from .models import (
    CheckStatus,
    Citation,
    Jurisdiction,
    PrincipleFinding,
    ProjectSubmission,
    Regulator,
    Severity,
)
from .principles import ALLOWED_REGIONS, PRINCIPLES, PRINCIPLES_BY_ID

# A rule id per principle (mirrors the parallel rego rule names under policies/).
_RULE_ID = {p.id: f"rule_{p.id.lower().replace('-', '_')}" for p in PRINCIPLES}


def _has(submission: ProjectSubmission, control: str) -> bool:
    """Whether ``control`` is among the submission's declared controls (case-insensitive)."""
    declared = {c.strip().lower() for c in submission.declared_controls}
    return control.strip().lower() in declared


def _attr_true(submission: ProjectSubmission, key: str) -> bool:
    """Whether a free-form attribute is set truthy (e.g. a signed-off region exception)."""
    value = submission.attributes.get(key, "")
    return str(value).strip().lower() in {"true", "yes", "1", "signed", "signed_off", "approved"}


def principle_citation(principle_id: str) -> Citation:
    """A lightweight CROSS-provenance citation pointing at a General Principle."""
    principle = PRINCIPLES_BY_ID.get(principle_id)
    title = principle.title if principle else principle_id
    return Citation(
        source_id=principle_id,
        regulator=Regulator.CROSS,
        jurisdiction=Jurisdiction.GLOBAL,
        title=f"General Principle {principle_id}: {title}",
        url=f"https://rsk.internal/principles/{principle_id}",
        version="2026",
        snippet=(principle.statement if principle else ""),
    )


# --------------------------------------------------------------------------- #
# Per-principle checks. Each returns (status, evidence, severity, remediation).
# --------------------------------------------------------------------------- #
def _p01(s: ProjectSubmission) -> tuple[CheckStatus, str, Severity, str]:
    if _has(s, "vpc_sc"):
        return (
            CheckStatus.PASS,
            "VPC Service Controls perimeter declared; managed-service APIs are private.",
            Severity.HIGH,
            "",
        )
    return (
        CheckStatus.FAIL,
        "No VPC Service Controls perimeter declared; managed-service APIs would egress publicly.",
        Severity.HIGH,
        "Place all managed-service APIs inside a VPC-SC perimeter over private "
        "interconnect; no public egress.",
    )


def _p02(s: ProjectSubmission) -> tuple[CheckStatus, str, Severity, str]:
    if _has(s, "ports_and_adapters") or _attr_true(s, "documented_fallback"):
        return (
            CheckStatus.PASS,
            "Ports-and-adapters architecture and/or a documented model fallback are declared.",
            Severity.MEDIUM,
            "",
        )
    return (
        CheckStatus.FAIL,
        "No ports-and-adapters boundary or documented fallback declared; the design "
        "risks vendor lock-in.",
        Severity.MEDIUM,
        "Adopt a ports-and-adapters boundary over open standards and document a Gemma "
        "(or equivalent) fallback.",
    )


def _p03(
    s: ProjectSubmission, allowed_regions: tuple[str, ...] = ALLOWED_REGIONS
) -> tuple[CheckStatus, str, Severity, str]:
    region = (s.declared_region or "").strip()
    if not region:
        return (
            CheckStatus.NEEDS_INFO,
            "No region declared; residency cannot be confirmed.",
            Severity.HIGH,
            "Declare the single in-country region for all data and processing.",
        )
    if region in allowed_regions:
        return (
            CheckStatus.PASS,
            f"Region '{region}' is an approved in-country region.",
            Severity.HIGH,
            "",
        )
    if _attr_true(s, "region_exception"):
        return (
            CheckStatus.PASS,
            f"Region '{region}' is outside the approved set but carries a signed-off exception.",
            Severity.HIGH,
            "",
        )
    return (
        CheckStatus.FAIL,
        f"Region '{region}' is not an approved in-country region and no exception is signed off.",
        Severity.CRITICAL,
        "Pin all data and processing to an approved in-country region "
        f"({', '.join(allowed_regions)}).",
    )


def _p04(s: ProjectSubmission) -> tuple[CheckStatus, str, Severity, str]:
    if not s.uses_pii:
        return (
            CheckStatus.NOT_APPLICABLE,
            "The project declares no PII processing, so boundary redaction does not bind.",
            Severity.LOW,
            "",
        )
    if _has(s, "dlp"):
        return (
            CheckStatus.PASS,
            "PII is processed and DLP boundary redaction is declared.",
            Severity.HIGH,
            "",
        )
    return (
        CheckStatus.NEEDS_INFO,
        "The project processes PII but does not declare DLP boundary redaction.",
        Severity.HIGH,
        "Redact PII at the boundary via DLP before any model call (minimise data to the model).",
    )


def _p05(s: ProjectSubmission) -> tuple[CheckStatus, str, Severity, str]:
    if s.uses_fine_tuning and s.uses_pii:
        return (
            CheckStatus.FAIL,
            "The project fine-tunes a model on data that includes PII.",
            Severity.CRITICAL,
            "Do not train on PII; prefer retrieval-augmented grounding on governed data.",
        )
    if s.uses_fine_tuning and not s.uses_rag:
        return (
            CheckStatus.NEEDS_INFO,
            "The project fine-tunes without a declared grounding (RAG) approach.",
            Severity.MEDIUM,
            "Prefer grounding over fine-tuning; justify any fine-tuning and confirm no "
            "PII is used.",
        )
    return (
        CheckStatus.PASS,
        "Grounding-first approach with no PII fine-tuning.",
        Severity.MEDIUM,
        "",
    )


def _p06(s: ProjectSubmission) -> tuple[CheckStatus, str, Severity, str]:
    if _has(s, "maker_checker"):
        return (
            CheckStatus.PASS,
            "A maker-checker human-in-the-loop control is declared.",
            Severity.HIGH,
            "",
        )
    return (
        CheckStatus.FAIL,
        "No maker-checker / human-in-the-loop control declared for consequential decisions.",
        Severity.HIGH,
        "Add a maker-checker gate so a human reviews consequential decisions before "
        "they take effect.",
    )


def _p07(s: ProjectSubmission) -> tuple[CheckStatus, str, Severity, str]:
    if not _has(s, "audit_logging"):
        return (
            CheckStatus.FAIL,
            "No immutable audit-logging control declared.",
            Severity.HIGH,
            "Emit immutable (WORM) audit logs with citations for every decision.",
        )
    if not _has(s, "model_card"):
        return (
            CheckStatus.NEEDS_INFO,
            "Audit logging is declared but no model card is provided for explainability.",
            Severity.MEDIUM,
            "Publish a model card documenting purpose, data, limitations and evaluation.",
        )
    return (
        CheckStatus.PASS,
        "Immutable audit logging and a model card are declared.",
        Severity.HIGH,
        "",
    )


def _p08(s: ProjectSubmission) -> tuple[CheckStatus, str, Severity, str]:
    if _has(s, "eval_gate"):
        return (
            CheckStatus.PASS,
            "An evaluation gate guards promotion to production.",
            Severity.HIGH,
            "",
        )
    return (
        CheckStatus.FAIL,
        "No evaluation gate declared; promotion would be ungated.",
        Severity.HIGH,
        "Gate promotion on a quantitative evaluation suite that must pass before release.",
    )


def _p09(s: ProjectSubmission) -> tuple[CheckStatus, str, Severity, str]:
    if not _has(s, "cmek"):
        return (
            CheckStatus.FAIL,
            "No customer-managed encryption keys (CMEK) declared.",
            Severity.HIGH,
            "Encrypt with CMEK, use private endpoints, least-privilege IAM and distinct "
            "agent identities.",
        )
    if not _has(s, "least_privilege_iam"):
        return (
            CheckStatus.NEEDS_INFO,
            "CMEK is declared but least-privilege IAM is not confirmed.",
            Severity.MEDIUM,
            "Confirm least-privilege IAM roles and distinct per-agent service identities.",
        )
    return (
        CheckStatus.PASS,
        "CMEK and least-privilege IAM are declared (defense in depth).",
        Severity.HIGH,
        "",
    )


def _p10(s: ProjectSubmission) -> tuple[CheckStatus, str, Severity, str]:
    if _has(s, "kill_switch") or _has(s, "circuit_breaker"):
        return (
            CheckStatus.PASS,
            "Resilience controls (kill-switch / circuit breaker) are declared.",
            Severity.HIGH,
            "",
        )
    return (
        CheckStatus.NEEDS_INFO,
        "No kill-switch or circuit-breaker declared for graceful degradation.",
        Severity.HIGH,
        "Add fallbacks, a circuit breaker and a kill-switch (APRA CPS 230 / HKMA OR-2).",
    )


def _p11(s: ProjectSubmission) -> tuple[CheckStatus, str, Severity, str]:
    if any(_has(s, c) for c in ("model_routing", "caching", "token_budget")):
        return (
            CheckStatus.PASS,
            "Cost / latency control declared (model routing, caching or token budgets).",
            Severity.LOW,
            "",
        )
    return (
        CheckStatus.NEEDS_INFO,
        "No cost / latency control declared.",
        Severity.LOW,
        "Add model routing, response caching and per-request token budgets.",
    )


def _p12(s: ProjectSubmission) -> tuple[CheckStatus, str, Severity, str]:
    if s.has_exit_plan:
        return (
            CheckStatus.PASS,
            "A documented exit plan is declared (reversibility).",
            Severity.MEDIUM,
            "",
        )
    return (
        CheckStatus.FAIL,
        "No documented exit plan; the system is not demonstrably reversible.",
        Severity.MEDIUM,
        "Document and test an exit plan that lets the system be migrated off the managed stack.",
    )


_CHECKS: dict[str, Callable[[ProjectSubmission], tuple[CheckStatus, str, Severity, str]]] = {
    "P-01": _p01,
    "P-02": _p02,
    "P-03": _p03,
    "P-04": _p04,
    "P-05": _p05,
    "P-06": _p06,
    "P-07": _p07,
    "P-08": _p08,
    "P-09": _p09,
    "P-10": _p10,
    "P-11": _p11,
    "P-12": _p12,
}


def evaluate_principle(
    submission: ProjectSubmission,
    principle_id: str,
    *,
    allowed_regions: tuple[str, ...] = ALLOWED_REGIONS,
) -> PrincipleFinding:
    """Evaluate a single principle against ``submission`` deterministically."""
    check = _CHECKS.get(principle_id)
    if check is None:
        return PrincipleFinding(
            principle_id=principle_id,
            status=CheckStatus.NEEDS_INFO,
            rule_id=_RULE_ID.get(principle_id, f"rule_{principle_id}"),
            evidence=f"No deterministic check is registered for principle {principle_id}.",
            severity=Severity.MEDIUM,
            remediation="",
            citations=(principle_citation(principle_id),),
        )
    status, evidence, severity, remediation = (
        _p03(submission, allowed_regions) if principle_id == "P-03" else check(submission)
    )
    return PrincipleFinding(
        principle_id=principle_id,
        status=status,
        rule_id=_RULE_ID[principle_id],
        evidence=evidence,
        severity=severity,
        remediation=remediation,
        citations=(principle_citation(principle_id),),
    )


def evaluate_all(
    submission: ProjectSubmission, *, allowed_regions: tuple[str, ...] = ALLOWED_REGIONS
) -> list[PrincipleFinding]:
    """Evaluate every one of the 12 General Principles against ``submission``.

    Findings are returned in canonical principle-id order (P-01..P-12).
    """
    return [
        evaluate_principle(submission, p.id, allowed_regions=allowed_regions) for p in PRINCIPLES
    ]
