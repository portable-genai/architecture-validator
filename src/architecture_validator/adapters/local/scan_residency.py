"""In-process residency adapter (ResidencyClientPort): the same-service seam.

The residency scan runs inside this service, so C3's ``residency`` port needs no HTTP hop to a
sibling: this adapter satisfies ``ResidencyClientPort.findings(scope)`` by running the in-process
:class:`~architecture_validator.domain.residency.scan_service.ResidencyScanService` and mapping the
scan result's violations onto their :class:`Citation` provenance.

The split-deployment HTTP client (``platform.remote_residency:RemoteResidencyAdapter``) is an
optional binding for a deployment that runs the scanner as a separate service.

Best-effort by contract: ``ValidationService`` calls ``findings`` inside a try/except, and
this adapter itself swallows any scan failure and returns ``[]`` so a residency signal
never aborts a validation. Import-safe and SDK-free (the scan service resolves its ports
lazily through the container).
"""

from __future__ import annotations

from typing import Any

from ...config import Settings, build_container
from ...domain.models import Citation


class LocalScanResidencyAdapter:
    """In-process residency client: runs the residency scan service and returns citations."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._service: Any | None = None
        self.calls: list[str] = []

    def _scan_service(self) -> Any:
        """Lazily assemble the residency scan service over an own container (SDK-free local)."""
        if self._service is None:
            from ...domain.residency.detector import ViolationDetector
            from ...domain.residency.scan_service import ResidencyScanService

            container = build_container(self._settings)
            detector = ViolationDetector(self._settings.build_residency_policy())
            self._service = ResidencyScanService(
                scanner=container.scanner,
                detector=detector,
                llm=container.llm,
                tracer=container.tracer,
                audit=container.audit,
                review_router=container.review_router,
            )
        return self._service

    def findings(self, scope: str) -> list[Citation]:
        """Return residency-scan citations for ``scope`` (best-effort; ``[]`` on any failure).

        ``scope`` is C3's submission id/name. If it names a plan/.tf path or a
        ``projects/...`` scope the scan grades it; anything else (or any error) degrades to
        an empty citation list, matching the best-effort contract of the port.
        """
        self.calls.append(scope)
        try:
            action = (
                "scan_project"
                if scope.strip().startswith(("projects/", "folders/", "organizations/"))
                else "scan_iac"
            )
            scan = self._scan_service().scan_target(
                scope, actor="architecture-validator", action=action
            )
        except Exception:  # noqa: BLE001 - best-effort residency signal, never fatal to C3
            return []
        citations = {(c.source_id, c.page): c for v in scan.violations for c in v.citations}
        return list(citations.values())
