"""Remote-platform residency adapter — HTTP client to the residency service.

Consumes the **residency scanner** for the residency findings relevant to a project. The
validator uses this best-effort: the :class:`ValidationService` calls ``findings`` inside
a try/except, so a residency-service outage never aborts a validation. The adapter POSTs
to the service's ``/scan`` endpoint and maps the returned findings onto domain
:class:`Citation` objects. The base URL is read from ``RSK_RESIDENCY_URL`` with a
localhost default (port 8088).
"""

from __future__ import annotations

import httpx

from ...domain.errors import ValidatorError
from ...domain.models import Citation, Jurisdiction, Regulator
from ...envread import setting_or_default
from . import _s2s

_DEFAULT_URL = "http://localhost:8088"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class RemoteResidencyError(ValidatorError):
    """Raised when the residency service returns an unexpected status."""


class RemoteResidencyAdapter:
    """HTTP client for the residency service's ``/scan`` endpoint."""

    def __init__(self, settings: object) -> None:
        self._settings = settings
        self._base_url = _s2s.validate_base_url(
            setting_or_default("RSK_RESIDENCY_URL", _DEFAULT_URL), service="residency validator"
        )

    def findings(self, scope: str) -> list[Citation]:
        """Return residency-scan citations for ``scope`` (best-effort)."""
        url = f"{self._base_url}/scan"
        payload = {"scope": scope, "actor": "architecture-validator"}
        try:
            response = httpx.post(url, json=payload, timeout=_TIMEOUT, headers=_s2s.headers())
        except httpx.HTTPError as exc:
            raise RemoteResidencyError(f"Residency request to {url} failed: {exc}") from exc
        if response.status_code // 100 != 2:
            raise RemoteResidencyError(
                f"Residency {url} returned {response.status_code}: {response.text[:500]}"
            )
        body = response.json() or {}
        items = body.get("citations") or body.get("findings") or []
        return [_parse_citation(c) for c in items]


def _parse_citation(body: dict) -> Citation:
    try:
        regulator = Regulator(str(body.get("regulator", "CROSS")).upper())
    except ValueError:
        regulator = Regulator.CROSS
    try:
        jurisdiction = Jurisdiction(str(body.get("jurisdiction", "GLOBAL")).upper())
    except ValueError:
        jurisdiction = Jurisdiction.GLOBAL
    page = body.get("page")
    return Citation(
        source_id=str(body.get("source_id", "")),
        regulator=regulator,
        jurisdiction=jurisdiction,
        title=str(body.get("title", "")),
        url=str(body.get("url", "")),
        version=str(body.get("version", "unknown")),
        page=int(page) if isinstance(page, int) else None,
        snippet=str(body.get("snippet", "")),
    )
