"""On-prem placeholder for ``IaCScannerPort`` — the on-prem migration target.

One of the reversibility (P-02, P-12) migration placeholders: in the managed profile this
port binds to the Cloud Asset Inventory + Security Command Center adapter; switching
``profile`` to ``onprem`` rebinds it here. The adapter constructs cleanly with **no
external dependencies** and structurally satisfies the same Protocol as the managed
adapter, so the contract tests prove interface parity. Porting the live scan on-premise is
only a matter of filling this body in; the file-based CI-gate scan is unaffected.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.residency.models import ResourceConfig

_MESSAGE = (
    "On-prem IaCScannerPort adapter is a migration placeholder; implement against your "
    "on-premise asset inventory. Core domain logic is unchanged."
)


class OnPremScannerAdapter:
    """Placeholder live-scan adapter for the on-prem profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def scan(self, target: str) -> list[ResourceConfig]:
        raise NotImplementedError(_MESSAGE)
