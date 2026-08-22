"""Live GCP smoke test — deselected in CI via ``-m 'not integration'``.

Requires real Google Cloud credentials and the ``[gcp]`` extra installed. It is skipped
automatically when ``GOOGLE_CLOUD_PROJECT`` is unset, so the default on-prem / test
profile (no Google Cloud SDK) never executes any of this. It constructs the managed-service
adapters in ``asia-southeast1`` and does one trivial liveness check per adapter.
"""

from __future__ import annotations

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not os.environ.get("GOOGLE_CLOUD_PROJECT"),
        reason="set GOOGLE_CLOUD_PROJECT (and install the [gcp] extra) to run GCP smoke tests",
    ),
]


@pytest.fixture(scope="module")
def gcp_settings():
    from architecture_validator.config import Settings

    settings = Settings.load("config/settings.yaml")
    return Settings(
        project_id=os.environ["GOOGLE_CLOUD_PROJECT"],
        region="asia-southeast1",
        profile="gcp",
        kms_key=settings.kms_key,
        models=settings.models,
        policy=settings.policy,
        knowledge_base=settings.knowledge_base,
        logging=settings.logging,
        agent_engine=settings.agent_engine,
        adapters=settings.adapters,
    )


@pytest.fixture(scope="module")
def container(gcp_settings):
    from architecture_validator.config import Container

    return Container(gcp_settings)


def test_region_is_singapore(gcp_settings):
    assert gcp_settings.region == "asia-southeast1"


def test_registry_self_card(container):
    card = container.registry.get("architecture-validator")
    assert card is not None
    assert card.skills


def test_knowledge_base_liveness(container):
    citations = container.knowledge_base.retrieve("MAS cloud outsourcing", top_k=2)
    assert isinstance(citations, list)


def test_tool_catalog_lists_governed_tools(container):
    tools = container.tool_catalog.list_tools()
    assert {t.name for t in tools} >= {"validate_project", "list_principles"}


def test_cloud_asset_scanner_constructs(container):
    """The live-scan source (Cloud Asset Inventory + SCC) constructs on gcp."""
    scanner = container.scanner
    assert scanner is not None


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q", "-m", "integration"]))
