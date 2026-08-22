"""Synthetic resource configs + sample IaC for deterministic tests.

Nothing here touches Google Cloud. The resources mimic the shape of a parsed Terraform
plan (in-region and out-of-region, with and without residency controls) so unit tests
can assert the detector, the verdict, and the scan pipeline without any network or SDK.
The values are invented but plausible and clearly fictional.
"""

from __future__ import annotations

from pathlib import Path

from architecture_validator.domain.residency.models import ResourceConfig

FIXTURE_DIR = Path(__file__).resolve().parent
SAMPLE_PLAN_JSON = FIXTURE_DIR / "sample_plan.json"
SAMPLE_TF_DIR = FIXTURE_DIR / "sample_tf"

# --------------------------------------------------------------------------- #
# Compliant resources: in an allowed region (Singapore), with CMEK + VPC-SC and
# public access prevented. These must produce zero violations.
# --------------------------------------------------------------------------- #
COMPLIANT_BUCKET = ResourceConfig(
    address="google_storage_bucket.kyc",
    type="google_storage_bucket",
    region="asia-southeast1",
    attributes={
        "kms_key_name": "projects/p/locations/asia-southeast1/keyRings/r/cryptoKeys/k",
        "public_access_prevention": "enforced",
        "service_perimeter": "accessPolicies/123/servicePerimeters/sg",
    },
    source_ref="main.tf:10",
)

COMPLIANT_ALLOYDB = ResourceConfig(
    address="google_alloydb_cluster.ledger",
    type="google_alloydb_cluster",
    region="asia-southeast1",
    attributes={
        "kms_key_name": "projects/p/locations/asia-southeast1/keyRings/r/cryptoKeys/k",
        "ipv4_enabled": "false",
        "service_perimeter": "accessPolicies/123/servicePerimeters/sg",
    },
    source_ref="main.tf:30",
)

# A non-data resource (no residency controls expected), in an allowed region.
COMPLIANT_SERVICE = ResourceConfig(
    address="google_cloud_run_service.api",
    type="google_cloud_run_service",
    region="asia-southeast1",
    attributes={},
    source_ref="main.tf:50",
)

# --------------------------------------------------------------------------- #
# Violating resources — each plants a single, identifiable violation kind.
# --------------------------------------------------------------------------- #
# Region not in the allowed in-country set (us-central1).
BUCKET_WRONG_REGION = ResourceConfig(
    address="google_storage_bucket.export",
    type="google_storage_bucket",
    region="us-central1",
    attributes={
        "kms_key_name": "projects/p/locations/us-central1/keyRings/r/cryptoKeys/k",
        "public_access_prevention": "enforced",
        "service_perimeter": "accessPolicies/123/servicePerimeters/us",
    },
    source_ref="main.tf:70",
)

# Multi-region / global location.
BUCKET_GLOBAL = ResourceConfig(
    address="google_storage_bucket.global_logs",
    type="google_storage_bucket",
    region="US",
    attributes={
        "kms_key_name": "projects/p/locations/us/keyRings/r/cryptoKeys/k",
        "public_access_prevention": "enforced",
        "service_perimeter": "accessPolicies/123/servicePerimeters/x",
    },
    source_ref="main.tf:90",
)

# In-region but no CMEK attribute.
BUCKET_NO_CMEK = ResourceConfig(
    address="google_storage_bucket.no_cmek",
    type="google_storage_bucket",
    region="asia-southeast1",
    attributes={
        "public_access_prevention": "enforced",
        "service_perimeter": "accessPolicies/123/servicePerimeters/sg",
    },
    source_ref="main.tf:110",
)

# In-region, CMEK present, but a public endpoint enabled.
SQL_PUBLIC = ResourceConfig(
    address="google_sql_database_instance.public",
    type="google_sql_database_instance",
    region="asia-southeast1",
    attributes={
        "kms_key_name": "projects/p/locations/asia-southeast1/keyRings/r/cryptoKeys/k",
        "ipv4_enabled": "true",
        "service_perimeter": "accessPolicies/123/servicePerimeters/sg",
    },
    source_ref="main.tf:130",
)

# Data resource with no region at all.
DATASET_NO_REGION = ResourceConfig(
    address="google_bigquery_dataset.unscoped",
    type="google_bigquery_dataset",
    region=None,
    attributes={
        "kms_key_name": "projects/p/locations/asia-southeast1/keyRings/r/cryptoKeys/k",
        "public_access_prevention": "enforced",
        "service_perimeter": "accessPolicies/123/servicePerimeters/sg",
    },
    source_ref="main.tf:150",
)

# In-region, CMEK present, public prevented, but not inside a VPC-SC perimeter.
BUCKET_NO_VPCSC = ResourceConfig(
    address="google_storage_bucket.no_perimeter",
    type="google_storage_bucket",
    region="asia-southeast1",
    attributes={
        "kms_key_name": "projects/p/locations/asia-southeast1/keyRings/r/cryptoKeys/k",
        "public_access_prevention": "enforced",
    },
    source_ref="main.tf:170",
)

CLEAN_RESOURCES: tuple[ResourceConfig, ...] = (
    COMPLIANT_BUCKET,
    COMPLIANT_ALLOYDB,
    COMPLIANT_SERVICE,
)

VIOLATING_RESOURCES: tuple[ResourceConfig, ...] = (
    BUCKET_WRONG_REGION,
    BUCKET_GLOBAL,
    BUCKET_NO_CMEK,
    SQL_PUBLIC,
    DATASET_NO_REGION,
    BUCKET_NO_VPCSC,
)

MIXED_RESOURCES: tuple[ResourceConfig, ...] = CLEAN_RESOURCES + VIOLATING_RESOURCES

SAMPLE_ACTOR = "ci-bot@bank.test"
