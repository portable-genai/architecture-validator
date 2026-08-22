"""Ports — the abstract interfaces (the hexagon boundary).

Every port is a ``typing.Protocol`` so adapters need only structural conformance and
contract tests can verify any adapter (GCP, remote-platform, or on-prem placeholder)
satisfies the same contract.
"""

from .generation import LLMPort
from .governance import AgentRegistryPort, ToolCatalogPort
from .identity import IdentityPort
from .knowledge import (
    ControlMappingClientPort,
    KnowledgeBasePort,
    ResidencyClientPort,
)
from .observability import (
    AuditSinkPort,
    EvaluationGatePort,
    ObservabilityTracerPort,
    TokenUsage,
)
from .policy import PolicyEnginePort
from .review_router import ReviewRouterPort
from .scanner import IaCScannerPort

__all__ = [
    "PolicyEnginePort",
    "KnowledgeBasePort",
    "ControlMappingClientPort",
    "ResidencyClientPort",
    "IaCScannerPort",
    "LLMPort",
    "AuditSinkPort",
    "ObservabilityTracerPort",
    "TokenUsage",
    "EvaluationGatePort",
    "AgentRegistryPort",
    "ToolCatalogPort",
    "IdentityPort",
    "ReviewRouterPort",
]
