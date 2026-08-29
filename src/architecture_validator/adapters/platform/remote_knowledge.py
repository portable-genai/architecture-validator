"""Remote-platform knowledge-base adapter — HTTP client to C1 / the KB service (A2).

In the full platform deployment, regulatory-context retrieval is delegated to a shared
governed knowledge service rather than C3 calling File Search directly. In practice the
reg-KB requirement text comes via **C1** (``POST /ask``): C3 sends the context query as a
question and maps the returned citations onto domain :class:`Citation` objects. The base
URL is read from ``RSK_COMPLIANCE_URL`` (C1) with ``KNOWLEDGE_BASE_URL`` as an alternate, both with
localhost defaults.
"""

from __future__ import annotations

import httpx

from ...domain.errors import ValidatorError
from ...domain.models import Citation, Jurisdiction, Regulator
from ...envread import ConfiguredEmptyError, read_env_setting
from . import _s2s

_DEFAULT_C1_URL = "http://localhost:8080"
_TIMEOUT = httpx.Timeout(15.0, connect=5.0)

#: The base-URL names in preference order: C1 first, the KB service as the alternate.
_URL_ENVS = ("RSK_COMPLIANCE_URL", "KNOWLEDGE_BASE_URL")


def _base_url() -> str:
    """First CONFIGURED name wins, absent names fall through, an EMPTIED name refuses.

    A chain of ``get(A) or get(B) or default`` reads an emptied ``A`` as an absent one and
    falls through to ``B`` or to loopback. Emptying a URL is an expressed intent and it names
    nothing, so it stops the chain loudly instead of demoting the client to the pod's own
    loopback, where nothing is listening or, worse, something else is.
    """
    for name in _URL_ENVS:
        setting = read_env_setting(name)
        if setting.is_configured_empty:
            raise ConfiguredEmptyError(
                f"{name} is set to an empty value, which names no knowledge service. Unset it "
                f"to fall through to {_URL_ENVS[-1]} or the documented default "
                f"({_DEFAULT_C1_URL!r}), or give it a value."
            )
        if setting.has_value:
            return setting.value
    return _DEFAULT_C1_URL


class RemoteKnowledgeBaseError(ValidatorError):
    """Raised when the remote knowledge service returns an unexpected status."""


class RemoteKnowledgeBaseAdapter:
    """HTTP client for the A2 KB context, via C1 ``/ask`` (or the KB service)."""

    def __init__(self, settings: object) -> None:
        self._settings = settings
        self._base_url = _s2s.validate_base_url(
            _base_url(),
            service="knowledge base",
        )

    def retrieve(self, query: str, top_k: int = 8) -> list[Citation]:
        """Return governed-KB citations relevant to ``query`` via C1 ``/ask``."""
        url = f"{self._base_url}/ask"
        # The service identity travels as the S2S bearer + signed-actor headers (shared
        # hex-service-kit commons), not as a spoofable JSON body field.
        payload = {"question": query, "filters": {}}
        try:
            response = httpx.post(
                url,
                json=payload,
                timeout=_TIMEOUT,
                headers=_s2s.headers("architecture-validator"),
            )
        except httpx.HTTPError as exc:
            raise RemoteKnowledgeBaseError(f"KB request to {url} failed: {exc}") from exc
        if response.status_code // 100 != 2:
            raise RemoteKnowledgeBaseError(
                f"KB {url} returned {response.status_code}: {response.text[:500]}"
            )
        body = response.json() or {}
        return [self._parse_citation(c) for c in (body.get("citations") or [])][:top_k]

    @staticmethod
    def _parse_citation(body: dict) -> Citation:
        regulator = _coerce_regulator(body.get("regulator"))
        jurisdiction = _coerce_jurisdiction(body.get("jurisdiction"), regulator)
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


def _coerce_regulator(value: object) -> Regulator:
    try:
        return Regulator(str(value).upper())
    except (ValueError, AttributeError):
        return Regulator.CROSS


def _coerce_jurisdiction(value: object, regulator: Regulator) -> Jurisdiction:
    from ...domain.models import REGULATOR_JURISDICTION

    try:
        return Jurisdiction(str(value).upper())
    except (ValueError, AttributeError):
        return REGULATOR_JURISDICTION.get(regulator, Jurisdiction.GLOBAL)
