"""Root ADK agent for the C3 Architecture & Requirements Validator, on Agent Runtime.

This is the agent the Gemini Enterprise Agent Platform **Agent Runtime** (ex-Agent
Engine) hosts. It wires together:

* the three domain-service :class:`FunctionTool` wrappers (``agent.tools``),
* the audit + span-privacy **callbacks** (``agent.callbacks``), and
* the reasoning model ``settings.models.reasoning`` (``gemini-3.5-flash``) at
  ``thinking=high`` (SPEC §3).

C3 needs no public-web grounding (it validates project metadata against a bundled
ruleset), so there is no ``google_search`` sub-agent: the one-built-in-tool-per-agent rule
is satisfied trivially because the root agent carries only FunctionTools.

ADK convention is honoured two ways: the module exposes a ``root_agent`` attribute (what
ADK / ``adk web`` / Agent Runtime discover) **and** a ``build_root_agent(settings)`` factory.

Import safety (SPEC §4)
-----------------------
``google.adk`` is heavy and GCP-only. All ADK imports are quarantined inside
:func:`build_root_agent`, and the module-level ``root_agent`` is built lazily via
:class:`_LazyRootAgent` so merely importing this module never requires ADK.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..config import Settings

if TYPE_CHECKING:  # pragma: no cover - typing only
    from google.adk.agents import LlmAgent

ROOT_AGENT_NAME = "architecture_validator"

_ROOT_INSTRUCTION = (
    "You are C3, the Architecture & Requirements Validator for an APAC bank's agentic-AI "
    "platform. You are the policy-as-code gate at project intake (rule R6): you validate a "
    "project submission against the 12 General Principles (P-01..P-12) and inject the "
    "missing non-functional requirements.\n\n"
    "Routing:\n"
    "- 'Validate this project' / a submission -> call validate_project.\n"
    "- 'What requirements are we missing?' -> call inject_requirements.\n"
    "- 'What are the principles?' -> call list_principles.\n\n"
    "Rules:\n"
    "- You never decide a verdict yourself; the policy engine decides PASS/FAIL/NEEDS_INFO. "
    "Report exactly what the tools return.\n"
    "- Every finding and injected requirement carries a citation to the principle (and the "
    "regulatory source where relevant). Never invent a principle id or a citation.\n"
    "- A project passes intake only if no principle FAILs. State clearly when a result "
    "requires human review (maker-checker)."
)


def build_root_agent(settings: Settings | None = None) -> LlmAgent:
    """Construct the root ADK ``LlmAgent`` for the validator.

    Wires the three FunctionTools and the audit/span-privacy callbacks built from the DI
    container. The reasoning model runs at ``thinking=high`` (SPEC §3). All ADK imports
    are local to this function (SPEC §4).
    """
    settings = settings or Settings.load()

    from google.adk.agents import LlmAgent
    from google.genai import types

    from ..config import build_container
    from .callbacks import build_callbacks, configure_span_privacy
    from .tools import build_function_tools

    # PII / submission text must never land in trace spans (SPEC §3); set before anything.
    configure_span_privacy()

    container = build_container(settings)
    callbacks = build_callbacks(container)

    tools: list[Any] = list(build_function_tools())

    generate_content_config = types.GenerateContentConfig(
        temperature=0.2,
        thinking_config=types.ThinkingConfig(thinking_budget=-1),
    )

    return LlmAgent(
        name=ROOT_AGENT_NAME,
        model=settings.models.reasoning,
        description=(
            "Policy-as-code intake validator: validates a project against the 12 General "
            "Principles and injects the missing non-functional requirements, with citations."
        ),
        instruction=_ROOT_INSTRUCTION,
        tools=tools,
        generate_content_config=generate_content_config,
        after_agent_callback=callbacks["after_agent_callback"],
    )


def to_a2a_app(settings: Settings | None = None) -> Any:
    """Expose the root agent as an A2A app (serves ``/.well-known/agent-card.json``).

    Thin wrapper over ADK's ``to_a2a`` so peers can discover and call the validator over
    A2A v1.0 (SPEC §3/§6). ADK is imported lazily (SPEC §4).
    """
    from google.adk.a2a.utils.agent_to_a2a import to_a2a

    return to_a2a(build_root_agent(settings))


class _LazyRootAgent:
    """Lazy proxy so ``import root_agent`` never pulls in ADK.

    ADK discovers a module-level ``root_agent``. We expose that name without forcing ADK
    to be importable at module import time (on-prem/test profile, SPEC §4). The real
    ``LlmAgent`` is built on first attribute access and cached.
    """

    __slots__ = ("_agent",)

    def __init__(self) -> None:
        self._agent: LlmAgent | None = None

    def _resolve(self) -> LlmAgent:
        if self._agent is None:
            self._agent = build_root_agent()
        return self._agent

    def __getattr__(self, name: str) -> Any:
        return getattr(self._resolve(), name)

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        state = "unbuilt" if self._agent is None else "built"
        return f"<LazyRootAgent {ROOT_AGENT_NAME} ({state})>"


# ADK convention: a module-level ``root_agent`` the runtime discovers. Lazy so importing
# this module is safe without ADK installed (SPEC §4).
root_agent = _LazyRootAgent()
