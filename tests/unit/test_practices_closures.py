"""Static guardrails for repository practice contracts closed in this change."""

from pathlib import Path

import pytest
import yaml

from architecture_validator.adapters.gcp.opa_policy import OpaPolicyAdapter
from architecture_validator.config import PolicySettings, Settings
from architecture_validator.domain.hitl import ReviewPolicy
from architecture_validator.domain.models import CheckStatus, PrincipleFinding, Severity

ROOT = Path(__file__).resolve().parents[2]


def test_reference_policy_matches_shipped_yaml() -> None:
    assert Settings.load(ROOT / "config/settings.yaml").policy == PolicySettings()


def test_policy_override_changes_region_and_review_floor_cannot_be_removed() -> None:
    settings = PolicySettings(allowed_regions=("fictional-region1",))
    finding = PrincipleFinding(
        principle_id="P-01",
        status=CheckStatus.PASS,
        rule_id="rule_p_01",
        evidence="fictional",
        severity=Severity.LOW,
    )
    assert settings.allowed_regions == ("fictional-region1",)
    assert ReviewPolicy().requires_review([finding]) is True
    with pytest.raises(ValueError, match="immutable production safety floor"):
        PolicySettings(review_all_reports=False)


def test_authority_boundary_crosswalk_and_ci_contracts_are_documented() -> None:
    authority = (ROOT / "docs/doc-authority.md").read_text(encoding="utf-8")
    spec = (ROOT / "SPEC.md").read_text(encoding="utf-8")
    compliance = (ROOT / "COMPLIANCE.md").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/ci.yaml").read_text(encoding="utf-8")
    assert authority.index("`SPEC.md`") < authority.index("`ARCHITECTURE.md`")
    assert "Kernel / vertical boundary" in spec
    assert "Adopter-owned regulatory crosswalk" in compliance
    assert "make demo-selftest" in workflow
    assert "make tf-validate" in workflow


def test_managed_opa_request_receives_same_bank_owned_regions(monkeypatch) -> None:
    captured = {}

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {"result": {"findings": []}}

    def post(url, *, json, timeout):
        captured.update(json)
        return Response()

    monkeypatch.setattr("architecture_validator.adapters.gcp.opa_policy.httpx.post", post)
    from architecture_validator.domain.models import ProjectSubmission
    from architecture_validator.domain.principles import all_principles

    settings = Settings(policy=PolicySettings(allowed_regions=("fictional-region1",)))
    OpaPolicyAdapter(settings).evaluate(
        ProjectSubmission("fictional", "Fictional", "Synthetic", "Synthetic"),
        all_principles(),
    )
    assert captured["input"]["policy"]["allowed_regions"] == ["fictional-region1"]


@pytest.mark.parametrize(
    "policy,match",
    [
        ({"unknown": 1}, "unknown policy settings"),
        ({"review_all_reports": "false"}, "must be true or false"),
        ({"review_all_reports": False}, "immutable production safety floor"),
        ({"allowed_regions": "asia-southeast1"}, "must be lists"),
        ({"allowed_regions": [""]}, "non-empty"),
        ({"high_severities": ["severe"]}, "invalid values"),
    ],
)
def test_policy_yaml_refuses_ambiguous_invalid_or_unknown_values(tmp_path, policy, match) -> None:
    config = tmp_path / "settings.yaml"
    config.write_text(yaml.safe_dump({"profile": "local", "policy": policy}), encoding="utf-8")
    with pytest.raises(ValueError, match=match):
        Settings.load(config)
