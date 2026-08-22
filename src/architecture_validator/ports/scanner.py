"""IaCScannerPort — a live source of infrastructure resource configuration.

Primary GCP adapter: **Cloud Asset Inventory** (the authoritative inventory of deployed
resources) combined with **Security Command Center** findings, pinned to a single
in-country region. Given a scope (``projects/...`` | ``folders/...`` |
``organizations/...``) it returns the deployed resources normalised as
:class:`ResourceConfig`, which the deterministic detector grades for residency.

The CI-gate path does NOT use this port: a local Terraform plan / ``.tf`` directory is
parsed by ``pipelines.terraform`` (pure stdlib). This port is the *live* scan path
(``architecture-validator scan --project <id>``). On-prem migration swaps the adapter for a
placeholder with no change to callers.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.residency.models import ResourceConfig


@runtime_checkable
class IaCScannerPort(Protocol):
    def scan(self, target: str) -> list[ResourceConfig]:
        """Return the deployed resources under ``target`` (a project / folder / org scope)."""
        ...
