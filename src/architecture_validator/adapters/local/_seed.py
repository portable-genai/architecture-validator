"""Built-in synthetic regulatory corpus for the ``local`` profile.

A tiny, clearly-fictional set of MAS / HKMA / APRA passages (with page-level
:class:`Citation` provenance) so the local knowledge-base adapter has regulatory context
to ground the unmet-principle findings on out of the box, and the end-to-end CLI smoke
run returns a real cited artifact with no external corpus. The text is invented; the
source ids / titles are plausible but fictional and must not be treated as the real
instruments.

This mirrors ``tests/fixtures/sample_projects.SAMPLE_KB_CITATIONS`` so the local
adapters and the unit-test fixtures share one deterministic corpus, but it lives under
``src`` (not ``tests``) so the shipped package can seed itself without importing the
test tree.
"""

from __future__ import annotations

from ...domain.models import Citation, Jurisdiction, Regulator
from ...domain.residency.models import ResourceConfig

# A small, deterministic corpus. Page numbers are required for compliance provenance.
SEED_CITATIONS: tuple[Citation, ...] = (
    Citation(
        source_id="mas-trm-guidelines",
        regulator=Regulator.MAS,
        jurisdiction=Jurisdiction.SG,
        title="MAS Technology Risk Management Guidelines",
        url="https://example.test/mas/trm",
        version="2021",
        page=42,
        snippet=(
            "Pin data and processing to an approved in-country region, encrypt with "
            "institution-managed keys, and gate model promotion on an evaluation suite."
        ),
        score=0.93,
    ),
    Citation(
        source_id="hkma-genai-circular",
        regulator=Regulator.HKMA,
        jurisdiction=Jurisdiction.HK,
        title="HKMA Circular on Generative AI Risk Management",
        url="https://example.test/hkma/genai",
        version="2024",
        page=7,
        snippet=(
            "Authorized institutions should keep a human in the loop for consequential "
            "decisions and retain immutable audit records with traceable citations."
        ),
        score=0.88,
    ),
    Citation(
        source_id="apra-cps-230",
        regulator=Regulator.APRA,
        jurisdiction=Jurisdiction.AU,
        title="APRA CPS 230 Operational Risk Management",
        url="https://example.test/apra/cps230",
        version="2025",
        page=15,
        snippet=(
            "An APRA-regulated entity must maintain resilience controls (kill-switch, "
            "circuit breaker) and document and test an exit plan for material services."
        ),
        score=0.82,
    ),
)


# --------------------------------------------------------------------------- #
# Built-in synthetic resource estate for the ``local`` profile live scanner.
#
# A tiny, clearly-fictional set of deployed resources (a mix of compliant and violating
# ones) so the local IaCScannerPort has something to grade out of the box, and the
# end-to-end ``scan --project ...`` returns a real PASS/FAIL verdict with violations, with
# no cloud and no Google Cloud SDK. Two clean resources in Singapore (asia-southeast1) and
# two planted violations (an out-of-region bucket, a public SQL instance). The addresses /
# regions are invented but plausible and must not be treated as a real estate.
# --------------------------------------------------------------------------- #
SEED_RESOURCES: tuple[ResourceConfig, ...] = (
    ResourceConfig(
        address="google_storage_bucket.kyc",
        type="google_storage_bucket",
        region="asia-southeast1",
        attributes={
            "kms_key_name": "projects/p/locations/asia-southeast1/keyRings/r/cryptoKeys/k",
            "public_access_prevention": "enforced",
            "service_perimeter": "accessPolicies/123/servicePerimeters/sg",
        },
        source_ref="//storage.googleapis.com/projects/p/buckets/kyc",
    ),
    ResourceConfig(
        address="google_alloydb_cluster.ledger",
        type="google_alloydb_cluster",
        region="asia-southeast1",
        attributes={
            "kms_key_name": "projects/p/locations/asia-southeast1/keyRings/r/cryptoKeys/k",
            "ipv4_enabled": "false",
            "service_perimeter": "accessPolicies/123/servicePerimeters/sg",
        },
        source_ref="//alloydb.googleapis.com/projects/p/clusters/ledger",
    ),
    ResourceConfig(
        address="google_storage_bucket.export",
        type="google_storage_bucket",
        region="us-central1",
        attributes={
            "kms_key_name": "projects/p/locations/us-central1/keyRings/r/cryptoKeys/k",
            "public_access_prevention": "enforced",
            "service_perimeter": "accessPolicies/123/servicePerimeters/us",
        },
        source_ref="//storage.googleapis.com/projects/p/buckets/export",
    ),
    ResourceConfig(
        address="google_sql_database_instance.public",
        type="google_sql_database_instance",
        region="asia-southeast1",
        attributes={
            "kms_key_name": "projects/p/locations/asia-southeast1/keyRings/r/cryptoKeys/k",
            "ipv4_enabled": "true",
            "service_perimeter": "accessPolicies/123/servicePerimeters/sg",
        },
        source_ref="//sqladmin.googleapis.com/projects/p/instances/public",
    ),
)
