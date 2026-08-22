"""Local control-mapping adapter (ControlMappingClientPort) — in-process C2 signal.

The ``local`` profile's stand-in for the **C2** control-mapping client. Under ``local``
this platform client uses an in-process implementation rather than HTTP to the sibling
C2 service (a laptop runs one app, not the whole platform). C2 coverage is a best-effort
context signal for the validator, so by default this returns no extra citations (the
canned set is empty), exactly mirroring the optional, degrade-gracefully behaviour of the
managed path. SDK-free and unconditional.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import Citation


class LocalControlMappingAdapter:
    """In-process C2 control-mapping client (canned, best-effort)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._citations: list[Citation] = []
        self.calls: list[str] = []

    def coverage(self, scope: str) -> list[Citation]:
        """Return canned C2 control-coverage citations for ``scope`` (best-effort)."""
        self.calls.append(scope)
        return list(self._citations)
