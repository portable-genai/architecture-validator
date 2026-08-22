"""MCP tool catalog adapter — the governed tool surface for system C3.

Backs the domain ``ToolCatalogPort`` by exposing C3's governed, least-privilege
capabilities as ``ToolSpec`` objects: ``validate_project``, ``inject_requirements`` and
``list_principles``. These are the tools the validator (or a peer agent) may invoke, each
with an explicit JSON input schema so access is scoped and auditable (P-07, least privilege).

Interop: the catalog speaks **MCP 2025-11-25**. In an ADK deployment these specs are
surfaced through an ``McpToolset`` fronting the domain services; here the adapter only
*declares* the governed catalog. The ``mcp`` package is imported lazily and only when an
actual MCP wire object is requested.
"""

from __future__ import annotations

from typing import Any

from ...config import Settings
from ...domain.models import ToolSpec

MCP_PROTOCOL_VERSION = "2025-11-25"

_SUBMISSION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "id": {"type": "string"},
        "name": {"type": "string"},
        "description": {"type": "string"},
        "requirements": {"type": "string"},
        "declared_region": {"type": "string"},
        "declared_controls": {"type": "array", "items": {"type": "string"}},
        "uses_pii": {"type": "boolean"},
        "uses_rag": {"type": "boolean"},
        "uses_fine_tuning": {"type": "boolean"},
        "has_exit_plan": {"type": "boolean"},
    },
    "required": ["id", "name", "requirements"],
    "additionalProperties": True,
}


def _build_catalog() -> dict[str, ToolSpec]:
    """Declare C3's governed tools with explicit, least-privilege input schemas."""
    return {
        "validate_project": ToolSpec(
            name="validate_project",
            description=(
                "Validate a project submission against the 12 General Principles and "
                "return a cited ValidationReport. Output requires human review when any "
                "principle FAILs (maker-checker, P-06)."
            ),
            input_schema={
                "type": "object",
                "properties": {"submission": _SUBMISSION_SCHEMA},
                "required": ["submission"],
                "additionalProperties": False,
            },
        ),
        "inject_requirements": ToolSpec(
            name="inject_requirements",
            description=(
                "Given a submission and its findings, return the missing non-functional "
                "requirements to inject at intake, each tied to its principle and cited."
            ),
            input_schema={
                "type": "object",
                "properties": {"submission": _SUBMISSION_SCHEMA},
                "required": ["submission"],
                "additionalProperties": False,
            },
        ),
        "list_principles": ToolSpec(
            name="list_principles",
            description="Return the 12 General Principles (P-01..P-12) the gate enforces.",
            input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        ),
    }


class McpToolCatalogAdapter:
    """Declarative MCP 2025-11-25 catalog of C3's governed tools."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._catalog: dict[str, ToolSpec] = _build_catalog()

    # ------------------------------------------------------------------ #
    # ToolCatalogPort
    # ------------------------------------------------------------------ #
    def list_tools(self) -> list[ToolSpec]:
        return list(self._catalog.values())

    def get_tool(self, name: str) -> ToolSpec | None:
        return self._catalog.get(name)

    # ------------------------------------------------------------------ #
    # MCP wire helpers (lazy ``mcp`` import — only when actually used)
    # ------------------------------------------------------------------ #
    def as_mcp_tools(self) -> list[Any]:
        """Render the catalog as MCP ``Tool`` objects (MCP 2025-11-25 schema)."""
        from mcp import types as mcp_types  # lazy

        # verify: https://modelcontextprotocol.io/specification/2025-11-25
        return [
            mcp_types.Tool(
                name=spec.name,
                description=spec.description,
                inputSchema=spec.input_schema,
            )
            for spec in self._catalog.values()
        ]
