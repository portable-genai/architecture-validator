"""Observability ports -- the A5 (audit/trace) and A4 (eval gate) concerns.

Primary GCP adapters: **Cloud Logging locked WORM bucket** for immutable audit,
**Cloud Trace via OpenTelemetry** for validation-pipeline traces (message content
capture OFF), and the **Gen AI evaluation service** for the promotion gate
(principle accuracy, injection recall, citation accuracy, safety).

Two of the three Protocols here are re-exported, not redeclared.
``ObservabilityTracerPort`` and ``TokenUsage`` come from ``hex-service-kit`` and
``EvaluationGatePort`` from ``agent-eval-kit``, for the same reason ``IdentityPort`` does:
sixteen repositories each hand-copied this module and the copies had already drifted. One
had dropped the evaluation port entirely, two had dropped its ``gate`` method -- the half
that can actually refuse a promotion -- and one returned ``str`` from an audit ``record``
that returns ``None`` everywhere else. The split across the two commons packages follows
where the types already live: the tracer beside the ``TokenUsage`` it reports, the gate
beside the ``EvalReport`` it returns. Both are typing-only imports, so the offline profile
pays nothing: no OpenTelemetry, no HTTP client, no cloud SDK.

``AuditSinkPort`` STAYS declared here. It is typed in this repo's own vocabulary (an
:class:`~architecture_validator.domain.models.AuditEvent` carrying a validation verdict), so it is
not a shared shape and there is nothing for it to drift against.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from agent_eval_kit import EvaluationGatePort
from hex_service_kit.observability import ObservabilityTracerPort, TokenUsage

from ..domain.models import AuditEvent


@runtime_checkable
class AuditSinkPort(Protocol):
    def record(self, event: AuditEvent) -> None:
        """Write an immutable audit record of a validation verdict (WORM)."""
        ...


__all__ = [
    "AuditSinkPort",
    "EvaluationGatePort",
    "ObservabilityTracerPort",
    "TokenUsage",
]
