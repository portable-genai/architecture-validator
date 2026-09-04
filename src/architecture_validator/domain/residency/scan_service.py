"""ResidencyScanService — the residency scan orchestration.

Owns the scan pipeline and calls only ports + the pure detector. The pipeline, in order:

    tracer.span("residency.scan"):
      parse/scan target -> ResourceConfig[]
        (a local plan.json / .tf path uses the pure-Python terraform parser;
         a project / scope uses the IaCScannerPort live source)
      -> detector.detect -> ResidencyViolation[]
      -> compute verdict (passed = no violation >= gate severity)
      -> llm best-effort remediation narrative (deterministic findings, prose only)
      -> review policy (any HIGH/CRITICAL -> requires_human_review)
      -> audit.record(scan summary)

The detector is deterministic; the LLM only drafts human-readable remediation prose and
never changes the verdict. Defensive throughout: a missing live source or a malformed
model reply degrades gracefully rather than corrupting the gate result.

Pure domain code — no Google Cloud / ADK / FastAPI imports. It emits the kernel-unified
:class:`~architecture_validator.domain.models.AuditEvent` via the one shared audit port, mapping
its scan-native :class:`ResidencyDecision` onto C3's ``Decision`` for the WORM record.
"""

from __future__ import annotations

import contextlib
from contextlib import nullcontext
from typing import Any

from ..models import AuditEvent, Citation, Decision
from . import _remediation as r
from .detector import ViolationDetector
from .hitl import HumanReviewPolicy
from .models import (
    ResidencyDecision,
    ResidencyPolicy,
    ResidencyScan,
    ResidencyViolation,
    ResourceConfig,
)
from .prompts import _FACTS_RULES, REMEDIATION_SYSTEM, REMEDIATION_USER
from .verdict import compute_verdict

# JSON schema for the structured remediation response.
_REMEDIATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "remediation": {"type": "string"},
        "per_violation": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rule_id": {"type": "string"},
                    "fix": {"type": "string"},
                },
                "required": ["rule_id", "fix"],
            },
        },
    },
    "required": ["remediation"],
}

# Asset-scope prefixes that denote a live project / folder / org scan (the IaCScannerPort)
# rather than a local file the pure-Python Terraform parser should read.
_SCOPE_PREFIXES: tuple[str, ...] = ("projects/", "folders/", "organizations/")

# Map the scan-native decision onto C3's unified AuditEvent.Decision for the WORM record.
# The scan-native decision (passed/failed/escalated) is retained verbatim in the event
# metadata so no fidelity is lost.
_DECISION_MAP: dict[ResidencyDecision, Decision] = {
    ResidencyDecision.PASSED: Decision.ALLOWED,
    ResidencyDecision.FAILED: Decision.BLOCKED,
    ResidencyDecision.ESCALATED: Decision.ESCALATED,
}


class ResidencyScanService:
    """Scan a target for residency violations. Constructor takes explicit ports.

    ``scanner`` is the live ``IaCScannerPort`` (Cloud Asset Inventory + SCC) used for
    project / scope targets; file-path targets always use the bundled pure-Python
    Terraform parser, so a CI gate over a plan file never needs the scanner or the SDK.
    """

    def __init__(
        self,
        scanner: Any,
        detector: ViolationDetector,
        llm: Any,
        tracer: Any,
        audit: Any,
        review_policy: HumanReviewPolicy | None = None,
        review_router: Any = None,
    ) -> None:
        self._scanner = scanner
        self._detector = detector
        self._llm = llm
        self._tracer = tracer
        self._audit = audit
        self._review = review_policy or HumanReviewPolicy()
        # Rule R8: when a scan requires human review it is routed to human-review-console (the
        # maker-checker
        # console) rather than terminating in a boolean. Optional so the pure domain and every
        # existing test/caller keep working without a router bound (best-effort escalation).
        self._review_router = review_router

    @property
    def policy(self) -> ResidencyPolicy:
        return self._detector.policy

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def scan_target(
        self,
        target: str,
        actor: str,
        *,
        action: str = "scan_iac",
        tenant: str = "",
    ) -> ResidencyScan:
        """Scan ``target`` (a plan/.tf path or a project scope) for ``actor``.

        ``tenant`` (when set) is carried through to the human-review-console review hand-off (rule
        R8) so a routed
        escalation is attributed to the caller's tenant; the artifact itself has no tenant field
        (an infrastructure scan is not customer-tenant-scoped), so the default empty ``tenant``
        keeps existing callers unaffected.
        """
        with self._span(action, actor):
            resources = self._resolve_resources(target, action)
            return self._scan_resources(target, resources, actor, action, tenant)

    def scan_resources(
        self,
        target: str,
        resources: list[ResourceConfig],
        actor: str,
        *,
        action: str = "scan_iac",
        tenant: str = "",
    ) -> ResidencyScan:
        """Scan an already-parsed list of resources (the API's ``resources[]`` path)."""
        with self._span(action, actor):
            return self._scan_resources(target, resources, actor, action, tenant)

    def _span(self, action: str, actor: str) -> Any:
        """Open a trace span defensively.

        Observability is best-effort and must never fail the gate: if the tracer is an
        on-prem placeholder (or otherwise raises / returns None), the scan runs inside a
        ``nullcontext`` so the file-based CI gate stays SDK-free under any profile.
        """
        try:
            span = self._tracer.span("residency.scan", action=action, actor=actor)
        except Exception:  # noqa: BLE001 - tracing must never break the scan path
            return nullcontext()
        return span if span is not None else nullcontext()

    # ------------------------------------------------------------------ #
    # Pipeline
    # ------------------------------------------------------------------ #
    def _scan_resources(
        self,
        target: str,
        resources: list[ResourceConfig],
        actor: str,
        action: str,
        tenant: str = "",
    ) -> ResidencyScan:
        violations = self._detector.detect(resources)
        verdict = compute_verdict(violations, self.policy)
        requires_review = self._review.requires_review(violations)

        # Best-effort remediation narrative (deterministic findings; prose only).
        self._maybe_remediation(target, violations)

        scan = ResidencyScan(
            target=target,
            resources_scanned=len(resources),
            violations=tuple(violations),
            verdict=verdict,
            passed=verdict.passed,
            requires_human_review=requires_review,
        )
        self._audit_scan(actor, scan, action)
        self._maybe_route_review(scan, actor, tenant)
        return scan

    def _maybe_route_review(self, scan: ResidencyScan, actor: str, tenant: str) -> None:
        """Route an escalated scan to the human-review-console maker-checker console (rule R8).

        Runs after the audit write so the WORM record of the scan exists first. Best-effort and
        non-fatal: routing must never break the deterministic gate verdict, so any router / network
        failure is suppressed (the escalation is already recorded in the audit trail as ESCALATED).
        """
        if self._review_router is not None and scan.requires_human_review:
            with contextlib.suppress(Exception):
                self._review_router.route(scan, maker=actor, tenant=tenant)

    def _resolve_resources(self, target: str, action: str) -> list[ResourceConfig]:
        """Use the live scanner for a project scope, else the stdlib Terraform parser.

        An explicit ``scan_project`` action, or a ``projects/`` | ``folders/`` |
        ``organizations/`` scope, goes through the live ``IaCScannerPort``; everything
        else is a local plan / directory parsed offline by ``pipelines``.
        """
        if action == "scan_project" or self._looks_like_scope(target):
            return list(self._scanner.scan(target) or [])
        from ...pipelines import terraform

        return terraform.parse_target(target)

    @staticmethod
    def _looks_like_scope(target: str) -> bool:
        return target.strip().startswith(_SCOPE_PREFIXES)

    # ------------------------------------------------------------------ #
    # LLM remediation (best-effort, never changes the verdict)
    # ------------------------------------------------------------------ #
    def _maybe_remediation(self, target: str, violations: list[ResidencyViolation]) -> str:
        """Draft a remediation narrative; returns "" on any failure or no violations."""
        if not violations:
            return ""
        system = REMEDIATION_SYSTEM.format(facts_rules=_FACTS_RULES)
        user = REMEDIATION_USER.format(target=target, violations=r.render_violations(violations))
        request = r.build_llm_request(
            system_instruction=system,
            user_content=user,
            model=None,
            response_schema=_REMEDIATION_SCHEMA,
        )
        try:
            response = self._llm.generate(request)
        except Exception:  # noqa: BLE001 - remediation prose must never fail the gate
            return ""
        r.maybe_record_usage(self._tracer, response)
        parsed = r.parse_structured(response)
        return str(parsed.get("remediation") or "")

    # ------------------------------------------------------------------ #
    # Audit
    # ------------------------------------------------------------------ #
    def _audit_scan(self, actor: str, scan: ResidencyScan, action: str) -> None:
        """Write an immutable WORM audit record summarising the scan (A5 / P-07)."""
        if scan.passed:
            scan_decision = ResidencyDecision.PASSED
        elif scan.requires_human_review:
            scan_decision = ResidencyDecision.ESCALATED
        else:
            scan_decision = ResidencyDecision.FAILED
        counts = ", ".join(f"{c.count} {c.severity.value}" for c in scan.verdict.counts) or "none"
        citations: tuple[Citation, ...] = tuple(
            {(c.source_id, c.page): c for v in scan.violations for c in v.citations}.values()
        )
        summary = (
            f"{len(scan.violations)} violation(s) ({counts}) across "
            f"{scan.resources_scanned} resource(s); verdict="
            f"{'PASS' if scan.passed else 'FAIL'}"
        )
        event = AuditEvent(
            action=action,
            actor=actor,
            # Unified kernel AuditEvent carries C3's Decision; the scan-native verdict is
            # retained verbatim in metadata["scan_decision"] so nothing is lost.
            decision=_DECISION_MAP[scan_decision],
            summary_prompt=scan.target,
            summary_response=summary,
            citations=citations,
            resource="residency-validator",
            target=scan.target,
            metadata={
                "scan_decision": scan_decision.value,
                "passed": str(scan.passed).lower(),
                "requires_human_review": str(scan.requires_human_review).lower(),
                "resources_scanned": str(scan.resources_scanned),
                "gate_severity": scan.verdict.gate_severity.value,
            },
        )
        try:
            self._audit.record(event)
        except Exception:  # noqa: BLE001 - audit failure must not crash the scan
            from ..serialization import to_jsonable

            to_jsonable(event)
