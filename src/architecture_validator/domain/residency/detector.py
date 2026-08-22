"""ViolationDetector — the deterministic residency rules engine.

Given a list of :class:`ResourceConfig` (from the Terraform plan / ``.tf`` parser, or the
live Cloud Asset Inventory scanner) and a :class:`ResidencyPolicy`, it applies pure,
testable rules and returns the :class:`ResidencyViolation` list. **No LLM, no network, no
Google Cloud** — the detector is fully deterministic so the same plan always grades the
same way, which is what makes it trustworthy as a CI gate.

Rules:
* region not in ``allowed_regions``           -> REGION_NOT_ALLOWED
* region missing / unknown on a data resource -> UNKNOWN_REGION
* global / multi-region location              -> GLOBAL_ENDPOINT
* data resource with no regional CMEK attr    -> MISSING_CMEK
* data resource with a public endpoint / IP   -> PUBLIC_EGRESS
* a required control otherwise absent         -> RESIDENCY_CONTROL_MISSING

Pure domain code — talks only to models, no Google Cloud / ADK imports.
"""

from __future__ import annotations

from ..models import Citation, Jurisdiction, Regulator, Severity
from .models import (
    ResidencyControl,
    ResidencyPolicy,
    ResidencyViolation,
    ResourceConfig,
    ViolationKind,
)

# --------------------------------------------------------------------------- #
# Resource taxonomy
# --------------------------------------------------------------------------- #
# Resource types that hold or move *data* and therefore carry the full residency
# control set (CMEK, VPC-SC, no public egress, no global endpoint). A resource not in
# this set is still region-checked, but missing data controls are not held against it.
_DATA_RESOURCE_TYPES: frozenset[str] = frozenset(
    {
        "google_storage_bucket",
        "google_bigquery_dataset",
        "google_bigquery_table",
        "google_sql_database_instance",
        "google_alloydb_cluster",
        "google_alloydb_instance",
        "google_spanner_instance",
        "google_spanner_database",
        "google_firestore_database",
        "google_bigtable_instance",
        "google_pubsub_topic",
        "google_redis_instance",
        "google_filestore_instance",
        "google_dataproc_cluster",
        "google_kms_key_ring",
        "google_logging_project_bucket_config",
        "google_discovery_engine_data_store",
        "google_vertex_ai_index",
    }
)

# Region / location values that denote a global or multi-region endpoint (residency
# leak): the data is not pinned to a single in-country region.
_GLOBAL_REGION_TOKENS: frozenset[str] = frozenset(
    {
        "global",
        "us",
        "eu",
        "asia",
        "us-central1-and-multi",
        "nam",
        "multi-region",
    }
)

# Attribute keys that, when present and non-empty, evidence a regional CMEK.
_CMEK_ATTR_KEYS: tuple[str, ...] = (
    "kms_key_name",
    "kms_key_id",
    "encryption_key",
    "customer_managed_key",
    "cmek_key",
    "kms_key",
)

# Attribute keys whose value evidences a public endpoint / open egress.
_PUBLIC_EGRESS_TRUE_KEYS: tuple[str, ...] = (
    "public_access",
    "publicly_accessible",
    "ipv4_enabled",
    "assign_public_ip",
    "allow_public_egress",
)
# Attribute keys whose value (when "false"/absent) evidences public egress is *not*
# prevented. (e.g. public_access_prevention should be "enforced".)
_PUBLIC_PREVENTION_KEY = "public_access_prevention"

# Attribute keys that evidence a VPC Service Controls perimeter membership.
_VPC_SC_ATTR_KEYS: tuple[str, ...] = (
    "service_perimeter",
    "vpc_sc_perimeter",
    "access_policy",
)

_TRUE_VALUES: frozenset[str] = frozenset({"true", "1", "yes", "enabled"})
_FALSE_VALUES: frozenset[str] = frozenset({"false", "0", "no", "disabled"})


def _is_truthy(value: str | None) -> bool:
    return value is not None and value.strip().lower() in _TRUE_VALUES


# --------------------------------------------------------------------------- #
# Citations — every violation cites the residency principle it breaches plus the
# regulator whose in-country expectation it offends.
# --------------------------------------------------------------------------- #
_P01 = Citation(
    source_id="P-01",
    regulator=Regulator.CROSS,
    jurisdiction=Jurisdiction.GLOBAL,
    title="General Principle P-01 — private-by-default networking (VPC-SC, no public egress)",
    url="https://rsk.internal/principles/P-01",
    version="1.0",
)
_P03 = Citation(
    source_id="P-03",
    regulator=Regulator.CROSS,
    jurisdiction=Jurisdiction.GLOBAL,
    title="General Principle P-03 — single in-country region (data residency)",
    url="https://rsk.internal/principles/P-03",
    version="1.0",
)
_P10 = Citation(
    source_id="P-10",
    regulator=Regulator.CROSS,
    jurisdiction=Jurisdiction.GLOBAL,
    title="General Principle P-10 — customer-managed encryption keys (CMEK)",
    url="https://rsk.internal/principles/P-10",
    version="1.0",
)

# A region -> regulator residency-expectation citation (the in-country supervisor).
_REGION_REGULATOR: dict[str, Citation] = {
    "asia-southeast1": Citation(
        source_id="mas-trm-guidelines",
        regulator=Regulator.MAS,
        jurisdiction=Jurisdiction.SG,
        title="MAS Technology Risk Management Guidelines (data residency expectations)",
        url="https://rsk.internal/reg/mas-trm",
        version="2021",
    ),
    "asia-east2": Citation(
        source_id="hkma-cloud-spm",
        regulator=Regulator.HKMA,
        jurisdiction=Jurisdiction.HK,
        title="HKMA SA-2 Outsourcing (Cloud Computing) — data residency expectations",
        url="https://rsk.internal/reg/hkma-sa2",
        version="2022",
    ),
    "australia-southeast1": Citation(
        source_id="apra-cps-230",
        regulator=Regulator.APRA,
        jurisdiction=Jurisdiction.AU,
        title="APRA CPS 230 Operational Risk Management — data residency expectations",
        url="https://rsk.internal/reg/apra-cps230",
        version="2025",
    ),
    "australia-southeast2": Citation(
        source_id="apra-cps-230",
        regulator=Regulator.APRA,
        jurisdiction=Jurisdiction.AU,
        title="APRA CPS 230 Operational Risk Management — data residency expectations",
        url="https://rsk.internal/reg/apra-cps230",
        version="2025",
    ),
    "asia-northeast1": Citation(
        source_id="fsa-jp-system-risk",
        regulator=Regulator.FSA,
        jurisdiction=Jurisdiction.JP,
        title="FSA Guidelines for System Risk Management — data residency expectations",
        url="https://rsk.internal/reg/fsa-system-risk",
        version="2023",
    ),
}


def _regulator_citation_for(allowed_regions: frozenset[str]) -> Citation:
    """Pick a representative in-country regulator citation for the allowed set.

    Prefers Singapore (asia-southeast1) as the default residency, otherwise the first
    allowed region with a known supervisor; falls back to the MAS citation.
    """
    if "asia-southeast1" in allowed_regions:
        return _REGION_REGULATOR["asia-southeast1"]
    for region in sorted(allowed_regions):
        if region in _REGION_REGULATOR:
            return _REGION_REGULATOR[region]
    return _REGION_REGULATOR["asia-southeast1"]


class ViolationDetector:
    """Apply a :class:`ResidencyPolicy` to resources and return the violations.

    Constructed with the policy so the same detector can grade many scans; ``detect``
    is pure (no side effects) and deterministic.
    """

    def __init__(self, policy: ResidencyPolicy | None = None) -> None:
        self._policy = policy or ResidencyPolicy()

    @property
    def policy(self) -> ResidencyPolicy:
        return self._policy

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def detect(self, resources: list[ResourceConfig]) -> list[ResidencyViolation]:
        """Return every residency violation across ``resources`` (in input order)."""
        violations: list[ResidencyViolation] = []
        for resource in resources:
            violations.extend(self._detect_one(resource))
        return violations

    # ------------------------------------------------------------------ #
    # Per-resource rules
    # ------------------------------------------------------------------ #
    def _detect_one(self, resource: ResourceConfig) -> list[ResidencyViolation]:
        out: list[ResidencyViolation] = []
        region = (resource.region or "").strip() or None
        is_data = self._is_data_resource(resource)

        # 1) Region checks (apply to every resource).
        if region is None:
            if is_data:
                out.append(self._unknown_region(resource))
        elif self._is_global_region(region):
            out.append(self._global_endpoint(resource, region))
        elif not self._policy.is_region_allowed(region):
            out.append(self._region_not_allowed(resource, region))

        # 2) Data-control checks (only for data-bearing resources).
        if is_data:
            out.extend(self._control_checks(resource, region))
        return out

    def _control_checks(
        self, resource: ResourceConfig, region: str | None
    ) -> list[ResidencyViolation]:
        out: list[ResidencyViolation] = []
        attrs = resource.attributes

        if self._policy.requires(ResidencyControl.CMEK) and not self._has_cmek(attrs):
            out.append(self._missing_cmek(resource, region))

        if self._policy.requires(ResidencyControl.NO_PUBLIC_EGRESS) and self._has_public_egress(
            attrs
        ):
            out.append(self._public_egress(resource, region))

        if self._policy.requires(ResidencyControl.VPC_SC) and not self._has_vpc_sc(attrs):
            out.append(self._control_missing(resource, region, ResidencyControl.VPC_SC))
        return out

    # ------------------------------------------------------------------ #
    # Attribute predicates
    # ------------------------------------------------------------------ #
    def _is_data_resource(self, resource: ResourceConfig) -> bool:
        return resource.type in _DATA_RESOURCE_TYPES

    @staticmethod
    def _is_global_region(region: str) -> bool:
        return region.strip().lower() in _GLOBAL_REGION_TOKENS

    @staticmethod
    def _has_cmek(attrs: dict[str, str]) -> bool:
        return any(str(attrs.get(k, "")).strip() for k in _CMEK_ATTR_KEYS)

    @staticmethod
    def _has_public_egress(attrs: dict[str, str]) -> bool:
        # An explicit public flag set true is public egress.
        if any(_is_truthy(attrs.get(k)) for k in _PUBLIC_EGRESS_TRUE_KEYS):
            return True
        # public_access_prevention must be "enforced"; an explicit false-ish or
        # "inherited" value (when the key is present) is treated as not prevented.
        prevention = attrs.get(_PUBLIC_PREVENTION_KEY)
        if prevention is None:
            return False
        return prevention.strip().lower() in _FALSE_VALUES or prevention.strip().lower() == (
            "inherited"
        )

    @staticmethod
    def _has_vpc_sc(attrs: dict[str, str]) -> bool:
        return any(str(attrs.get(k, "")).strip() for k in _VPC_SC_ATTR_KEYS)

    # ------------------------------------------------------------------ #
    # Violation constructors
    # ------------------------------------------------------------------ #
    def _allowed_tuple(self) -> tuple[str, ...]:
        return tuple(sorted(self._policy.allowed_regions))

    def _region_citations(self) -> tuple[Citation, ...]:
        return (_P03, _regulator_citation_for(self._policy.allowed_regions))

    def _region_not_allowed(self, resource: ResourceConfig, region: str) -> ResidencyViolation:
        return ResidencyViolation(
            resource=resource,
            kind=ViolationKind.REGION_NOT_ALLOWED,
            found_region=region,
            allowed_regions=self._allowed_tuple(),
            severity=Severity.CRITICAL,
            rule_id="region-not-allowed",
            remediation=(
                f"Move {resource.address} to an allowed in-country region "
                f"({', '.join(self._allowed_tuple())}); it is currently in {region!r} (P-03)."
            ),
            evidence=resource.source_ref or resource.address,
            citations=self._region_citations(),
        )

    def _global_endpoint(self, resource: ResourceConfig, region: str) -> ResidencyViolation:
        return ResidencyViolation(
            resource=resource,
            kind=ViolationKind.GLOBAL_ENDPOINT,
            found_region=region,
            allowed_regions=self._allowed_tuple(),
            severity=Severity.CRITICAL,
            rule_id="global-endpoint",
            remediation=(
                f"{resource.address} uses a global / multi-region location ({region!r}); "
                f"pin it to a single in-country region ({', '.join(self._allowed_tuple())}) (P-03)."
            ),
            evidence=resource.source_ref or resource.address,
            citations=self._region_citations(),
        )

    def _unknown_region(self, resource: ResourceConfig) -> ResidencyViolation:
        return ResidencyViolation(
            resource=resource,
            kind=ViolationKind.UNKNOWN_REGION,
            found_region=None,
            allowed_regions=self._allowed_tuple(),
            severity=Severity.HIGH,
            rule_id="unknown-region",
            remediation=(
                f"{resource.address} declares no region / location; set an explicit "
                f"in-country region ({', '.join(self._allowed_tuple())}) so residency is "
                "verifiable (P-03)."
            ),
            evidence=resource.source_ref or resource.address,
            citations=self._region_citations(),
        )

    def _missing_cmek(self, resource: ResourceConfig, region: str | None) -> ResidencyViolation:
        return ResidencyViolation(
            resource=resource,
            kind=ViolationKind.MISSING_CMEK,
            found_region=region,
            allowed_regions=self._allowed_tuple(),
            severity=Severity.HIGH,
            rule_id="missing-cmek",
            remediation=(
                f"Attach a regional Customer-Managed Encryption Key to {resource.address} "
                "(e.g. set kms_key_name); Google-managed keys do not satisfy the residency "
                "control (P-10)."
            ),
            evidence=resource.source_ref or resource.address,
            citations=(_P10, _regulator_citation_for(self._policy.allowed_regions)),
        )

    def _public_egress(self, resource: ResourceConfig, region: str | None) -> ResidencyViolation:
        return ResidencyViolation(
            resource=resource,
            kind=ViolationKind.PUBLIC_EGRESS,
            found_region=region,
            allowed_regions=self._allowed_tuple(),
            severity=Severity.HIGH,
            rule_id="public-egress",
            remediation=(
                f"Remove the public endpoint / IP from {resource.address} and enforce "
                "public_access_prevention; data services must be private (P-01)."
            ),
            evidence=resource.source_ref or resource.address,
            citations=(_P01, _regulator_citation_for(self._policy.allowed_regions)),
        )

    def _control_missing(
        self,
        resource: ResourceConfig,
        region: str | None,
        control: ResidencyControl,
    ) -> ResidencyViolation:
        return ResidencyViolation(
            resource=resource,
            kind=ViolationKind.RESIDENCY_CONTROL_MISSING,
            found_region=region,
            allowed_regions=self._allowed_tuple(),
            severity=Severity.MEDIUM,
            rule_id=f"control-missing-{control.value}",
            remediation=(
                f"{resource.address} is not evidenced inside a VPC Service Controls "
                "perimeter; place it behind a perimeter (e.g. set service_perimeter) so "
                "data cannot egress the boundary (P-01)."
            ),
            evidence=resource.source_ref or resource.address,
            citations=(_P01, _regulator_citation_for(self._policy.allowed_regions)),
        )
