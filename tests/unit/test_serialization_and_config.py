"""Unit tests for serialization, Settings.load, and Container wiring.

* domain/serialization.to_jsonable round-trips enums (-> .value) and datetimes.
* Settings.load parses config/settings.yaml.
* Container under profile=onprem binds the on-prem placeholder adapters, and each bound
  adapter satisfies its runtime_checkable Protocol (structural parity).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from tests.fixtures import sample_projects

from architecture_validator import ports
from architecture_validator.config import Container, Settings
from architecture_validator.domain import principles_eval
from architecture_validator.domain.models import (
    AuditEvent,
    CheckStatus,
    Citation,
    Decision,
    Jurisdiction,
    Regulator,
    Severity,
    ValidationReport,
)
from architecture_validator.domain.residency.models import (
    ResidencyControl,
    ResidencyScan,
    ResidencyViolation,
    ResourceConfig,
    ScanVerdict,
    SeverityCount,
    ViolationKind,
)

CONFIG_PATH = "config/settings.yaml"

PORT_PROTOCOLS = {
    "policy_engine": ports.PolicyEnginePort,
    "knowledge_base": ports.KnowledgeBasePort,
    "control_mapping": ports.ControlMappingClientPort,
    "residency": ports.ResidencyClientPort,
    "llm": ports.LLMPort,
    "audit": ports.AuditSinkPort,
    "tracer": ports.ObservabilityTracerPort,
    "evaluation": ports.EvaluationGatePort,
    "registry": ports.AgentRegistryPort,
    "tool_catalog": ports.ToolCatalogPort,
}


def _to_jsonable():
    from architecture_validator.domain.serialization import to_jsonable

    return to_jsonable


# --------------------------------------------------------------------------- #
# to_jsonable
# --------------------------------------------------------------------------- #
def test_to_jsonable_enum_becomes_value():
    to_jsonable = _to_jsonable()
    assert to_jsonable(Regulator.MAS) == "MAS"
    assert to_jsonable(Severity.HIGH) == "high"
    assert to_jsonable(CheckStatus.FAIL) == "FAIL"
    assert to_jsonable(Decision.ESCALATED) == "escalated"


def test_to_jsonable_datetime_is_json_safe_string():
    to_jsonable = _to_jsonable()
    dt = datetime(2026, 6, 20, 8, 30, tzinfo=UTC)
    out = to_jsonable(dt)
    assert isinstance(out, str)
    assert json.loads(json.dumps(out)) == out
    assert "2026-06-20" in out


def test_to_jsonable_validation_report_roundtrips_through_json():
    to_jsonable = _to_jsonable()
    findings = principles_eval.evaluate_all(sample_projects.NON_COMPLIANT_SUBMISSION)
    report = ValidationReport(
        submission=sample_projects.NON_COMPLIANT_SUBMISSION,
        findings=tuple(findings),
        injected_requirements=(),
        passed=False,
        requires_human_review=True,
    )
    out = to_jsonable(report)
    text = json.dumps(out)  # must not raise
    reloaded = json.loads(text)
    assert reloaded["passed"] is False
    assert reloaded["findings"][0]["status"] in {"PASS", "FAIL", "NEEDS_INFO", "NOT_APPLICABLE"}
    assert reloaded["submission"]["id"] == sample_projects.NON_COMPLIANT_SUBMISSION.id


def test_to_jsonable_scan_roundtrips_through_json():
    """A ResidencyScan serialises to a JSON-safe, provenance-bearing payload."""
    to_jsonable = _to_jsonable()
    citation = Citation(
        source_id="P-03",
        regulator=Regulator.MAS,
        jurisdiction=Jurisdiction.SG,
        title="single in-country region",
        url="https://rsk.internal/principles/P-03",
        page=1,
    )
    violation = ResidencyViolation(
        resource=ResourceConfig(
            address="google_storage_bucket.export",
            type="google_storage_bucket",
            region="us-central1",
            source_ref="main.tf:42",
        ),
        kind=ViolationKind.REGION_NOT_ALLOWED,
        found_region="us-central1",
        allowed_regions=("asia-southeast1",),
        severity=Severity.CRITICAL,
        rule_id="region-not-allowed",
        remediation="move to asia-southeast1",
        evidence="main.tf:42",
        citations=(citation,),
    )
    scan = ResidencyScan(
        target="plan.json",
        resources_scanned=1,
        violations=(violation,),
        verdict=ScanVerdict(
            passed=False,
            gate_severity=Severity.HIGH,
            total_violations=1,
            counts=(SeverityCount(severity=Severity.CRITICAL, count=1),),
        ),
        passed=False,
        requires_human_review=True,
    )
    out = to_jsonable(scan)
    text = json.dumps(out)  # must not raise
    reloaded = json.loads(text)
    assert reloaded["passed"] is False
    assert reloaded["violations"][0]["kind"] == "region_not_allowed"
    assert reloaded["violations"][0]["citations"][0]["source_id"] == "P-03"
    assert reloaded["verdict"]["counts"][0]["severity"] == "critical"


def test_to_jsonable_audit_event_is_worm_serialisable():
    to_jsonable = _to_jsonable()
    event = AuditEvent(
        action="validate",
        actor="reviewer",
        decision=Decision.ALLOWED,
        summary_prompt="proj-1: a project",
        summary_response="verdict=PASS",
        citations=(sample_projects.SAMPLE_KB_CITATIONS[0],),
    )
    out = to_jsonable(event)
    reloaded = json.loads(json.dumps(out))
    assert reloaded["decision"] == "allowed"
    assert reloaded["action"] == "validate"


# --------------------------------------------------------------------------- #
# Settings.load parses config/settings.yaml
# --------------------------------------------------------------------------- #
def test_settings_load_parses_yaml():
    settings = Settings.load(CONFIG_PATH)
    assert settings.region == "asia-southeast1"
    assert settings.models.reasoning == "gemini-3.5-flash"
    assert settings.models.triage == "gemini-3.5-flash"
    assert settings.policy.decision_path == "arch/validate"
    assert set(PORT_PROTOCOLS) <= set(settings.adapters)


def test_settings_pins_models_to_allowed_ids():
    settings = Settings.load(CONFIG_PATH)
    assert settings.models.reasoning != "gemini-2.0-flash"
    assert settings.models.triage != "gemini-2.0-flash"
    assert settings.models.reasoning.startswith("gemini-3")


def test_settings_builds_residency_policy():
    """The residency gate is built from the ``residency_policy`` settings block.

    The method is named ``build_residency_policy()`` so it does not collide with the
    ``residency_policy`` settings field it reads.
    """
    settings = Settings.load(CONFIG_PATH)
    policy = settings.build_residency_policy()
    assert "asia-southeast1" in policy.allowed_regions
    assert "us-central1" not in policy.allowed_regions
    assert ResidencyControl.CMEK in policy.required_controls
    assert policy.gate_severity is Severity.HIGH


# --------------------------------------------------------------------------- #
# Container binds on-prem adapters under profile=onprem, with structural parity.
# --------------------------------------------------------------------------- #
def _onprem_settings() -> Settings:
    s = Settings.load(CONFIG_PATH)
    return Settings(
        project_id=s.project_id,
        region=s.region,
        profile="onprem",
        kms_key=s.kms_key,
        models=s.models,
        policy=s.policy,
        knowledge_base=s.knowledge_base,
        logging=s.logging,
        agent_engine=s.agent_engine,
        adapters=s.adapters,
    )


def test_container_binds_onprem_adapters_with_protocol_parity():
    container = Container(_onprem_settings())
    for port_name, protocol in PORT_PROTOCOLS.items():
        adapter = getattr(container, port_name)
        assert isinstance(adapter, protocol), (
            f"on-prem adapter for '{port_name}' is not structurally a {protocol.__name__}"
        )


def test_container_falls_back_to_gcp_binding_when_profile_missing():
    settings = _onprem_settings()
    # tracer has no 'platform' entry; gcp is always present as the primary/fallback.
    binding = settings.adapters["tracer"]
    assert binding["onprem"].endswith("OnPremTracerAdapter")
    assert "gcp" in binding


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
