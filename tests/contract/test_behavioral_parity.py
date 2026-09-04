"""Behavioral parity: the same request through every implementation of a port.

The structural contract suite (``test_port_parity``) proves every adapter *satisfies*
its Protocol. This suite proves the stronger claim behind the no-lock-in promise
(P-02): for one canonical request, every SDK-free implementation of a port behaves
identically at the boundary (same first-class domain objects / verdicts / byte-identical
serialized payloads), and the on-prem migration placeholder fails fast rather than ever
returning a silent wrong answer.

What this repo actually ships (see ``config/settings.yaml`` ``adapters:``), and how each
port's parity is proven here:

* ``audit`` (agent-observability) and ``registry`` (agent-registry) have a REAL httpx ``platform``
  delegate beside the in-process ``local`` adapter. For each, the same request is put through
  ``local`` and through the ``platform`` client (its sibling horizontal-platform service mocked with
  respx at the documented SPEC section 6 contract), and the two are asserted identical at the
  boundary (``local == platform``): the audit sink receives the byte-identical record the local sink
  stored, and the registry round-trips the byte-identical ``AgentCard``. * ``control_mapping`` (the
  cloud control-mapping toolkit / C2) also has a REAL httpx ``platform`` delegate, but its ``local``
  adapter is a canned best-effort signal (empty by design, mirroring the degrade-gracefully managed
  path), so ``local == platform`` does not apply. Instead the respx suite proves the delegate
  faithfully round-trips C2's ``/evidence-pack`` wire contract into first-class domain
  :class:`Citation` objects, while ``local`` is asserted deterministic across independent instances.
  * ``policy_engine`` (the consequential intake gate) has NO ``platform`` delegate (a laptop runs
  one app), so its parity claim is *determinism*: the same submission through two independent
  ``local`` evaluators returns byte-identical findings. This is the property a migration relies on,
  so it is asserted directly. * every port's ``onprem`` placeholder constructs and satisfies the
  Protocol but raises ``NotImplementedError`` on use (fail-fast), asserted for all four ports above.

Plus the end-to-end proof: the full ``ValidationService`` intake pipeline runs
deterministically under ``local`` and fails fast under ``onprem`` with **zero domain
edits**, only a profile change. The suite passes under
``ARCH_VALIDATOR_PROFILE=local pytest``.

All data below is obviously fictional.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
import respx

from architecture_validator.config import Container, LocalSettings, Settings, instantiate
from architecture_validator.domain.models import (
    AgentCard,
    AgentSkill,
    AuditEvent,
    Citation,
    Decision,
    Jurisdiction,
    ProjectSubmission,
    Regulator,
)
from architecture_validator.domain.serialization import to_jsonable

CONFIG_PATH = "config/settings.yaml"

# The platform delegates' localhost defaults (SPEC section 6): mocked, never actually
# served. These mirror the ``_DEFAULT_URL`` in each ``adapters/platform/remote_*`` module.
OBSERVABILITY = "http://localhost:8085"  # remote_audit -> A5 (agent-observability) /v1/audit
AGENT_REGISTRY = "http://localhost:8083"  # remote_registry -> A3 (agent-registry) /v1/agents
# remote_control_mapping -> compliance-advisory's control-mapping module /evidence-pack
# (served on :8080, the same port as the assistant's other routes).
RSK_CONTROL_MAPPING = "http://localhost:8080"

# A fictional live scope for the residency scanner port; the seeded scanner returns its
# built-in synthetic estate for any scope with no explicit rows, so any ``projects/...``
# value grades the default estate.
FICTIONAL_SCOPE = "projects/acme-sg-fictional"


def _settings(profile: str) -> Settings:
    base = Settings.load(CONFIG_PATH)
    # In-memory SQLite so the parity assertions stay ephemeral and deterministic.
    return replace(
        base,
        profile=profile,
        local=LocalSettings(db_path=":memory:", audit_path=":memory:"),
    )


def _adapter(port: str, profile: str):
    settings = _settings(profile)
    return instantiate(settings.adapters[port][profile], settings)


# --------------------------------------------------------------------------- #
# PolicyEnginePort — no platform sibling, so parity == determinism across evaluators
# --------------------------------------------------------------------------- #
def test_policy_engine_parity_is_deterministic_across_independent_evaluators():
    """Two independent local policy evaluators return byte-identical findings.

    The consequential verdict is a pure deterministic evaluator (no platform delegate),
    so the migration-relevant property is that a re-run is indistinguishable. The on-prem
    placeholder must never wave a submission through: it fails fast instead.
    """
    submission = ProjectSubmission(
        id="proj-fiction-001",
        name="Ungated Chat Agent (FICTIONAL)",
        description="A customer-facing chat agent with no declared guardrail or exit plan.",
        requirements="Answer product questions; no controls declared.",
    )

    first = _adapter("policy_engine", "local").evaluate(submission, [])
    second = _adapter("policy_engine", "local").evaluate(submission, [])

    assert len(first) == 12, "the local evaluator must return one finding per General Principle"
    # Same first-class domain objects, in the same order: the property a migration relies on.
    assert first == second
    # And byte-identical once serialized at the boundary (what a remote sibling would return).
    assert to_jsonable(first) == to_jsonable(second)

    with pytest.raises(NotImplementedError):
        _adapter("policy_engine", "onprem").evaluate(submission, [])


# --------------------------------------------------------------------------- #
# ControlMappingClientPort (the cloud control-mapping toolkit / C2) — real httpx delegate; faithful
# wire round-trip
# --------------------------------------------------------------------------- #
def test_control_mapping_parity_delegate_round_trips_c2_wire_contract():
    """The platform delegate maps C2's ``/evidence-pack`` payload onto domain Citations.

    ``local`` is a canned best-effort signal (empty by design, mirroring the managed path's
    degrade-gracefully behaviour), so ``local == platform`` does not apply here. What the
    no-lock-in claim needs instead is that the HTTP delegate is a faithful, lossless
    translation of the sibling's documented contract into the SAME first-class domain
    :class:`Citation` the rest of the hexagon consumes. That is what is asserted.
    """
    scope = "Ungated Chat Agent (FICTIONAL)"

    # local: canned best-effort, deterministic across two independent instances.
    first = _adapter("control_mapping", "local").coverage(scope)
    second = _adapter("control_mapping", "local").coverage(scope)
    assert first == second == []

    # platform: the same request maps C2's evidence pack onto a domain Citation, lossless.
    expected = Citation(
        source_id="ctrl-map-fiction-7",
        regulator=Regulator.MAS,
        jurisdiction=Jurisdiction.SG,
        title="Control coverage evidence (FICTIONAL)",
        url="https://example.test/evidence/ctrl-map-fiction-7",
        version="2026.1",
        page=3,
        snippet="Guardrail control mapped to the intake principle.",
    )
    with respx.mock:
        respx.post(f"{RSK_CONTROL_MAPPING}/evidence-pack").respond(
            200,
            json={
                "citations": [
                    {
                        "source_id": expected.source_id,
                        "regulator": expected.regulator.value,
                        "jurisdiction": expected.jurisdiction.value,
                        "title": expected.title,
                        "url": expected.url,
                        "version": expected.version,
                        "page": expected.page,
                        "snippet": expected.snippet,
                    }
                ]
            },
        )
        coverage = _adapter("control_mapping", "platform").coverage(scope)

    assert coverage == [expected], "the C2 delegate did not faithfully map the wire payload"

    with pytest.raises(NotImplementedError):
        _adapter("control_mapping", "onprem").coverage(scope)


def test_control_mapping_delegate_defaults_to_compliance_assistant_port(monkeypatch):
    """The remote control-mapping client reads ``RSK_CONTROL_MAPPING_URL`` and defaults to :8080.

    The control-mapping evidence packs come from the compliance-advisory's
    control-mapping module, so an unset env var must resolve to the compliance assistant's
    port (:8080), and the env var NAME is the one pinned override knob. The ``/evidence-pack``
    wire contract the delegate POSTs is independent of which endpoint serves it.
    """
    from architecture_validator.adapters.platform.remote_control_mapping import (
        RemoteControlMappingAdapter,
    )

    monkeypatch.delenv("RSK_CONTROL_MAPPING_URL", raising=False)
    default_client = RemoteControlMappingAdapter(_settings("platform"))
    assert default_client._base_url == "http://localhost:8080", (
        "the control-mapping default must point at the compliance assistant's port (:8080)"
    )

    monkeypatch.setenv("RSK_CONTROL_MAPPING_URL", "https://control-mapping.example.test")
    override_client = RemoteControlMappingAdapter(_settings("platform"))
    assert override_client._base_url == "https://control-mapping.example.test", (
        "the client must honor the RSK_CONTROL_MAPPING_URL override (env var name unchanged)"
    )


# --------------------------------------------------------------------------- #
# AuditSinkPort (agent-observability) — byte-identical record shape at every sink boundary
# --------------------------------------------------------------------------- #
def test_audit_parity_identical_payload_at_every_sink():
    """The platform sink receives the byte-identical record the local sink stored."""
    event = AuditEvent(
        action="validate",
        actor="reviewer@bank.test",
        decision=Decision.ESCALATED,
        summary_prompt="proj-fiction-001: Ungated Chat Agent (FICTIONAL)",
        summary_response="verdict=FAIL; failed=P-01,P-05; injected=2",
        citations=(
            Citation(
                source_id="P-05",
                regulator=Regulator.CROSS,
                jurisdiction=Jurisdiction.GLOBAL,
                title="General Principle P-05 (FICTIONAL provenance)",
                url="https://example.test/principles/P-05",
                page=1,
            ),
        ),
        metadata={"passed": "false", "requires_human_review": "true"},
    )
    expected = to_jsonable(event)

    local_audit = _adapter("audit", "local")
    local_audit.record(event)
    # The local append-only sink stores exactly the serialized domain object.
    assert local_audit.read_all() == [expected]

    with respx.mock:
        route = respx.post(f"{OBSERVABILITY}/v1/audit").respond(202)
        _adapter("audit", "platform").record(event)
        posted = json.loads(route.calls.last.request.content)
    # local == platform: the platform sink receives the byte-identical record local stored.
    assert posted == expected, "platform sink received a different record than local stored"

    with pytest.raises(NotImplementedError):
        _adapter("audit", "onprem").record(event)


# --------------------------------------------------------------------------- #
# AgentRegistryPort (agent-registry) — the same AgentCard round-trips either way
# --------------------------------------------------------------------------- #
def test_registry_parity_same_card_across_implementations():
    card = AgentCard(
        name="architecture-validator",
        description="Policy-as-code intake gate for the 12 General Principles.",
        url="https://architecture-validator.example.test",
        version="0.1.0",
        skills=(AgentSkill(id="validate", name="Validate", description="Validate a submission."),),
        provider="architecture-validator",
    )

    local_registry = _adapter("registry", "local")
    local_registry.register(card)
    local_card = local_registry.get(card.name)
    assert local_card is not None, "local registry did not return the registered card"

    with respx.mock:
        respx.post(f"{AGENT_REGISTRY}/v1/agents").respond(201)
        # agent-registry serves back the same card shape for the same name (SPEC section 6).
        respx.get(f"{AGENT_REGISTRY}/v1/agents/{card.name}").respond(200, json=to_jsonable(card))
        remote_registry = _adapter("registry", "platform")
        remote_registry.register(card)
        remote_card = remote_registry.get(card.name)

    # Not merely the same shape: the same first-class domain object either way.
    assert remote_card == local_card == card

    with pytest.raises(NotImplementedError):
        _adapter("registry", "onprem").list()


# --------------------------------------------------------------------------- #
# IaCScannerPort (residency live scan) — no platform sibling, so parity == determinism
# --------------------------------------------------------------------------- #
def test_scanner_parity_is_deterministic_across_independent_estates():
    """Two independent local seeded estates return byte-identical resources for one scope.

    The live-scan source has no ``platform`` delegate (a laptop runs one app), so its
    no-lock-in claim is *determinism*: the same scope through two independent ``local``
    seeded SQLite estates returns the same first-class domain objects, and the on-prem
    placeholder fails fast rather than returning a silent wrong answer.
    """
    first = _adapter("scanner", "local").scan(FICTIONAL_SCOPE)
    second = _adapter("scanner", "local").scan(FICTIONAL_SCOPE)

    assert first, "local seeded scanner returned no resources for the default estate"
    # Same first-class domain objects, in the same order: the property a migration relies on.
    assert first == second
    assert to_jsonable(first) == to_jsonable(second)
    # The seeded estate plants an out-of-region bucket so a downstream detector grades a FAIL.
    assert any(r.region == "us-central1" for r in first), "expected the planted violation"

    with pytest.raises(NotImplementedError):
        _adapter("scanner", "onprem").scan(FICTIONAL_SCOPE)


def test_full_scan_pipeline_local_scans_and_onprem_fails_fast():
    """The whole residency scan pipeline runs under local and fails fast under onprem.

    Only the profile changes: the live scan is step one of ``scan_target`` for a project
    scope, so under ``onprem`` the placeholder scanner raises and the whole pipeline fails
    fast with zero domain edits, while under ``local`` it grades a real cited FAIL verdict.
    """
    from architecture_validator.api.deps import build_scan_service

    actor = "parity@test"

    scan = build_scan_service(Container(_settings("local"))).scan_target(
        FICTIONAL_SCOPE, actor, action="scan_project"
    )
    assert scan.resources_scanned > 0, "the local seeded estate must return resources"
    assert scan.violations, "the seeded estate plants gradable residency violations"
    assert scan.passed is False, "a planted out-of-region resource must FAIL the gate"
    assert scan.requires_human_review is True, "a HIGH/CRITICAL scan escalates (maker-checker)"
    assert any(v.citations for v in scan.violations), "every finding cites its principle"

    with pytest.raises(NotImplementedError):
        build_scan_service(Container(_settings("onprem"))).scan_target(
            FICTIONAL_SCOPE, actor, action="scan_project"
        )


# --------------------------------------------------------------------------- #
# End to end: one profile line swaps the whole stack, domain untouched
# --------------------------------------------------------------------------- #
def _submission() -> ProjectSubmission:
    return ProjectSubmission(
        id="proj-fiction-042",
        name="Locked-in Vendor Agent (FICTIONAL)",
        description="A RAG agent pinned to a single managed vendor with no exit plan.",
        requirements="Ingest policies; answer staff questions; no residency controls declared.",
        declared_region="us-central1",
        uses_rag=True,
    )


def test_full_pipeline_local_is_deterministic_and_onprem_fails_fast():
    from architecture_validator.api.deps import build_validation_service

    submission = _submission()

    report_a = build_validation_service(Container(_settings("local"))).validate(
        submission, actor="parity@test"
    )
    report_b = build_validation_service(Container(_settings("local"))).validate(
        submission, actor="parity@test"
    )

    assert len(report_a.findings) == 12, "the offline gate must evaluate all 12 principles"
    assert report_a.requires_human_review is True, "a non-clean intake must escalate"
    # The whole report is byte-identical at the boundary on a re-run (same profile, no edits).
    # ``generated_at`` is the only wall-clock field; compare everything else.
    payload_a = to_jsonable(report_a)
    payload_b = to_jsonable(report_b)
    payload_a.pop("generated_at", None)
    payload_b.pop("generated_at", None)
    assert payload_a == payload_b

    # Same request, only the profile changed: the policy engine is step 1 and its on-prem
    # placeholder raises, so the whole pipeline fails fast with no domain edits.
    with pytest.raises(NotImplementedError):
        build_validation_service(Container(_settings("onprem"))).validate(
            submission, actor="parity@test"
        )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
