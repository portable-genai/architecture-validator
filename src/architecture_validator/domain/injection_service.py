"""RequirementInjectionService — auto-inject missing NFRs at intake (SPEC §5).

From the FAIL / NEEDS_INFO principle findings, this service produces one
:class:`InjectedRequirement` per unmet principle: the missing non-functional
requirement a project must add before it can start compliant (R6). The requirement
text and rationale are LLM-drafted, grounded in the principle text and any KB
citations; the verdict itself is never changed (the policy engine owns verdicts).

The service degrades gracefully: if the LLM is unavailable or returns nothing usable,
it falls back to the deterministic remediation text already attached to each finding,
so an unmet principle always yields an injected requirement.

Pure domain code — no Google Cloud / ADK imports.
"""

from __future__ import annotations

from typing import Any

from . import _grounded as g
from .models import (
    CheckStatus,
    Citation,
    InjectedRequirement,
    PrincipleFinding,
    ProjectSubmission,
    Severity,
)
from .principles import PRINCIPLES_BY_ID
from .prompts import _CITATION_RULES, REMEDIATION_SYSTEM, REMEDIATION_USER

#: Statuses that mean a principle is unmet and needs a requirement injected.
_UNMET: frozenset[CheckStatus] = frozenset({CheckStatus.FAIL, CheckStatus.NEEDS_INFO})

_INJECTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "principle_id": {"type": "string"},
                    "requirement_text": {"type": "string"},
                    "rationale": {"type": "string"},
                    "severity": {
                        "type": "string",
                        "enum": ["low", "medium", "high", "critical"],
                    },
                    "used_source_ids": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["principle_id", "requirement_text", "rationale", "severity"],
            },
        }
    },
    "required": ["items"],
}


class RequirementInjectionService:
    """Draft injected requirements for the unmet principles of a validation."""

    def __init__(self, llm: Any, tracer: Any | None = None) -> None:
        self._llm = llm
        self._tracer = tracer

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def inject(
        self,
        submission: ProjectSubmission,
        findings: list[PrincipleFinding],
        kb_citations: list[Citation] | None = None,
    ) -> list[InjectedRequirement]:
        """Produce one InjectedRequirement per unmet principle, in finding order."""
        unmet = [f for f in findings if f.status in _UNMET]
        if not unmet:
            return []

        kb_citations = list(kb_citations or [])
        drafted = self._draft_with_llm(submission, unmet, kb_citations)

        out: list[InjectedRequirement] = []
        for finding in unmet:
            requirement = drafted.get(finding.principle_id)
            if requirement is None:
                requirement = self._fallback_requirement(finding, kb_citations)
            out.append(requirement)
        return out

    # ------------------------------------------------------------------ #
    # LLM drafting (best-effort; falls back to deterministic remediation)
    # ------------------------------------------------------------------ #
    def _draft_with_llm(
        self,
        submission: ProjectSubmission,
        unmet: list[PrincipleFinding],
        kb_citations: list[Citation],
    ) -> dict[str, InjectedRequirement]:
        request = g.build_llm_request(
            system_instruction=REMEDIATION_SYSTEM.format(citation_rules=_CITATION_RULES),
            user_content=REMEDIATION_USER.format(
                project=self._project_summary(submission),
                findings=self._render_findings(unmet),
                context=g.render_citations(kb_citations),
            ),
            model=None,
            response_schema=_INJECTION_SCHEMA,
        )
        try:
            response = self._llm.generate(request)
        except Exception:  # noqa: BLE001 - drafting failure must not drop requirements
            return {}
        g.maybe_record_usage(self._tracer, response)

        parsed = g.parse_structured(response)
        raw_items = parsed.get("items")
        if not isinstance(raw_items, list):
            return {}

        unmet_by_id = {f.principle_id: f for f in unmet}
        available_by_principle = {f.principle_id: list(f.citations) + kb_citations for f in unmet}
        out: dict[str, InjectedRequirement] = {}
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            principle_id = str(raw.get("principle_id") or "").strip()
            finding = unmet_by_id.get(principle_id)
            if finding is None:
                continue
            text = str(raw.get("requirement_text") or "").strip()
            if not text:
                continue
            citations = g.citations_for_source_ids(
                g.as_str_list(raw.get("used_source_ids")),
                available_by_principle.get(principle_id, list(finding.citations)),
            )
            out[principle_id] = InjectedRequirement(
                id=f"inj-{principle_id.lower()}",
                principle_id=principle_id,
                requirement_text=text,
                rationale=str(raw.get("rationale") or finding.evidence).strip(),
                severity=g.coerce_severity(raw.get("severity"), default=finding.severity),
                citations=citations or finding.citations,
            )
        return out

    # ------------------------------------------------------------------ #
    # Deterministic fallback
    # ------------------------------------------------------------------ #
    @staticmethod
    def _fallback_requirement(
        finding: PrincipleFinding, kb_citations: list[Citation]
    ) -> InjectedRequirement:
        principle = PRINCIPLES_BY_ID.get(finding.principle_id)
        text = finding.remediation or (
            f"Address General Principle {finding.principle_id}"
            + (f" ({principle.title})" if principle else "")
            + "."
        )
        rationale = (
            f"{finding.evidence} This requirement operationalises "
            f"{finding.principle_id}" + (f" ({principle.title})" if principle else "") + "."
        )
        citations = tuple(finding.citations) + tuple(kb_citations)
        return InjectedRequirement(
            id=f"inj-{finding.principle_id.lower()}",
            principle_id=finding.principle_id,
            requirement_text=text,
            rationale=rationale,
            severity=finding.severity
            if isinstance(finding.severity, Severity)
            else Severity.MEDIUM,
            citations=citations,
        )

    # ------------------------------------------------------------------ #
    # Prompt rendering helpers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _project_summary(submission: ProjectSubmission) -> str:
        return (
            f"id: {submission.id}\n"
            f"name: {submission.name}\n"
            f"description: {submission.description}\n"
            f"declared_region: {submission.declared_region or '(none)'}\n"
            f"declared_controls: {', '.join(submission.declared_controls) or '(none)'}\n"
            f"uses_pii: {submission.uses_pii}; uses_rag: {submission.uses_rag}; "
            f"uses_fine_tuning: {submission.uses_fine_tuning}; "
            f"has_exit_plan: {submission.has_exit_plan}"
        )

    @staticmethod
    def _render_findings(unmet: list[PrincipleFinding]) -> str:
        lines: list[str] = []
        for f in unmet:
            lines.append(
                f"- {f.principle_id} [{f.status.value}, {f.severity.value}] "
                f"(rule {f.rule_id}): {f.evidence}"
            )
        return "\n".join(lines)
