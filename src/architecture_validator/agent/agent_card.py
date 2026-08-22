"""A2A AgentCard for the C3 Architecture & Requirements Validator (A3 Registry).

This builds the validator's discovery card — the same minimal A2A shape the
``agent-registry`` service stores and serves (SPEC §6). It is published at
``/.well-known/agent-card.json``; :func:`agent_card_document` returns the JSON-safe body
the API layer serves there.

The card advertises C3's three skills (validate_project, inject_requirements,
list_principles), mirroring the ADK FunctionTools so a peer agent or the registry sees one
consistent capability surface.

This module is pure (domain models only) and imports without ADK or any Google Cloud SDK
installed (SPEC §4).
"""

from __future__ import annotations

from typing import Any

from ..config import Settings
from ..domain.models import AgentCard, AgentSkill

# Skill ids match the FunctionTool callables in ``agent.tools`` so the card and the tool
# surface stay in lockstep.
SKILLS: tuple[AgentSkill, ...] = (
    AgentSkill(
        id="validate_project",
        name="Validate project at intake",
        description=(
            "Validate a project submission against the 12 General Principles and return a "
            "cited ValidationReport: verdict (PASS only if no principle FAILs), per-principle "
            "findings, and the auto-injected non-functional requirements. Flagged for human "
            "review on any FAIL (maker-checker, P-06)."
        ),
    ),
    AgentSkill(
        id="inject_requirements",
        name="Inject missing requirements",
        description=(
            "Produce the missing non-functional requirements for the unmet principles, each "
            "tied to the principle that mandates it, with rationale, severity and citations."
        ),
    ),
    AgentSkill(
        id="list_principles",
        name="List the General Principles",
        description="Return the 12 General Principles (P-01..P-12) the intake gate enforces.",
    ),
    # Residency-scan skills. This validator now BOTH validates a project
    # at intake AND scans infrastructure config for data-residency / sovereignty violations.
    AgentSkill(
        id="scan_iac",
        name="Scan IaC for residency violations",
        description=(
            "Scan a Terraform plan / directory for region and residency violations and "
            "return a PASS/FAIL verdict with cited findings and remediation. Exits "
            "non-zero on FAIL so it gates a CI pipeline."
        ),
    ),
    AgentSkill(
        id="scan_project",
        name="Scan a live project for residency violations",
        description=(
            "Scan a live GCP project / folder / org scope via Cloud Asset Inventory + "
            "Security Command Center for residency violations."
        ),
    ),
    AgentSkill(
        id="explain_violation",
        name="Explain a residency violation",
        description=(
            "Explain why a finding fails residency policy (P-01 / P-03) and how to "
            "remediate it, for an engineer reading a failed gate."
        ),
    ),
)

_DESCRIPTION = (
    "Policy-as-code intake gate for an APAC bank's agentic-AI platform. Validates a "
    "project's requirements/design against the 12 General Principles, cross-checks the "
    "regulatory knowledge base, and auto-injects the missing non-functional requirements "
    "so a project cannot start non-compliant (rule R6). Also scans infrastructure config "
    "(Terraform plan / .tf, or a live GCP project) for data-residency / sovereignty "
    "violations and gates a CI pipeline. Built ports-and-adapters on "
    "the Gemini Enterprise Agent Platform (OPA policy engine, File Search grounding)."
)


def build_agent_card(settings: Settings) -> AgentCard:
    """Construct the A2A :class:`AgentCard` for this validator."""
    return AgentCard(
        name="architecture-validator",
        description=_DESCRIPTION,
        url=_resolve_url(settings),
        version="0.1.0",
        skills=SKILLS,
        provider="architecture-validator",
    )


def agent_card_document(settings: Settings) -> dict[str, Any]:
    """Return the JSON-safe body to serve at ``/.well-known/agent-card.json``."""
    from ..domain.serialization import to_jsonable

    return to_jsonable(build_agent_card(settings))


def _resolve_url(settings: Settings) -> str:
    """Best-effort public URL for the card, region-pinned to asia-southeast1."""
    resource = settings.agent_engine.resource_name
    if resource:
        return f"https://aiplatform.googleapis.com/v1/{resource}"
    return "https://architecture-validator.rsk.internal/a2a"
