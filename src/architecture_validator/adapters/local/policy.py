"""Local policy-engine adapter (PolicyEnginePort) — the in-process principle evaluator.

The ``local`` profile's stand-in for the **OPA REST service**: it evaluates the 12
General Principles with the deterministic in-process evaluator
(:mod:`architecture_validator.domain.principles_eval`) instead of POSTing to OPA. That evaluator
is the single source of truth the rego bundle is kept in lockstep with, so the local and
managed verdicts agree by construction. SDK-free, deterministic and credential-free; the
whole intake gate therefore runs offline with no Google Cloud and no policy service.

``tests/conftest.py``'s schema-free ``FakePolicyEngine`` is a thin recording subclass of
this adapter, not a second implementation, so the rule wiring lives once under
``adapters/local`` and drives both the offline tests and the CLI.
"""

from __future__ import annotations

from ...config import Settings
from ...domain import principles_eval
from ...domain.models import Principle, PrincipleFinding, ProjectSubmission


class LocalPolicyEngineAdapter:
    """Evaluate the principle ruleset deterministically (shares the domain evaluator)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        # Expose the submissions evaluated so a unit test can assert the engine was hit.
        self.calls: list[ProjectSubmission] = []

    def evaluate(
        self, submission: ProjectSubmission, principles: list[Principle]
    ) -> list[PrincipleFinding]:
        """Return one deterministic finding per principle for ``submission``."""
        self.calls.append(submission)
        return principles_eval.evaluate_all(
            submission, allowed_regions=self._settings.policy.allowed_regions
        )
