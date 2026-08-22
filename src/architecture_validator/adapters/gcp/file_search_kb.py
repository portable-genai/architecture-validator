"""File Search knowledge-base adapter (KnowledgeBasePort).

Primary production grounding backend for C3: **File Search** (governed RAG, the A2
Enterprise KB) on the **Gemini Enterprise Agent Platform**, reached through the Discovery
Engine ``SearchService`` on a **regional** endpoint pinned to ``asia-southeast1`` so all
regulatory-document retrieval stays in-country for MAS/HKMA/APRA/FSA residency.

Each result is mapped to a domain :class:`Citation` carrying page-level provenance, used to
ground the findings and injected requirements C3 produces. All Google Cloud SDK imports are
lazy so the on-prem / test profile imports this module without
``google-cloud-discoveryengine`` installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ...config import Settings
from ...domain.models import Citation, Jurisdiction, Regulator

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from google.cloud import discoveryengine_v1


class FileSearchKnowledgeBaseAdapter:
    """Retrieve governed-KB citations from File Search (Discovery Engine v1)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        cfg = settings.knowledge_base
        self._location = cfg.location
        self._engine_id = cfg.engine_id
        self._serving_config_id = cfg.serving_config
        self._data_store_id = cfg.data_store_id
        self._endpoint = f"{self._location}-discoveryengine.googleapis.com"
        self._client: Any | None = None

    def _get_client(self) -> discoveryengine_v1.SearchServiceClient:
        if self._client is None:
            from google.api_core.client_options import ClientOptions
            from google.cloud import discoveryengine_v1

            self._client = discoveryengine_v1.SearchServiceClient(
                client_options=ClientOptions(api_endpoint=self._endpoint),
            )
        return self._client

    def _serving_config_path(self) -> str:
        return (
            f"projects/{self._settings.project_id}"
            f"/locations/{self._location}"
            f"/collections/default_collection"
            f"/engines/{self._engine_id}"
            f"/servingConfigs/{self._serving_config_id}"
        )

    # ------------------------------------------------------------------ #
    # KnowledgeBasePort
    # ------------------------------------------------------------------ #
    def retrieve(self, query: str, top_k: int = 8) -> list[Citation]:
        """Return governed-KB citations relevant to ``query`` (reg context for findings)."""
        from google.cloud import discoveryengine_v1

        client = self._get_client()
        content_spec = discoveryengine_v1.SearchRequest.ContentSearchSpec(
            snippet_spec=discoveryengine_v1.SearchRequest.ContentSearchSpec.SnippetSpec(
                return_snippet=True,
            ),
        )
        request = discoveryengine_v1.SearchRequest(
            serving_config=self._serving_config_path(),
            query=query,
            page_size=top_k,
            content_search_spec=content_spec,
        )
        response = client.search(request=request)
        return [self._result_to_citation(r) for r in response.results]

    # ------------------------------------------------------------------ #
    # Result mapping
    # ------------------------------------------------------------------ #
    def _result_to_citation(self, result: Any) -> Citation:
        document = result.document
        struct = self._to_dict(getattr(document, "struct_data", None))
        derived = self._to_dict(getattr(document, "derived_struct_data", None))
        source_id = (
            struct.get("source_id") or struct.get("id") or getattr(document, "id", "") or "unknown"
        )
        regulator = self._parse_regulator(struct.get("regulator"))
        return Citation(
            source_id=str(source_id),
            regulator=regulator,
            jurisdiction=self._parse_jurisdiction(struct.get("jurisdiction"), regulator),
            title=str(struct.get("title") or derived.get("title") or source_id),
            url=str(struct.get("url") or derived.get("link") or ""),
            version=str(struct.get("version") or "unknown"),
            page=self._parse_page(struct.get("page")),
            snippet=self._first_snippet(derived),
        )

    @staticmethod
    def _to_dict(value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        try:
            return dict(value)
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def _first_snippet(derived: dict[str, Any]) -> str:
        for snip in derived.get("snippets") or []:
            snip_d = FileSearchKnowledgeBaseAdapter._to_dict(snip)
            text = snip_d.get("snippet")
            if text:
                return str(text)
        return ""

    @staticmethod
    def _parse_regulator(value: Any) -> Regulator:
        if value:
            try:
                return Regulator(str(value).upper())
            except ValueError:
                pass
        return Regulator.CROSS

    @staticmethod
    def _parse_jurisdiction(value: Any, regulator: Regulator) -> Jurisdiction:
        from ...domain.models import REGULATOR_JURISDICTION

        if value:
            try:
                return Jurisdiction(str(value).upper())
            except ValueError:
                pass
        return REGULATOR_JURISDICTION.get(regulator, Jurisdiction.GLOBAL)

    @staticmethod
    def _parse_page(value: Any) -> int | None:
        if value is None:
            return None
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None
