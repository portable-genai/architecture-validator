"""ValidationService — the policy-as-code intake gate (SPEC §5).

Owns the validation pipeline and calls only ports. The pipeline, in order (mirrors the
brief):

    tracer.span("validate"):
      load the 12 General Principles
      -> policy_engine.evaluate(submission, principles)              [-> findings]
      -> for each FAIL / NEEDS_INFO finding: knowledge_base.retrieve [KB citations]
      -> best-effort control_mapping.coverage + residency.findings   [augment evidence]
      -> requirement injection (LLM drafts NFR prose + rationale)    [-> injected reqs]
      -> assemble ValidationReport (passed = no FAIL)
      -> ReviewPolicy sets requires_human_review (all reports by shipped policy)
      -> audit.record(submission summary + verdict)

Defensive throughout: an OPA failure falls back to the in-process deterministic
evaluator; a KB, control-mapping or residency outage degrades to evidence-only findings
rather than raising; audit failures never crash the request.

Pure domain code — no Google Cloud / ADK / FastAPI imports.
"""

from __future__ import annotations

import contextlib
from contextlib import nullcontext
from typing import Any

from . import _grounded as g
from . import principles_eval
from .errors import PolicyEvaluationError
from .hitl import ReviewPolicy
from .injection_service import RequirementInjectionService
from .models import (
    AuditEvent,
    CheckStatus,
    Citation,
    Decision,
    PrincipleFinding,
    ProjectSubmission,
    ValidationReport,
)
from .principles import all_principles
from .serialization import to_jsonable

#: Statuses that warrant fetching extra grounding context for a finding.
_UNMET: frozenset[CheckStatus] = frozenset({CheckStatus.FAIL, CheckStatus.NEEDS_INFO})


class ValidationService:
    """Validate a project submission against the 12 General Principles (SPEC §5).

    Constructor takes explicit port instances. ``control_mapping`` and ``residency`` are
    optional and consumed best-effort: their failure degrades a finding's evidence to
    NEEDS_INFO-grade context, never aborts the validation.
    """

    def __init__(
        self,
        policy_engine: Any,
        knowledge_base: Any,
        llm: Any,
        tracer: Any,
        audit: Any,
        control_mapping: Any | None = None,
        residency: Any | None = None,
        review_policy: ReviewPolicy | None = None,
        allowed_regions: tuple[str, ...] | None = None,
        review_router: Any = None,
    ) -> None:
        self._policy_engine = policy_engine
        self._knowledge_base = knowledge_base
        self._llm = llm
        self._tracer = tracer
        self._audit = audit
        self._control_mapping = control_mapping
        self._residency = residency
        self._review = review_policy or ReviewPolicy()
        self._allowed_regions = allowed_regions
        self._injector = RequirementInjectionService(llm, tracer)
        # Rule R8: when a report requires human review it is routed to human-review-console (the
        # maker-checker
        # console) rather than terminating in the ``requires_human_review`` boolean. Optional so a
        # unit test or a deployment that leaves the escalation unrouted still audits ESCALATED, it
        # just is not forwarded to a console.
        self._review_router = review_router

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def validate(
        self, submission: ProjectSubmission, actor: str, tenant: str = ""
    ) -> ValidationReport:
        """Validate ``submission`` for ``actor`` via the SPEC §5 intake pipeline.

        ``actor`` and ``tenant`` are the server-verified caller identity: ``actor`` is the audit
        subject and the maker asserted when the report is routed to human-review-console (rule R8);
        ``tenant``
        (when set) partitions the routed review. C3's submission is project metadata with no tenant
        field, so the tenant is threaded from the call, not read off the artifact. The default
        empty ``tenant`` keeps existing callers/tests unaffected.
        """
        span = self._tracer.span("validate", action="validate", actor=actor)
        with span if span is not None else nullcontext():
            return self._validate_inner(submission, actor, tenant)

    # ------------------------------------------------------------------ #
    # Pipeline
    # ------------------------------------------------------------------ #
    def _validate_inner(
        self, submission: ProjectSubmission, actor: str, tenant: str = ""
    ) -> ValidationReport:
        principles = all_principles()

        # 1) Evaluate the ruleset. The OPA path may raise; fall back to the
        #    deterministic in-process evaluator so a verdict is always produced.
        try:
            findings = list(self._policy_engine.evaluate(submission, principles))
        except PolicyEvaluationError:
            findings = principles_eval.evaluate_all(
                submission,
                allowed_regions=self._allowed_regions or principles_eval.ALLOWED_REGIONS,
            )
        if not findings:
            findings = principles_eval.evaluate_all(
                submission,
                allowed_regions=self._allowed_regions or principles_eval.ALLOWED_REGIONS,
            )

        # 2) For each unmet principle, fetch KB grounding context and best-effort
        #    coverage / residency signals; attach them as extra citations.
        kb_citations = self._gather_context(submission, findings)

        # 3) Auto-inject the missing non-functional requirements.
        injected = self._injector.inject(submission, findings, kb_citations)

        # 4) Assemble the report. passed = no FAIL; review per P-06.
        passed = ReviewPolicy.passed(findings)
        requires_review = self._review.requires_review(findings)
        report = ValidationReport(
            submission=submission,
            findings=tuple(findings),
            injected_requirements=tuple(injected),
            passed=passed,
            requires_human_review=requires_review,
        )

        # 5) Audit the verdict (submission summary + verdict; no customer PII).
        self._audit_report(actor, report)

        # 6) Rule R8: route a non-clean report to the human-review-console maker-checker console.
        # This is the
        #    producer half of the maker-checker loop over an already-assembled, already-audited
        #    report (the audit ESCALATED record is the source of truth); routing is a hand-off,
        #    never fatal to the request, so a console outage degrades to audit-only.
        if self._review_router is not None and report.requires_human_review:
            with contextlib.suppress(Exception):
                self._review_router.route(report, maker=actor, tenant=tenant)
        return report

    # ------------------------------------------------------------------ #
    # Grounding context (KB + best-effort control mapping / residency)
    # ------------------------------------------------------------------ #
    def _gather_context(
        self, submission: ProjectSubmission, findings: list[PrincipleFinding]
    ) -> list[Citation]:
        """Retrieve KB context for the unmet principles, plus the sibling-capability signals.

        Returns the union of KB citations gathered; per-finding evidence is left to the
        injection service, which receives both the findings and these citations.
        """
        unmet = [f for f in findings if f.status in _UNMET]
        if not unmet:
            return []

        query = self._context_query(submission, unmet)
        citations: list[Citation] = []
        try:
            citations.extend(g.retrieve_citations(self._knowledge_base, query))
        except Exception:  # noqa: BLE001 - KB outage degrades to evidence-only findings
            citations = []

        citations.extend(self._best_effort(self._control_mapping, "coverage", submission.name))
        citations.extend(self._best_effort(self._residency, "findings", submission.id))
        return citations

    @staticmethod
    def _context_query(submission: ProjectSubmission, unmet: list[PrincipleFinding]) -> str:
        ids = ", ".join(f.principle_id for f in unmet)
        return (
            f"Regulatory obligations relevant to {submission.name}: {submission.description}. "
            f"Unmet general principles: {ids}."
        )

    @staticmethod
    def _best_effort(client: Any | None, method: str, scope: str) -> list[Citation]:
        """Call an optional sibling client (control-mapping coverage / residency) defensively."""
        if client is None:
            return []
        fn = getattr(client, method, None)
        if fn is None:
            return []
        try:
            result = fn(scope)
        except Exception:  # noqa: BLE001 - best-effort: failures degrade silently
            return []
        return [c for c in (result or []) if isinstance(c, Citation)]

    # ------------------------------------------------------------------ #
    # Audit
    # ------------------------------------------------------------------ #
    def _audit_report(self, actor: str, report: ValidationReport) -> None:
        """Write an immutable WORM audit record for this validation (P-07)."""
        decision = Decision.ALLOWED if report.passed else Decision.ESCALATED
        failed = report.failed_principle_ids
        summary_response = (
            f"verdict={'PASS' if report.passed else 'FAIL'}; "
            f"failed={','.join(failed) or 'none'}; "
            f"injected={len(report.injected_requirements)}"
        )
        citations = tuple(c for f in report.findings for c in f.citations)
        event = AuditEvent(
            action="validate",
            actor=actor,
            decision=decision,
            summary_prompt=f"{report.submission.id}: {report.submission.name}",
            summary_response=summary_response,
            citations=citations,
            metadata={
                "passed": str(report.passed).lower(),
                "requires_human_review": str(report.requires_human_review).lower(),
                "n_findings": str(len(report.findings)),
                "n_injected": str(len(report.injected_requirements)),
            },
        )
        try:
            self._audit.record(event)
        except Exception:  # noqa: BLE001 - audit failure must not crash the request
            to_jsonable(event)
