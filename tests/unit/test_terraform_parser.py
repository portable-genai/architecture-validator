"""Unit tests for the file-based Terraform parser — the CI-gate workhorse (SPEC §5).

The plan-JSON parser and the .tf regex fallback are pure stdlib and must turn a bundled
sample plan / directory into normalised ResourceConfig objects the detector grades. End
to end (parse -> detect) the planted violations must be found and the clean resources
must not be flagged.
"""

from __future__ import annotations

import pytest
from tests.fixtures import sample_resources as f

from architecture_validator.domain.errors import ScanTargetError
from architecture_validator.domain.residency.detector import ViolationDetector
from architecture_validator.domain.residency.models import ViolationKind
from architecture_validator.pipelines import terraform


# --------------------------------------------------------------------------- #
# Plan JSON
# --------------------------------------------------------------------------- #
def test_parse_plan_json_extracts_all_resources_including_child_modules():
    resources = terraform.parse_plan_json(f.SAMPLE_PLAN_JSON)
    addresses = {r.address for r in resources}
    # Root module + nested child_module resources are all present.
    assert "google_storage_bucket.kyc" in addresses
    assert "google_storage_bucket.export" in addresses
    assert "module.data.google_bigquery_dataset.global_logs" in addresses
    assert "module.data.google_storage_bucket.no_cmek" in addresses
    assert len(resources) == 6


def test_parse_plan_json_extracts_region_and_controls():
    resources = {r.address: r for r in terraform.parse_plan_json(f.SAMPLE_PLAN_JSON)}
    kyc = resources["google_storage_bucket.kyc"]
    assert kyc.region == "asia-southeast1"
    # CMEK key is lifted from the nested encryption block.
    assert kyc.attributes.get("kms_key_name")
    # The SQL instance's nested ipv4_enabled is captured as a public-egress signal.
    sql = resources["google_sql_database_instance.public"]
    assert sql.attributes.get("ipv4_enabled") == "true"


def test_parse_plan_then_detect_finds_planted_violations():
    resources = terraform.parse_plan_json(f.SAMPLE_PLAN_JSON)
    violations = ViolationDetector().detect(resources)
    kinds = {(v.resource.address, v.kind) for v in violations}
    assert ("google_storage_bucket.export", ViolationKind.REGION_NOT_ALLOWED) in kinds
    assert ("module.data.google_bigquery_dataset.global_logs", ViolationKind.GLOBAL_ENDPOINT) in (
        kinds
    )
    assert ("module.data.google_storage_bucket.no_cmek", ViolationKind.MISSING_CMEK) in kinds
    assert ("google_sql_database_instance.public", ViolationKind.PUBLIC_EGRESS) in kinds
    # The compliant kyc bucket and the cloud run service produce no violations.
    flagged = {v.resource.address for v in violations}
    assert "google_storage_bucket.kyc" not in flagged
    assert "google_cloud_run_service.api" not in flagged


def test_parse_plan_json_rejects_non_plan_document(tmp_path):
    bad = tmp_path / "not_a_plan.json"
    bad.write_text('{"hello": "world"}', encoding="utf-8")
    with pytest.raises(ScanTargetError):
        terraform.parse_plan_json(bad)


def test_parse_plan_json_rejects_malformed_json(tmp_path):
    bad = tmp_path / "broken.json"
    bad.write_text("{not json", encoding="utf-8")
    with pytest.raises(ScanTargetError):
        terraform.parse_plan_json(bad)


# --------------------------------------------------------------------------- #
# .tf regex fallback
# --------------------------------------------------------------------------- #
def test_parse_tf_dir_extracts_resources_and_source_refs():
    resources = {r.address: r for r in terraform.parse_tf_dir(f.SAMPLE_TF_DIR)}
    assert "google_storage_bucket.kyc" in resources
    assert "google_storage_bucket.export" in resources
    export = resources["google_storage_bucket.export"]
    assert export.region == "us-central1"
    # source_ref carries file:line for the reviewer.
    assert ":" in export.source_ref


def test_parse_tf_then_detect_finds_region_violation():
    resources = terraform.parse_tf_dir(f.SAMPLE_TF_DIR)
    violations = ViolationDetector().detect(resources)
    kinds = {(v.resource.address, v.kind) for v in violations}
    assert ("google_storage_bucket.export", ViolationKind.REGION_NOT_ALLOWED) in kinds


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
def test_parse_target_dispatches_on_suffix():
    assert terraform.parse_target(f.SAMPLE_PLAN_JSON)
    assert terraform.parse_target(f.SAMPLE_TF_DIR)


def test_parse_target_missing_path_raises():
    with pytest.raises(ScanTargetError):
        terraform.parse_target("does/not/exist.json")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
