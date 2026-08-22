"""API-level tests for server-verified identity on the /validate route.

Prove the identity seam end-to-end at the HTTP boundary:

* an unknown ``X-Dev-Persona`` is rejected with 401 (no verified principal), and
* the default persona (no header) and an explicitly selected persona both become the
  audit actor recorded for the validation, never a client-supplied body field.

``deps.get_container`` is ``lru_cache``d, so the test monkeypatches it to return a
purpose-built local-profile Container (rather than mutating the environment), sharing the
audit adapter instance so the recorded actor can be asserted.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tests.conftest import LOOPBACK_PEER

from architecture_validator.api import deps
from architecture_validator.config import Container, LocalSettings, Settings

_SUBMISSION = {
    "id": "proj-1",
    "name": "Onboarding assistant (FICTIONAL)",
    "description": "A demo submission",
    "requirements": "chat over policy",
}


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    base = Settings.load("config/settings.yaml")
    # Local profile with in-memory stores, keeping the real adapter bindings from YAML.
    settings = Settings(
        project_id=base.project_id,
        region=base.region,
        profile="local",
        kms_key=base.kms_key,
        models=base.models,
        policy=base.policy,
        knowledge_base=base.knowledge_base,
        logging=base.logging,
        agent_engine=base.agent_engine,
        local=LocalSettings(db_path=":memory:", audit_path=":memory:"),
        adapters=base.adapters,
    )
    container = Container(settings)
    # Bypass the lru_cached process-wide container so this test drives its own instance.
    monkeypatch.setattr(deps, "get_container", lambda: container)
    from architecture_validator.api.app import app

    test_client = TestClient(app, client=LOOPBACK_PEER)
    test_client._container = container  # type: ignore[attr-defined]  # for assertions
    return test_client


def _last_actor(client: TestClient) -> str:
    container: Container = client._container  # type: ignore[attr-defined]
    events = container.audit.events
    assert events, "the validation should have written an audit event"
    return events[-1].actor


def test_unknown_persona_is_401(client: TestClient) -> None:
    res = client.post(
        "/validate",
        json={"submission": _SUBMISSION},
        headers={"X-Dev-Persona": "does-not-exist"},
    )
    assert res.status_code == 401


def test_default_persona_is_the_audit_actor(client: TestClient) -> None:
    res = client.post("/validate", json={"submission": _SUBMISSION})
    assert res.status_code == 200
    assert _last_actor(client) == "demo.analyst@bank.example"


def test_selected_persona_is_the_audit_actor(client: TestClient) -> None:
    res = client.post(
        "/validate",
        json={"submission": _SUBMISSION},
        headers={"X-Dev-Persona": "auditor"},
    )
    assert res.status_code == 200
    assert _last_actor(client) == "demo.auditor@bank.example"


def test_body_actor_is_ignored(client: TestClient) -> None:
    # A client-asserted actor in the body must not become the audit actor.
    res = client.post(
        "/validate",
        json={"submission": _SUBMISSION, "actor": "attacker@evil.example"},
    )
    assert res.status_code == 200
    assert _last_actor(client) == "demo.analyst@bank.example"


def test_personas_endpoint_lists_local_personas(client: TestClient) -> None:
    res = client.get("/v1/personas")
    assert res.status_code == 200
    ids = {p["id"] for p in res.json()}
    assert {"analyst", "approver", "auditor", "other-tenant"} <= ids


def test_api_security_headers_cover_local_baseline(client: TestClient) -> None:
    res = client.get("/principles")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert res.headers["referrer-policy"] == "no-referrer"
    assert "frame-ancestors" in res.headers["content-security-policy"]
    assert "strict-transport-security" not in res.headers


@pytest.mark.parametrize("profile", ["gcp", "platform"])
def test_secure_profile_adds_hsts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    monkeypatch.setattr(deps, "get_settings", lambda: Settings(profile=profile))
    res = client.get("/principles")
    assert res.headers["strict-transport-security"].startswith("max-age=31536000")


@pytest.mark.parametrize("profile", ["onprem", "unconfigured"])
def test_non_tls_profile_does_not_add_hsts(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    from types import SimpleNamespace

    monkeypatch.setattr(deps, "get_settings", lambda: SimpleNamespace(profile=profile))
    res = client.get("/principles")
    assert "strict-transport-security" not in res.headers
