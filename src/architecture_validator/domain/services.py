"""Aggregator re-exporting the C3 orchestration services.

The services live one-per-module (``validation_service``, ``injection_service``) so each
stays focused. This module is the single import surface the wiring layers
(``api.deps``, ``agent.tools``, ``cli``) use, so they never need to know which module a
service lives in.
"""

from __future__ import annotations

from .injection_service import RequirementInjectionService
from .validation_service import ValidationService

__all__ = [
    "ValidationService",
    "RequirementInjectionService",
]
