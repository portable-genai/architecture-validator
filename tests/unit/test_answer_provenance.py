"""The service half of the model pills: which model ANSWERED, and whether it searched.

The console shows two pills at the top right: the model that answered the last request, and
``Search`` when that answer used an online search tool. Both come from response headers the kit
emits (``install_answer_provenance`` in ``api/app.py``) for whatever the model adapters NOTED as
they called. Before a request is answered the pill shows ``generator_model`` from ``/healthz``,
so that value must be the model the bound adapter calls, never one a configuration flag names
while the adapter calls another (the hard-reasoning flag did exactly that, and is deleted).

The console calls this service directly, cross-origin when standalone, so the kit also names both
headers in ``Access-Control-Expose-Headers``: a browser hides every other header from script.

No adapter here attaches an online search tool (retrieval is the governed File Search KB, a
separate port), so the ``Search`` half is proved by binding a noting adapter on the real route.
"""

from __future__ import annotations

import dataclasses

import pytest
from fastapi.testclient import TestClient
from hex_service_kit import provenance
from tests.conftest import LOOPBACK_PEER
from tests.fixtures import fake_genai

from architecture_validator.adapters.gcp.gemini_llm import GeminiLLMAdapter
from architecture_validator.adapters.local.llm import LocalDeterministicLLMAdapter
from architecture_validator.api import deps
from architecture_validator.config import (
    LOCAL_STUB_MODEL,
    Container,
    LocalSettings,
    ModelSettings,
    Settings,
)
from architecture_validator.domain.kernel import LlmMessage, LlmRequest, LlmResponse

ANSWERED_BY = "x-answered-by"
SEARCH_USED = "x-search-used"

#: A submission that leaves principles unmet, so the intake drafts requirements with the model.
_SUBMISSION = {
    "id": "proj-pills",
    "name": "Onboarding assistant (FICTIONAL)",
    "description": "A demo submission",
    "requirements": "chat over policy",
}


def _local_settings() -> Settings:
    base = Settings.load("config/settings.yaml")
    return dataclasses.replace(
        base, profile="local", local=LocalSettings(db_path=":memory:", audit_path=":memory:")
    )


@pytest.fixture
def container(monkeypatch: pytest.MonkeyPatch) -> Container:
    built = Container(_local_settings())
    monkeypatch.setattr(deps, "get_container", lambda: built)
    return built


@pytest.fixture
def client(container: Container) -> TestClient:
    from architecture_validator.api.app import app

    return TestClient(app, client=LOOPBACK_PEER)


def _validate(client: TestClient, **headers: str) -> dict[str, str]:
    response = client.post("/validate", json={"submission": _SUBMISSION}, headers=headers)
    assert response.status_code == 200, response.text
    return dict(response.headers)


def test_a_local_intake_names_the_stub_that_answered(
    client: TestClient, container: Container
) -> None:
    """Under ``local`` the pill reads the same string before an answer and after it."""
    headers = _validate(client)
    assert container.llm.requests, "the intake never called the model port"
    assert headers[ANSWERED_BY] == container.settings.generator_model == LOCAL_STUB_MODEL
    assert SEARCH_USED not in headers, "no search tool was attached, so none may be claimed"


def test_a_route_that_calls_no_model_names_none(client: TestClient) -> None:
    headers = dict(client.get("/healthz").headers)
    assert ANSWERED_BY not in headers
    assert SEARCH_USED not in headers


class _SearchingLLM(LocalDeterministicLLMAdapter):
    """The local generator, plus what an adapter that attached a search tool would note."""

    def generate(self, request: LlmRequest) -> LlmResponse:
        provenance.note_search()
        return super().generate(request)


def test_a_call_that_searched_says_so_and_the_next_request_starts_clean(
    client: TestClient, container: Container
) -> None:
    container.llm = _SearchingLLM(container.settings)
    headers = _validate(client)
    assert headers[ANSWERED_BY] == LOCAL_STUB_MODEL
    assert headers[SEARCH_USED] == "true"
    container.llm = LocalDeterministicLLMAdapter(container.settings)
    assert SEARCH_USED not in _validate(client), "a search leaked into a later request"


def test_a_cross_origin_console_can_read_both_headers(client: TestClient) -> None:
    headers = _validate(client, Origin="http://localhost:3000")
    assert headers.get("access-control-allow-origin") == "http://localhost:3000", (
        "the dev console origin is not on this run's CORS allowlist, so this proves nothing"
    )
    exposed = {name.strip().lower() for name in headers["access-control-expose-headers"].split(",")}
    assert {ANSWERED_BY, SEARCH_USED} <= exposed


def _gemini(monkeypatch: pytest.MonkeyPatch) -> tuple[GeminiLLMAdapter, fake_genai.FakeClient]:
    fake_genai.install(monkeypatch)
    settings = dataclasses.replace(_local_settings(), profile="gcp")
    adapter = GeminiLLMAdapter(settings)
    client = fake_genai.FakeClient()
    adapter._client = client
    return adapter, client


def _ask(model: str | None = None) -> LlmRequest:
    return LlmRequest(messages=(LlmMessage(role="user", content="x"),), model=model)


def test_the_managed_adapter_notes_the_model_it_called(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, client = _gemini(monkeypatch)
    with provenance.scope() as record:
        adapter.generate(_ask("an-explicit-model"))
        adapter.classify("text", ["a", "b"])
    assert record.models == [client.calls[0]["model"], client.calls[1]["model"]]
    assert record.models[0] == "an-explicit-model"
    assert record.search_used is False


def test_a_failed_managed_call_notes_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, client = _gemini(monkeypatch)

    def refuse(**_: object) -> None:
        raise RuntimeError("quota")

    monkeypatch.setattr(client, "generate_content", refuse)
    with provenance.scope() as record, pytest.raises(RuntimeError):
        adapter.generate(_ask())
    assert record.models == []


def test_generator_model_is_the_model_the_managed_adapter_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The pill's configured value and the answered value agree for a call naming no model."""
    adapter, client = _gemini(monkeypatch)
    adapter.generate(_ask())
    assert client.calls[-1]["model"] == adapter._settings.generator_model


def test_the_hard_reasoning_flag_no_longer_exists() -> None:
    """The latent false banner: a flag that moved the displayed model but not the called one."""
    fields = {field.name for field in dataclasses.fields(ModelSettings)}
    assert "use_hard_reasoning" not in fields
    assert "hard_reasoning" not in fields
    with open("config/settings.yaml", encoding="utf-8") as handle:
        assert "hard_reasoning" not in handle.read()
