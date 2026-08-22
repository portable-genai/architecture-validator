"""On-prem placeholder for ``KnowledgeBasePort`` — the on-premise migration target.

One of the reversibility (P-02, P-12) migration placeholders: in the managed profile
this port binds to the File Search adapter; switching ``profile`` to ``onprem`` rebinds
it here. The adapter constructs cleanly with **no external dependencies** and
structurally satisfies the same Protocol as the managed adapter, so the contract tests
prove interface parity. Porting C3 on-premise is *only* a matter of filling these bodies
in — the domain orchestration and service callers do not change.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import Citation

_MESSAGE = (
    "On-prem KnowledgeBasePort adapter is a migration placeholder; implement against your "
    "on-premise platform. Core domain logic is unchanged."
)


class OnPremKnowledgeBaseAdapter:
    """Placeholder knowledge-base adapter for the on-prem migration profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def retrieve(self, query: str, top_k: int = 8) -> list[Citation]:
        raise NotImplementedError(_MESSAGE)
