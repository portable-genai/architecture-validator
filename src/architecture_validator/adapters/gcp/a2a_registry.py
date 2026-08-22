"""A2A registry adapter — agent discovery and governance for system C3 (A3).

Backs the domain ``AgentRegistryPort`` with an in-process, **A2A v1.0**-style registry of
``AgentCard`` objects. In a standalone deployment C3 registers its own card here and can
serve it at the well-known A2A discovery path; inside the full platform the ``platform``
profile swaps this for a thin client to ``agent-registry``.

A2A discovery contract: an agent publishes its capabilities as an **AgentCard** served at
``/.well-known/agent-card.json``; peers fetch that card to learn the agent's skills,
endpoint URL and version before initiating an A2A task. No external call is required —
this adapter is pure, in-memory governance.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import AgentCard, AgentSkill

AGENT_CARD_PATH = "/.well-known/agent-card.json"

# C3's own skills, surfaced on its AgentCard so peers / the registry can discover the
# three governed capabilities the validator offers.
_C3_SKILLS: tuple[AgentSkill, ...] = (
    AgentSkill(
        id="validate_project",
        name="Validate project at intake",
        description=(
            "Validate a project submission against the 12 General Principles and return a "
            "cited ValidationReport (verdict, per-principle findings, injected requirements)."
        ),
    ),
    AgentSkill(
        id="inject_requirements",
        name="Inject missing requirements",
        description=(
            "Auto-inject the missing non-functional requirements for the unmet principles, "
            "each tied to the principle that mandates it, with rationale and citations."
        ),
    ),
    AgentSkill(
        id="list_principles",
        name="List the General Principles",
        description="Return the 12 General Principles (P-01..P-12) the gate enforces.",
    ),
)


class A2ARegistryAdapter:
    """In-process A2A AgentCard registry: register / get / list, plus card export."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._cards: dict[str, AgentCard] = {}
        self.register(self._self_card())

    # ------------------------------------------------------------------ #
    # AgentRegistryPort
    # ------------------------------------------------------------------ #
    def register(self, card: AgentCard) -> None:
        self._cards[card.name] = card

    def get(self, name: str) -> AgentCard | None:
        return self._cards.get(name)

    def list(self) -> list[AgentCard]:
        return list(self._cards.values())

    # ------------------------------------------------------------------ #
    # A2A discovery helper
    # ------------------------------------------------------------------ #
    def agent_card_dict(self, name: str | None = None) -> dict:
        """Return the ``/.well-known/agent-card.json`` body for ``name`` (defaults to C3)."""
        card = self.get(name) if name else self._cards.get(self._self_name())
        if card is None:
            raise KeyError(f"No AgentCard registered for '{name}'.")
        return {
            "name": card.name,
            "description": card.description,
            "url": card.url,
            "version": card.version,
            "provider": card.provider,
            "skills": [
                {"id": s.id, "name": s.name, "description": s.description} for s in card.skills
            ],
        }

    # ------------------------------------------------------------------ #
    # C3's own card
    # ------------------------------------------------------------------ #
    def _self_name(self) -> str:
        return self._settings.agent_engine.display_name or "architecture-validator"

    def _self_card(self) -> AgentCard:
        return AgentCard(
            name=self._self_name(),
            description=(
                "C3 Architecture & Requirements Validator — policy-as-code intake gate over "
                "the 12 General Principles, with auto-injected non-functional requirements."
            ),
            url=f"https://architecture-validator.{self._settings.region}.example/a2a",
            version="1.0.0",
            skills=_C3_SKILLS,
            provider="architecture-validator",
        )
