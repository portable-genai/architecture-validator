"""PolicyEnginePort — evaluate the General-Principles ruleset over a submission.

Primary GCP adapter: an **OPA (Open Policy Agent) REST service** on Cloud Run that
evaluates the bundled rego policies against the submission + principle ruleset (lazy
``httpx``). The bundled default and the test fake instead use the deterministic
in-process evaluator in :mod:`architecture_validator.domain.principles_eval`, so the same rule
logic backs both the managed and the credential-free paths.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.models import Principle, PrincipleFinding, ProjectSubmission


@runtime_checkable
class PolicyEnginePort(Protocol):
    def evaluate(
        self, submission: ProjectSubmission, principles: list[Principle]
    ) -> list[PrincipleFinding]:
        """Evaluate ``submission`` against ``principles`` and return one finding each."""
        ...
