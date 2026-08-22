"""Unit tests for the FastAPI /scan endpoint (the surface C3 consumes).

Driven through FastAPI's dependency override so the endpoint runs against the seeded
in-memory local adapters (no Google Cloud SDK). Asserts the JSON projection mirrors the
domain ResidencyScan and that the verdict + violations are surfaced for a downstream consumer.

Identity is server-verified: there is no ``actor`` field in the request body. The audit
actor is the :class:`Principal` the local persona adapter resolves from the (optional)
``X-Dev-Persona`` header, defaulting to the first seeded persona. A bad persona is a 401.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from tests.conftest import LOOPBACK_PEER, FakeScanner

from architecture_validator.adapters.local.audit import LocalAppendOnlyAuditAdapter
from architecture_validator.adapters.local.llm import LocalDeterministicLLMAdapter
from architecture_validator.adapters.local.tracer import LocalNoopTracerAdapter
from architecture_validator.api import deps
from architecture_validator.api.app import app
from architecture_validator.config import Container, LocalSettings, Settings
from architecture_validator.domain.residency.detector import ViolationDetector
from architecture_validator.domain.residency.scan_service import ResidencyScanService


def _settings() -> Settings:
    """Ephemeral in-memory ``local`` settings (deterministic, no files written)."""
    return Settings(local=LocalSettings(db_path=":memory:", audit_path=":memory:"))


# The first seeded persona is the default audit actor when no X-Dev-Persona header is sent.
_DEFAULT_ACTOR = "demo.analyst@bank.example"
_AUDITOR_ACTOR = "demo.auditor@bank.example"


@pytest.fixture
def recorder() -> LocalAppendOnlyAuditAdapter:
    """The audit sink wired into the overridden service, so tests can read the actor.

    The local append-only adapter records every event in ``.events`` natively, so it is
    the recorder the residency API tests read the audit actor from (no bespoke fake).
    """
    return LocalAppendOnlyAuditAdapter(_settings())


@pytest.fixture
def client(recorder, monkeypatch: pytest.MonkeyPatch):
    service = ResidencyScanService(
        FakeScanner(),
        ViolationDetector(),
        LocalDeterministicLLMAdapter(_settings()),
        LocalNoopTracerAdapter(_settings()),
        recorder,
    )
    # Identity comes from the process-wide Container, which is built from the AMBIENT
    # environment. Bind a purpose-built local-profile Container instead, so the seeded
    # personas these tests assert on are a deliberate choice made here rather than an
    # inherited one: the adapter refuses to serve an unconsented local profile.
    base = Settings.load("config/settings.yaml")
    settings = Settings(
        project_id=base.project_id,
        region=base.region,
        profile="local",
        profile_explicit=True,
        kms_key=base.kms_key,
        models=base.models,
        policy=base.policy,
        knowledge_base=base.knowledge_base,
        logging=base.logging,
        agent_engine=base.agent_engine,
        local=LocalSettings(db_path=":memory:", audit_path=":memory:"),
        adapters=base.adapters,
    )
    monkeypatch.setattr(deps, "get_container", lambda: Container(settings))
    app.dependency_overrides[deps.get_scan_service] = lambda: service
    with TestClient(app, client=LOOPBACK_PEER) as c:
        yield c
    app.dependency_overrides.clear()


def test_scan_inline_resources_returns_verdict(client):
    body = {
        "resources": [
            {
                "address": "google_storage_bucket.export",
                "type": "google_storage_bucket",
                "region": "us-central1",
                "attributes": {
                    "kms_key_name": "k",
                    "public_access_prevention": "enforced",
                    "service_perimeter": "p",
                },
                "source_ref": "main.tf:10",
            }
        ],
    }
    resp = client.post("/scan", json=body)
    assert resp.status_code == 200
    data = resp.json()
    assert data["passed"] is False
    assert data["resources_scanned"] == 1
    assert data["verdict"]["exit_code"] == 1
    kinds = {v["kind"] for v in data["violations"]}
    assert "region_not_allowed" in kinds
    # The finding carries citations so a consumer (C3) can trace provenance.
    assert data["violations"][0]["citations"]


def test_default_persona_is_the_audit_actor(client, recorder):
    """With no X-Dev-Persona header the verified default persona is the audit actor."""
    resp = client.post("/scan", json={"resources": []})
    assert resp.status_code == 200
    assert recorder.events, "the scan must have written an audit event"
    assert all(e.actor == _DEFAULT_ACTOR for e in recorder.events)


def test_selected_persona_is_the_audit_actor(client, recorder):
    """The X-Dev-Persona-selected persona (not any client body) is the audit actor."""
    resp = client.post("/scan", json={"resources": []}, headers={"X-Dev-Persona": "auditor"})
    assert resp.status_code == 200
    assert recorder.events
    assert all(e.actor == _AUDITOR_ACTOR for e in recorder.events)


def test_unknown_persona_is_unauthorized(client):
    """An unresolvable identity (unknown dev persona) is a 401, never a silent default."""
    resp = client.post("/scan", json={"resources": []}, headers={"X-Dev-Persona": "does-not-exist"})
    assert resp.status_code == 401


def test_personas_route_lists_seeded_personas(client):
    """The picker route exposes the seeded personas under a DELIBERATE local profile.

    Takes the ``client`` fixture rather than building its own: the personas exist only when
    someone chose the local profile, so the route must be asked against a Container that
    made that choice, not against whatever the ambient environment happens to say.
    """
    resp = client.get("/v1/personas")
    assert resp.status_code == 200
    ids = {p["id"] for p in resp.json()}
    assert {"analyst", "approver", "auditor", "other-tenant"} <= ids


def test_personas_route_is_empty_when_nobody_chose_the_local_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An inherited local profile advertises no personas, because it can resolve none."""
    base = Settings.load("config/settings.yaml")
    inherited = Settings(
        profile="local",
        profile_explicit=False,
        local=LocalSettings(db_path=":memory:", audit_path=":memory:"),
        adapters=base.adapters,
    )
    monkeypatch.setattr(deps, "get_container", lambda: Container(inherited))
    with TestClient(app, client=LOOPBACK_PEER) as c:
        resp = c.get("/v1/personas")
        assert resp.status_code == 200
        assert resp.json() == []
        # And the seeded approver identity is not available to any protected route either.
        assert c.post("/scan", json={"target": "projects/demo"}).status_code == 401


def test_scan_clean_inline_resources_passes(client):
    body = {
        "resources": [
            {
                "address": "google_storage_bucket.kyc",
                "type": "google_storage_bucket",
                "region": "asia-southeast1",
                "attributes": {
                    "kms_key_name": "k",
                    "public_access_prevention": "enforced",
                    "service_perimeter": "p",
                },
                "source_ref": "main.tf:1",
            }
        ]
    }
    resp = client.post("/scan", json=body)
    assert resp.status_code == 200
    assert resp.json()["passed"] is True


def test_healthz_reports_profile_and_region():
    with TestClient(app, client=LOOPBACK_PEER) as c:
        resp = c.get("/healthz")
    assert resp.status_code == 200
    body = resp.json()
    assert body["region"] == "asia-southeast1"


def test_agent_card_advertises_scan_skills():
    with TestClient(app, client=LOOPBACK_PEER) as c:
        resp = c.get("/.well-known/agent-card.json")
    assert resp.status_code == 200
    skills = {s["id"] for s in resp.json()["skills"]}
    assert {"scan_iac", "scan_project", "explain_violation"} <= skills


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
