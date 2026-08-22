"""On-prem placeholder for ``ControlMappingClientPort`` (consume C2).

One of the reversibility (P-02, P-12) migration placeholders. C2 control-mapping
coverage is a best-effort signal for the validator, so on-prem this could be wired to an
internal control-coverage service. Until then the placeholder raises from ``coverage``:
the :class:`ValidationService` calls it best-effort and swallows the error, degrading the
finding's context to NEEDS_INFO-grade rather than failing the validation. The adapter
constructs cleanly with no external dependencies and structurally satisfies the Protocol.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import Citation

_MESSAGE = (
    "On-prem ControlMappingClientPort adapter is a migration placeholder; implement against "
    "your on-premise platform. Core domain logic is unchanged."
)


class OnPremControlMappingAdapter:
    """Placeholder C2 control-mapping client for the on-prem migration profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def coverage(self, scope: str) -> list[Citation]:
        raise NotImplementedError(_MESSAGE)
