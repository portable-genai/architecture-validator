"""Pydantic v2 request/response models for the C3 Architecture Validator API.

These schemas mirror the frozen domain dataclasses in
:mod:`architecture_validator.domain.models` one-for-one, so the HTTP boundary is a thin, typed
projection of the domain — the React/Next.js UI and the CLI consume exactly these shapes.
Each response model exposes a ``from_domain`` classmethod that builds itself from the
corresponding domain object, using :func:`domain.serialization.to_jsonable` where a nested
structure is easiest to project verbatim (enums become their ``.value`` strings).

Nothing here imports Google Cloud, ADK, or any adapter: the API layer depends only on the
domain models, the ports, and the orchestration services — never on a concrete adapter.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ..domain import models as m
from ..domain.residency import models as rm
from ..domain.serialization import to_jsonable

# --------------------------------------------------------------------------- #
# Shared citation projection
# --------------------------------------------------------------------------- #


class CitationModel(BaseModel):
    """Provenance attached to a finding / injected requirement (mirror of Citation)."""

    source_id: str
    regulator: str
    jurisdiction: str
    title: str
    url: str
    version: str = "unknown"
    page: int | None = None
    snippet: str = ""
    score: float | None = None

    @classmethod
    def from_domain(cls, citation: m.Citation) -> CitationModel:
        return cls(**to_jsonable(citation))


# --------------------------------------------------------------------------- #
# Requests
# --------------------------------------------------------------------------- #


class SubmissionModel(BaseModel):
    """Inbound project submission to validate at intake (mirror of ProjectSubmission)."""

    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    description: str = ""
    requirements: str = ""
    declared_region: str | None = None
    declared_controls: list[str] = Field(default_factory=list)
    uses_pii: bool = False
    uses_rag: bool = False
    uses_fine_tuning: bool = False
    has_exit_plan: bool = False
    attributes: dict[str, str] = Field(default_factory=dict)

    def to_domain(self) -> m.ProjectSubmission:
        return m.ProjectSubmission(
            id=self.id,
            name=self.name,
            description=self.description,
            requirements=self.requirements,
            declared_region=self.declared_region,
            declared_controls=tuple(self.declared_controls),
            uses_pii=self.uses_pii,
            uses_rag=self.uses_rag,
            uses_fine_tuning=self.uses_fine_tuning,
            has_exit_plan=self.has_exit_plan,
            attributes=dict(self.attributes),
        )


class ValidateRequest(BaseModel):
    """Inbound validation request.

    There is deliberately no ``actor`` field: the API never trusts a client-asserted
    identity. The audit actor is the server-verified :class:`Principal` resolved by the
    active profile's ``IdentityPort`` (see ``api/security.py``).
    """

    submission: SubmissionModel


# --------------------------------------------------------------------------- #
# Artifact responses
# --------------------------------------------------------------------------- #


class PrincipleFindingModel(BaseModel):
    """The verdict for one principle (mirror of PrincipleFinding)."""

    principle_id: str
    status: str
    rule_id: str
    evidence: str
    severity: str = "medium"
    remediation: str = ""
    citations: list[CitationModel] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, finding: m.PrincipleFinding) -> PrincipleFindingModel:
        return cls(
            principle_id=finding.principle_id,
            status=finding.status.value,
            rule_id=finding.rule_id,
            evidence=finding.evidence,
            severity=finding.severity.value,
            remediation=finding.remediation,
            citations=[CitationModel.from_domain(c) for c in finding.citations],
        )


class InjectedRequirementModel(BaseModel):
    """A missing NFR auto-injected at intake (mirror of InjectedRequirement)."""

    id: str
    principle_id: str
    requirement_text: str
    rationale: str
    severity: str = "medium"
    citations: list[CitationModel] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, req: m.InjectedRequirement) -> InjectedRequirementModel:
        return cls(
            id=req.id,
            principle_id=req.principle_id,
            requirement_text=req.requirement_text,
            rationale=req.rationale,
            severity=req.severity.value,
            citations=[CitationModel.from_domain(c) for c in req.citations],
        )


class ValidationReportResponse(BaseModel):
    """The intake-gate verdict (mirror of ValidationReport)."""

    submission: SubmissionModel
    findings: list[PrincipleFindingModel] = Field(default_factory=list)
    injected_requirements: list[InjectedRequirementModel] = Field(default_factory=list)
    passed: bool = False
    requires_human_review: bool = True
    generated_at: str = ""

    @classmethod
    def from_domain(cls, report: m.ValidationReport) -> ValidationReportResponse:
        sub = report.submission
        return cls(
            submission=SubmissionModel(
                id=sub.id,
                name=sub.name,
                description=sub.description,
                requirements=sub.requirements,
                declared_region=sub.declared_region,
                declared_controls=list(sub.declared_controls),
                uses_pii=sub.uses_pii,
                uses_rag=sub.uses_rag,
                uses_fine_tuning=sub.uses_fine_tuning,
                has_exit_plan=sub.has_exit_plan,
                attributes=dict(sub.attributes),
            ),
            findings=[PrincipleFindingModel.from_domain(f) for f in report.findings],
            injected_requirements=[
                InjectedRequirementModel.from_domain(r) for r in report.injected_requirements
            ],
            passed=report.passed,
            requires_human_review=report.requires_human_review,
            generated_at=report.generated_at.isoformat(),
        )


class PrincipleModel(BaseModel):
    """One of the 12 General Principles (mirror of Principle)."""

    id: str
    title: str
    statement: str
    machine_rule: str
    enforced_by: list[str] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, principle: m.Principle) -> PrincipleModel:
        return cls(
            id=principle.id,
            title=principle.title,
            statement=principle.statement,
            machine_rule=principle.machine_rule,
            enforced_by=list(principle.enforced_by),
        )


class PrinciplesResponse(BaseModel):
    """The 12 General Principles the gate enforces."""

    principles: list[PrincipleModel] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Health & governance
# --------------------------------------------------------------------------- #


class HealthResponse(BaseModel):
    """Liveness/readiness of the validator and its active profile."""

    status: str = "ok"
    profile: str = "local"
    region: str = "asia-southeast1"
    #: Provenance the UI banner states on every page: where the runtime sits and which model
    #: answers. Both are read off the service because the browser cannot know either.
    runtime: str = "local"  # "gcp" | "local"
    generator_model: str = "deterministic-offline-stub"


class AgentSkillModel(BaseModel):
    id: str
    name: str
    description: str


class AgentCardModel(BaseModel):
    """A2A AgentCard served at /.well-known/agent-card.json (mirror of AgentCard)."""

    name: str
    description: str
    url: str
    version: str
    provider: str = "architecture-validator"
    skills: list[AgentSkillModel] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, card: m.AgentCard) -> AgentCardModel:
        data: dict[str, Any] = to_jsonable(card)
        return cls(**data)


# --------------------------------------------------------------------------- #
# Residency scan projections. C3's own /validate schemas are
# above; these back the additive POST /scan and GET /policy routes.
# --------------------------------------------------------------------------- #


class ResourceConfigModel(BaseModel):
    """One scanned resource (mirror of residency ResourceConfig)."""

    address: str
    type: str
    region: str | None = None
    attributes: dict[str, str] = Field(default_factory=dict)
    source_ref: str = ""

    @classmethod
    def from_domain(cls, resource: rm.ResourceConfig) -> ResourceConfigModel:
        return cls(**to_jsonable(resource))


class ScanRequest(BaseModel):
    """Inbound residency scan request.

    Exactly one of ``target``, ``plan_json`` or ``resources`` should be provided:
    * ``target``   — a plan/.tf path or a ``projects/...`` scope (the gate path);
    * ``plan_json``— an inline ``terraform show -json`` document to scan;
    * ``resources``— an already-parsed list of resources.

    There is no ``actor`` field: the audit actor is the server-verified Principal resolved
    by the IdentityPort, never a client-supplied value.
    """

    target: str | None = Field(default=None, description="A plan/.tf path or a project scope.")
    plan_json: dict[str, Any] | None = Field(
        default=None, description="An inline Terraform plan JSON document to scan."
    )
    resources: list[ResourceConfigModel] | None = Field(
        default=None, description="An already-parsed list of resources to scan."
    )


class ResidencyViolationModel(BaseModel):
    """A single residency violation (mirror of ResidencyViolation)."""

    resource_address: str
    resource_type: str
    kind: str
    found_region: str | None = None
    allowed_regions: list[str] = Field(default_factory=list)
    severity: str
    rule_id: str
    remediation: str
    evidence: str
    citations: list[CitationModel] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, v: rm.ResidencyViolation) -> ResidencyViolationModel:
        return cls(
            resource_address=v.resource.address,
            resource_type=v.resource.type,
            kind=v.kind.value,
            found_region=v.found_region,
            allowed_regions=list(v.allowed_regions),
            severity=v.severity.value,
            rule_id=v.rule_id,
            remediation=v.remediation,
            evidence=v.evidence,
            citations=[CitationModel.from_domain(c) for c in v.citations],
        )


class SeverityCountModel(BaseModel):
    severity: str
    count: int

    @classmethod
    def from_domain(cls, c: rm.SeverityCount) -> SeverityCountModel:
        return cls(severity=c.severity.value, count=c.count)


class ScanVerdictModel(BaseModel):
    """PASS/FAIL gate result (mirror of ScanVerdict)."""

    passed: bool
    gate_severity: str
    total_violations: int
    exit_code: int
    counts: list[SeverityCountModel] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, v: rm.ScanVerdict) -> ScanVerdictModel:
        return cls(
            passed=v.passed,
            gate_severity=v.gate_severity.value,
            total_violations=v.total_violations,
            exit_code=v.exit_code,
            counts=[SeverityCountModel.from_domain(c) for c in v.counts],
        )


class ResidencyScanResponse(BaseModel):
    """The full scan result (mirror of ResidencyScan)."""

    target: str
    resources_scanned: int
    passed: bool
    requires_human_review: bool
    generated_at: str
    verdict: ScanVerdictModel
    violations: list[ResidencyViolationModel] = Field(default_factory=list)

    @classmethod
    def from_domain(cls, scan: rm.ResidencyScan) -> ResidencyScanResponse:
        return cls(
            target=scan.target,
            resources_scanned=scan.resources_scanned,
            passed=scan.passed,
            requires_human_review=scan.requires_human_review,
            generated_at=scan.generated_at.isoformat(),
            verdict=ScanVerdictModel.from_domain(scan.verdict),
            violations=[ResidencyViolationModel.from_domain(v) for v in scan.violations],
        )


class ResidencyPolicyModel(BaseModel):
    """The active residency policy (mirror of ResidencyPolicy)."""

    allowed_regions: list[str]
    required_controls: list[str]
    gate_severity: str

    @classmethod
    def from_domain(cls, policy: rm.ResidencyPolicy) -> ResidencyPolicyModel:
        return cls(
            allowed_regions=sorted(policy.allowed_regions),
            required_controls=sorted(c.value for c in policy.required_controls),
            gate_severity=policy.gate_severity.value,
        )
