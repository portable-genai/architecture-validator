"""Model-boundary callbacks: span-privacy + an audit record at agent turn end.

C3 validates project metadata, not customer PII, so (unlike C1) there is no
redaction/guardrail callback at the model boundary. What remains is the two
defense-in-depth concerns C3 still owes (P-07, audited-everything):

  1. **span privacy** — ADK can attach message content to trace spans, which would put
     submission text into Cloud Trace; :func:`configure_span_privacy` sets
     ``ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS=false`` (idempotent), and the Cloud Trace
     adapter additionally disables content capture at the exporter (SPEC §3); and
  2. **audit** — an :class:`AuditEvent` is written at agent turn end via the
     :class:`AuditSinkPort`, summarising the validation the agent ran.

ADK imports are done lazily inside the factory so this module imports without ADK
installed (SPEC §4). Callback signatures follow ADK 2.x:

* ``after_agent_callback(callback_context) -> types.Content | None``
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from ..config import Container
from ..domain.models import AuditEvent, Decision, utcnow

if TYPE_CHECKING:  # pragma: no cover - typing only
    from google.adk.agents.callback_context import CallbackContext

# Env var ADK reads to decide whether to copy message content into trace spans.
SPAN_CONTENT_ENV = "ADK_CAPTURE_MESSAGE_CONTENT_IN_SPANS"


def configure_span_privacy() -> None:
    """Ensure message content is never captured into trace spans (SPEC §3).

    Idempotent and non-destructive: only sets the flag if the operator has not already
    pinned it. Pairs with the Cloud Trace adapter's exporter-level content-capture-off.
    """
    os.environ.setdefault(SPAN_CONTENT_ENV, "false")


def _get_state(callback_context: Any, key: str, default: Any = None) -> Any:
    state = getattr(callback_context, "state", None)
    if state is None:
        return default
    try:
        return state.get(key, default)
    except Exception:  # pragma: no cover - extremely defensive
        return default


def build_callbacks(container: Container) -> dict[str, Callable[..., Any]]:
    """Build the after-agent audit callback bound to ``container``.

    Returns a dict with key ``after_agent_callback`` ready to attach to an ADK
    ``LlmAgent``. ``google.adk`` is imported lazily here so the module is import-safe
    without ADK installed (SPEC §4).
    """

    def after_agent_callback(callback_context: CallbackContext) -> Any:
        """Write one WORM audit record for the agent turn (P-07)."""
        event = AuditEvent(
            action="validate",
            actor=_actor(callback_context),
            decision=Decision.ESCALATED,
            summary_prompt=str(_get_state(callback_context, "submission_id", "")),
            summary_response="agent validation turn",
            resource="architecture-validator",
            trace_id=_trace_id(callback_context),
            timestamp=utcnow(),
            metadata={"layer": "model-boundary"},
        )
        try:
            container.audit.record(event)
        except Exception:  # noqa: BLE001 - audit must not crash the turn
            return None
        return None

    return {"after_agent_callback": after_agent_callback}


def _actor(callback_context: Any) -> str:
    """Resolve the authenticated identity for the audit row, with a safe default."""
    actor = _get_state(callback_context, "actor", None)
    if actor:
        return str(actor)
    user_id = getattr(callback_context, "user_id", None)
    return str(user_id) if user_id else "architecture-validator-agent"


def _trace_id(callback_context: Any) -> str | None:
    """Pull the current trace id from the context if ADK exposes one."""
    invocation_id = getattr(callback_context, "invocation_id", None)
    return str(invocation_id) if invocation_id else None
