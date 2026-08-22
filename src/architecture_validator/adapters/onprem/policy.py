"""On-prem placeholder for ``PolicyEnginePort`` — the on-premise migration target.

This is one of the migration placeholders that make reversibility (P-02, P-12) a
*demonstrable* property rather than a claim. In the managed profile this port is bound
to the OPA policy adapter; switching ``profile`` to ``onprem`` rebinds it here. The
adapter constructs cleanly with **no external dependencies** and structurally satisfies
the same Protocol as the managed adapter, so the contract tests prove interface parity.

``evaluate`` deliberately raises rather than waving a submission through unevaluated: an
unimplemented intake gate must never silently pass a project, so porting on-premise
*must* supply a real policy backend (e.g. a self-hosted OPA). Note the deterministic
rule logic itself lives in :mod:`architecture_validator.domain.principles_eval`, so an on-prem
implementation can reuse it without changing the domain.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.models import Principle, PrincipleFinding, ProjectSubmission

_MESSAGE = (
    "On-prem PolicyEnginePort adapter is a migration placeholder; implement against your "
    "on-premise platform. Core domain logic is unchanged."
)


class OnPremPolicyAdapter:
    """Placeholder policy-engine adapter for the on-prem migration profile."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def evaluate(
        self, submission: ProjectSubmission, principles: list[Principle]
    ) -> list[PrincipleFinding]:
        raise NotImplementedError(_MESSAGE)
