"""Review routing has a switch, default on, and behaves as a user expects.

The fleet's runtime-control contract (2026-09-24): review routing, the one cheap runtime control
this service has, is switched by one environment variable read in three states; off binds a
disabled router and says so at startup; on under a networked profile refuses to boot without
the console it routes to; and every caller that hands a validation report or a residency scan
to the router says what happened to it.

This service binds no guardrail and no PII redaction port, so it has no other switch.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from tests.conftest import LOOPBACK_PEER
from typer.testing import CliRunner

from architecture_validator import config as config_module
from architecture_validator.adapters.controls import (
    DisabledReviewRouter,
    RecordingReviewRouter,
    ReviewRouting,
)
from architecture_validator.api import deps
from architecture_validator.config import (
    HUMAN_REVIEW_URL_ENV,
    REVIEW_ROUTING_ENV,
    Container,
    ControlSwitches,
    LocalSettings,
    Settings,
    build_container,
    warn_switched_off,
)
from architecture_validator.envread import ConfiguredEmptyError

_PROFILE_ENV = "ARCH_VALIDATOR_PROFILE"
_CONSOLE = "https://review.example.test"

_SUBMISSION: dict[str, Any] = {
    "id": "proj-1",
    "name": "Onboarding assistant (FICTIONAL)",
    "description": "A demo submission",
    "requirements": "chat over policy",
}

_OUT_OF_REGION: dict[str, Any] = {
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


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (REVIEW_ROUTING_ENV, HUMAN_REVIEW_URL_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(_PROFILE_ENV, "local")


# --------------------------------------------------------------------------- #
# Three states
# --------------------------------------------------------------------------- #
def test_routing_is_on_when_nothing_is_said() -> None:
    assert Settings.load().controls == ControlSwitches(review_routing=True)


def test_routing_switched_off_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "false")
    assert Settings.load().controls.switched_off() == (REVIEW_ROUTING_ENV,)


def test_an_emptied_switch_refuses_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "")
    with pytest.raises(ConfiguredEmptyError, match=REVIEW_ROUTING_ENV):
        Settings.load()


def test_an_unrecognised_switch_refuses_at_load(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "sometimes")
    with pytest.raises(ValueError, match=REVIEW_ROUTING_ENV):
        Settings.load()


# --------------------------------------------------------------------------- #
# Off binds the disabled router, and says so
# --------------------------------------------------------------------------- #
def _local(**switches: bool) -> Settings:
    base = Settings.load("config/settings.yaml")
    return Settings(
        profile="local",
        policy=base.policy,
        knowledge_base=base.knowledge_base,
        local=LocalSettings(db_path=":memory:", audit_path=":memory:"),
        adapters=base.adapters,
        controls=ControlSwitches(**switches),
    )


def test_off_binds_the_disabled_router() -> None:
    assert isinstance(Container(_local(review_routing=False)).review_router, DisabledReviewRouter)


def test_on_binds_the_profile_router() -> None:
    assert not isinstance(Container(_local()).review_router, DisabledReviewRouter)


def test_a_process_with_routing_off_says_so_once_at_startup(
    caplog: pytest.LogCaptureFixture,
) -> None:
    warn_switched_off.cache_clear()
    settings = _local(review_routing=False)
    with caplog.at_level(logging.WARNING, logger="architecture_validator.config"):
        build_container(settings)
        build_container(settings)
    assert caplog.text.count(REVIEW_ROUTING_ENV) == 1


# --------------------------------------------------------------------------- #
# On has to work: checked at boot under a networked profile
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("profile", ["gcp", "platform"])
def test_routing_on_without_a_console_refuses_at_boot(
    monkeypatch: pytest.MonkeyPatch, profile: str
) -> None:
    monkeypatch.setenv(_PROFILE_ENV, profile)
    with pytest.raises(ConfiguredEmptyError, match=HUMAN_REVIEW_URL_ENV):
        Settings.load()


@pytest.mark.parametrize("profile", ["gcp", "platform"])
def test_routing_on_with_a_console_loads(monkeypatch: pytest.MonkeyPatch, profile: str) -> None:
    monkeypatch.setenv(_PROFILE_ENV, profile)
    monkeypatch.setenv(HUMAN_REVIEW_URL_ENV, _CONSOLE)
    assert Settings.load().controls.review_routing is True


def test_routing_stated_off_under_gcp_needs_no_console(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(_PROFILE_ENV, "gcp")
    monkeypatch.setenv(REVIEW_ROUTING_ENV, "off")
    assert Settings.load().controls.review_routing is False


def test_an_emptied_console_refuses_rather_than_reading_as_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(_PROFILE_ENV, "gcp")
    monkeypatch.setenv(HUMAN_REVIEW_URL_ENV, "")
    with pytest.raises(ConfiguredEmptyError, match=HUMAN_REVIEW_URL_ENV):
        Settings.load()


def test_the_local_profile_needs_no_console() -> None:
    assert Settings.load().controls.review_routing is True


# --------------------------------------------------------------------------- #
# The four routing outcomes
# --------------------------------------------------------------------------- #
class _Accepting:
    def route(self, item: object, *, maker: str, tenant: str = "") -> None:
        return None


class _Refusing:
    def route(self, item: object, *, maker: str, tenant: str = "") -> None:
        raise ConnectionError("console unreachable")


def test_routing_outcomes_take_each_of_their_four_values() -> None:
    nothing_required = RecordingReviewRouter(_Accepting())
    assert nothing_required.outcome is ReviewRouting.NOT_REQUIRED

    routed = RecordingReviewRouter(_Accepting())
    routed.route(object(), maker="m")  # type: ignore[arg-type]
    assert routed.outcome is ReviewRouting.ROUTED

    off = RecordingReviewRouter(DisabledReviewRouter(_local()))
    off.route(object(), maker="m")  # type: ignore[arg-type]
    assert off.outcome is ReviewRouting.OFF

    failed = RecordingReviewRouter(_Refusing())
    failed.route(object(), maker="m")  # type: ignore[arg-type]
    assert failed.outcome is ReviewRouting.FAILED


def test_a_failed_hand_off_is_reported_and_logged_never_raised(
    caplog: pytest.LogCaptureFixture,
) -> None:
    failed = RecordingReviewRouter(_Refusing())
    with caplog.at_level(logging.WARNING, logger="architecture_validator.adapters.controls"):
        failed.route(object(), maker="m")  # type: ignore[arg-type]
    assert failed.outcome is ReviewRouting.FAILED
    assert "ConnectionError" in caplog.text


def test_one_failure_among_several_hand_offs_is_what_the_caller_reports() -> None:
    class _FailsSecond:
        calls = 0

        def route(self, item: object, *, maker: str, tenant: str = "") -> None:
            self.calls += 1
            if self.calls == 2:
                raise TimeoutError

    router = RecordingReviewRouter(_FailsSecond())
    for _ in range(3):
        router.route(object(), maker="m")  # type: ignore[arg-type]
    assert router.outcome is ReviewRouting.FAILED


# --------------------------------------------------------------------------- #
# Every caller reports what happened to the item it handed off
# --------------------------------------------------------------------------- #
def _container(*, router: object | None = None, **switches: bool) -> Container:
    container = Container(_local(**switches))
    if router is not None:
        container.__dict__["review_router"] = router  # the cached_property's slot
    return container


def _post(
    monkeypatch: pytest.MonkeyPatch, container: Container, path: str, body: dict[str, Any]
) -> dict[str, Any]:
    from architecture_validator.api.app import app

    monkeypatch.setattr(deps, "get_container", lambda: container)
    response = TestClient(app, client=LOOPBACK_PEER).post(path, json=body)
    assert response.status_code == 200, response.text
    payload: dict[str, Any] = response.json()
    return payload


def test_validate_reports_a_routed_report(monkeypatch: pytest.MonkeyPatch) -> None:
    body = _post(monkeypatch, _container(), "/validate", {"submission": _SUBMISSION})
    assert body["requires_human_review"] is True
    assert body["review_routing"] == "routed"


def test_validate_reports_routing_off(monkeypatch: pytest.MonkeyPatch) -> None:
    body = _post(
        monkeypatch, _container(review_routing=False), "/validate", {"submission": _SUBMISSION}
    )
    assert body["review_routing"] == "off"


def test_validate_reports_a_failed_hand_off_instead_of_failing_the_report(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    body = _post(
        monkeypatch, _container(router=_Refusing()), "/validate", {"submission": _SUBMISSION}
    )
    assert body["review_routing"] == "failed"


def test_scan_reports_a_failed_hand_off(monkeypatch: pytest.MonkeyPatch) -> None:
    body = _post(monkeypatch, _container(router=_Refusing()), "/scan", _OUT_OF_REGION)
    assert body["passed"] is False
    assert body["review_routing"] == "failed"


def test_the_agent_tool_reports_the_hand_off() -> None:
    from architecture_validator.agent import tools

    payload = tools.validate_project(_SUBMISSION, settings=_local(review_routing=False))
    assert payload["review_routing"] == "off"


def test_the_mcp_validate_tool_reports_the_hand_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from architecture_validator.mcp import server as mcp_server

    container = _container(router=_Refusing())
    monkeypatch.setattr(deps, "get_container", lambda: container)
    payload = mcp_server.build_handlers(actor="svc:test")["validate_project"](
        submission=_SUBMISSION
    )
    assert payload["review_routing"] == "failed"


def test_the_cli_validate_command_says_where_the_report_went(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from architecture_validator.cli.main import app as cli

    container = _container(review_routing=False)
    monkeypatch.setattr(config_module, "build_container", lambda *_a, **_k: container)
    submission = tmp_path / "submission.json"
    submission.write_text(json.dumps(_SUBMISSION))
    result = CliRunner().invoke(cli, ["validate", str(submission)])
    assert result.exit_code == 0, result.output
    assert "human review hand-off: off" in result.output


def test_the_cli_scan_command_says_where_the_scan_went(monkeypatch: pytest.MonkeyPatch) -> None:
    from architecture_validator.cli.main import app as cli

    container = _container(router=_Refusing())
    monkeypatch.setattr(config_module, "build_container", lambda *_a, **_k: container)
    result = CliRunner().invoke(cli, ["scan", "--plan", "tests/fixtures/sample_plan.json"])
    assert "human review hand-off: failed" in result.output
