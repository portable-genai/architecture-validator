"""Knowledge & sibling-service ports — governed RAG plus control-mapping / residency input.

* ``KnowledgeBasePort`` — governed retrieval (A2 Enterprise KB) for the regulatory
  context that grounds a finding. Primary GCP adapter: File Search on the Gemini
  Enterprise Agent Platform; the **platform** adapter is an HTTP client to C1 ``/ask``
  and/or the KB service.
* ``ControlMappingClientPort`` — consume **C2** control-mapping evidence packs
  (best-effort; failures degrade to NEEDS_INFO-grade context).
* ``ResidencyClientPort`` — consume **residency scan** findings (best-effort).

Each returns ``Citation`` provenance so findings and injected requirements stay cited.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import Citation


@runtime_checkable
class KnowledgeBasePort(Protocol):
    def retrieve(self, query: str, top_k: int = 8) -> list[Citation]:
        """Return governed-KB citations relevant to ``query`` (reg context for findings)."""
        ...


@runtime_checkable
class ControlMappingClientPort(Protocol):
    def coverage(self, scope: str) -> list[Citation]:
        """Consume C2: control-coverage evidence for ``scope`` (best-effort)."""
        ...


@runtime_checkable
class ResidencyClientPort(Protocol):
    def findings(self, scope: str) -> list[Citation]:
        """Consume the residency scan findings for ``scope`` (best-effort)."""
        ...
