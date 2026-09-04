"""Serve the governed tool catalog architecture-validator already declares, over MCP 2026-07-28.

The catalog declared three governed tools and served none of them: there was no MCP server
process anywhere in the fleet. This supplies the callables that answer the existing catalog and
declares nothing new. `hex_service_kit.mcpserve.bind` refuses a mismatch in either direction at
start-up, so a tool the service advertises and cannot perform does not start, and neither does a
handler for a tool nobody governed.

MCP stdio verifies no end user, so the caller identity is supplied by the composition root and
recorded as a SERVICE caller, and no tenant is asserted. Every consequential verdict here is
computed by the deterministic domain rather than by a model, so a tool call cannot change what
the principles decide; it can only ask.
"""

from __future__ import annotations

from typing import Any

from hex_service_kit import mcpserve

from ..api import deps
from ..domain.models import ProjectSubmission
from ..domain.principles import all_principles

#: The tools this module answers, as data, so a test can hold it against the catalog without
#: starting a server or importing the MCP SDK.
HANDLER_NAMES: tuple[str, ...] = ("validate_project", "inject_requirements", "list_principles")


def _submission(raw: Any) -> ProjectSubmission:
    """Build the domain submission from the tool's declared object, defensively.

    The schema requires only id, name and requirements, so every other field takes the domain
    default rather than being invented here. `declared_region` stays None when absent, because
    an absent region and a region declared as empty are different claims and the residency rules
    read them differently.
    """
    data = raw if isinstance(raw, dict) else {}
    region = data.get("declared_region")
    return ProjectSubmission(
        id=str(data.get("id", "")),
        name=str(data.get("name", "")),
        description=str(data.get("description", "") or ""),
        requirements=str(data.get("requirements", "") or ""),
        declared_region=str(region) if region is not None else None,
        declared_controls=tuple(str(c) for c in (data.get("declared_controls") or ())),
        uses_pii=bool(data.get("uses_pii", False)),
        uses_rag=bool(data.get("uses_rag", False)),
        uses_fine_tuning=bool(data.get("uses_fine_tuning", False)),
        has_exit_plan=bool(data.get("has_exit_plan", False)),
    )


def build_handlers(actor: str) -> dict[str, mcpserve.Handler]:
    """Bind each declared tool to the domain service that already performs it."""

    def validate_project(**arguments: Any) -> Any:
        return deps.get_validation_service().validate(
            _submission(arguments.get("submission")), actor=actor
        )

    def inject_requirements(**arguments: Any) -> Any:
        submission = _submission(arguments.get("submission"))
        # Injection reads the findings, so the validation runs first rather than the caller
        # being asked to supply findings it has no way to compute.
        report = deps.get_validation_service().validate(submission, actor=actor)
        return deps.get_injection_service().inject(submission, list(report.findings))

    def list_principles(**_: Any) -> Any:
        return list(all_principles())

    return {
        "validate_project": validate_project,
        "inject_requirements": inject_requirements,
        "list_principles": list_principles,
    }


def build_server(actor: str, *, with_audit_tools: bool = True) -> Any:
    """Build the MCP server for architecture-validator's catalog, refusing on any catalog/handler
    mismatch.
    """
    container = deps.get_container()
    return mcpserve.build_server(
        name="architecture-validator",
        version=str(getattr(container.settings, "version", "") or "0.0.1"),
        catalog=container.tool_catalog,
        handlers=build_handlers(actor),
        audit_store=container.audit if with_audit_tools else None,
    )
