"""Residency-specific domain models.

The heart of the residency-scan hexagon. It reuses the shared kernel types from
:mod:`architecture_validator.domain.models` (``Citation``, ``Severity``, ``utcnow``) and defines
only the residency-specific types here: the policy, the resource/violation/verdict/scan
artifacts, and ``ResidencyDecision`` (the scan-native audit decision, kept distinct from
C3's ``Decision``). No dependency on Google Cloud, ADK, FastAPI — standard library only.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from hex_service_kit import StrEnum

from ..models import Citation, Severity, utcnow


# --------------------------------------------------------------------------- #
# Residency policy — the heart of the residency scan.
# --------------------------------------------------------------------------- #
class ResidencyControl(StrEnum):
    """Required residency controls a data-bearing resource must carry (P-01 / P-03)."""

    CMEK = "cmek"  # regional Customer-Managed Encryption Key present
    VPC_SC = "vpc_sc"  # inside a VPC Service Controls perimeter
    NO_PUBLIC_EGRESS = "no_public_egress"  # no public IP / open egress
    NO_GLOBAL_ENDPOINT = "no_global_endpoint"  # no global / multi-region endpoint


# Default in-country allowed regions (from P-03). Singapore is the primary residency.
DEFAULT_ALLOWED_REGIONS: frozenset[str] = frozenset(
    {
        "asia-southeast1",  # Singapore (default)
        "australia-southeast1",  # Sydney
        "australia-southeast2",  # Melbourne
        "asia-east2",  # Hong Kong
        "asia-northeast1",  # Tokyo
    }
)

DEFAULT_REQUIRED_CONTROLS: frozenset[ResidencyControl] = frozenset(
    {
        ResidencyControl.CMEK,
        ResidencyControl.VPC_SC,
        ResidencyControl.NO_PUBLIC_EGRESS,
        ResidencyControl.NO_GLOBAL_ENDPOINT,
    }
)


@dataclass(frozen=True, slots=True)
class ResidencyPolicy:
    """The residency / sovereignty rules a scan is graded against (pure, testable).

    Args:
        allowed_regions: the in-country regions a resource may be placed in (P-03).
        required_controls: the residency controls a data-bearing resource must carry.
        gate_severity: a scan PASSES iff it has no violation at or above this severity.
    """

    allowed_regions: frozenset[str] = DEFAULT_ALLOWED_REGIONS
    required_controls: frozenset[ResidencyControl] = DEFAULT_REQUIRED_CONTROLS
    gate_severity: Severity = Severity.HIGH

    def is_region_allowed(self, region: str | None) -> bool:
        """Whether ``region`` is an allowed in-country region."""
        return bool(region) and region in self.allowed_regions

    def requires(self, control: ResidencyControl) -> bool:
        """Whether ``control`` is mandated by this policy."""
        return control in self.required_controls


# --------------------------------------------------------------------------- #
# Resource configuration — what the scanners / parser produce.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ResourceConfig:
    """One infrastructure resource, normalised across the parser and the live scanner.

    ``attributes`` carries the raw, string-valued config the detector inspects for
    residency controls (e.g. ``kms_key_name``, ``public_access_prevention``); the
    detector reads these keys defensively so a missing attribute is a finding, not a
    crash.
    """

    address: str  # e.g. "google_storage_bucket.kyc"
    type: str  # e.g. "google_storage_bucket"
    region: str | None = None  # the resource's region / location, if any
    attributes: dict[str, str] = field(default_factory=dict)
    source_ref: str = ""  # "main.tf:42" or a Cloud Asset Inventory asset name


# --------------------------------------------------------------------------- #
# Violations — what the detector emits.
# --------------------------------------------------------------------------- #
class ViolationKind(StrEnum):
    """The kinds of residency / sovereignty violations the scan detects."""

    REGION_NOT_ALLOWED = "region_not_allowed"
    RESIDENCY_CONTROL_MISSING = "residency_control_missing"
    GLOBAL_ENDPOINT = "global_endpoint"
    MISSING_CMEK = "missing_cmek"
    PUBLIC_EGRESS = "public_egress"
    UNKNOWN_REGION = "unknown_region"


@dataclass(frozen=True, slots=True)
class ResidencyViolation:
    """A single residency / sovereignty violation against one resource.

    Carries enough context for both a human reviewer (``remediation`` prose, the
    ``evidence`` source_ref) and a downstream consumer: the offending resource, the rule
    that fired, the severity that feeds the gate verdict, and the citations to P-01 / P-03
    and the regulator.
    """

    resource: ResourceConfig
    kind: ViolationKind
    found_region: str | None
    allowed_regions: tuple[str, ...]
    severity: Severity
    rule_id: str  # stable slug, e.g. "region-not-allowed" / "missing-cmek"
    remediation: str
    evidence: str  # source_ref ("main.tf:42") or asset name
    citations: tuple[Citation, ...] = ()

    @property
    def resource_address(self) -> str:
        return self.resource.address

    @property
    def resource_type(self) -> str:
        return self.resource.type


@dataclass(frozen=True, slots=True)
class SeverityCount:
    """Count of violations at one severity level (for the verdict summary)."""

    severity: Severity
    count: int


@dataclass(frozen=True, slots=True)
class ScanVerdict:
    """The PASS/FAIL gate result that drives the CI exit code.

    ``passed`` is False when any violation is at or above the policy's gate severity.
    ``counts`` is the per-severity breakdown a CI log / dashboard renders.
    """

    passed: bool
    gate_severity: Severity
    total_violations: int
    counts: tuple[SeverityCount, ...] = ()

    @property
    def exit_code(self) -> int:
        """0 when the gate passes, 1 when it fails (the CLI returns this)."""
        return 0 if self.passed else 1


@dataclass(frozen=True, slots=True)
class ResidencyScan:
    """The full result of scanning a target (the primary residency-scan artifact).

    ``passed`` mirrors the verdict (no violation at/above the gate severity).
    ``requires_human_review`` is set when any HIGH/CRITICAL violation is present so a
    person signs off before an exception is granted (maker-checker, P-06).
    """

    target: str
    resources_scanned: int
    violations: tuple[ResidencyViolation, ...]
    verdict: ScanVerdict
    passed: bool
    requires_human_review: bool = False
    generated_at: datetime = field(default_factory=utcnow)


# --------------------------------------------------------------------------- #
# Audit decision — the scan-native decision, kept DISTINCT from C3's ``Decision``
# (ALLOWED/BLOCKED/ESCALATED). The scan service maps this onto the unified
# ``AuditEvent`` when writing the WORM record.
# --------------------------------------------------------------------------- #
class ResidencyDecision(StrEnum):
    PASSED = "passed"  # scan clean (gate PASS)
    FAILED = "failed"  # scan found gating violations (gate FAIL)
    ESCALATED = "escalated"  # routed to a human (maker-checker)
