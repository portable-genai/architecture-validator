"""Remote-platform control-mapping adapter — HTTP client to the compliance assistant.

Consumes control-coverage evidence relevant to a project scope from the **compliance-advisory
compliance assistant's control-mapping module** (served on the same port as the assistant's other
routes). C3 uses this best-effort: the :class:`ValidationService` calls ``coverage`` inside a
try/except, so an outage degrades a finding's context rather than failing the validation. The
adapter POSTs to the service's ``/evidence-pack`` endpoint and maps the returned evidence onto
domain :class:`Citation` objects. The base URL is read from ``RSK_CONTROL_MAPPING_URL`` with a
localhost default of the compliance assistant's port (8080).
"""

from __future__ import annotations

import httpx

from ...domain.errors import ValidatorError
from ...domain.models import Citation, Jurisdiction, Regulator
from ...envread import setting_or_default
from . import _s2s

_DEFAULT_URL = "http://localhost:8080"
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


class RemoteControlMappingError(ValidatorError):
    """Raised when the C2 control-mapping service returns an unexpected status."""


class RemoteControlMappingAdapter:
    """HTTP client for the C2 ``/evidence-pack`` endpoint."""

    def __init__(self, settings: object) -> None:
        self._settings = settings
        self._base_url = _s2s.validate_base_url(
            setting_or_default("RSK_CONTROL_MAPPING_URL", _DEFAULT_URL),
            service="control-mapping toolkit",
        )

    def coverage(self, scope: str) -> list[Citation]:
        """Return C2 control-coverage citations for ``scope`` (best-effort)."""
        url = f"{self._base_url}/evidence-pack"
        payload = {"scope": scope, "actor": "architecture-validator"}
        try:
            response = httpx.post(url, json=payload, timeout=_TIMEOUT, headers=_s2s.headers())
        except httpx.HTTPError as exc:
            raise RemoteControlMappingError(f"C2 request to {url} failed: {exc}") from exc
        if response.status_code // 100 != 2:
            raise RemoteControlMappingError(
                f"C2 {url} returned {response.status_code}: {response.text[:500]}"
            )
        body = response.json() or {}
        items = body.get("citations") or body.get("evidence") or []
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
