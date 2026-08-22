"""The Rsk3 VERTICAL domain models (system C3, the intake gate itself).

This module is the vertical half of the SPEC §2 "Kernel / vertical boundary": the
artifacts a fork of this repo REWRITES. C3 is the policy-as-code gate at project intake,
so the vertical is ``ProjectSubmission`` (what is submitted), ``Principle`` (the 12
General Principles as policy-as-code), ``PrincipleFinding`` (one verdict per principle),
``InjectedRequirement`` (the missing non-functional requirements auto-injected) and the
assembled ``ValidationReport``. The residency artifacts are the vertical's
second family and live in :mod:`architecture_validator.domain.residency.models`.

The reusable half -- citations and their regulator provenance, the LLM envelope,
retrieval, sessions and memory, the audit event, the evaluation report, agent cards and
the shared severity scale -- lives in :mod:`architecture_validator.domain.kernel`, which imports
NOTHING from this package. This module imports the kernel and re-exports every kernel
name below, so a fork inherits the kernel physically (it can ``import
architecture_validator.domain.kernel`` without ever loading this module) while every existing
``from .models import Citation`` import site in the repo keeps working unchanged.
``tests/unit/test_kernel_boundary.py`` enforces both directions by execution.

Still no dependency on Google Cloud, ADK, FastAPI or any framework: standard library
only, which is what lets the managed-service stack be swapped for an on-premise one
without touching domain logic (General Principle P-02, "no vendor lock-in / ports &
adapters"). C3 processes project metadata / design docs, not customer / PII data, so it
carries no Guardrail / Redaction models (the A1 guardrail dependency is N/A for C3).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

# --------------------------------------------------------------------------- #
# Kernel re-exports. These names are DEFINED in ``kernel.py``; they are re-exported
# here so that the physical split cost no import site a single edit. Never redeclare
# one of them in this module: ``test_kernel_boundary.py`` asserts object IDENTITY
# (``is``) between ``models.X`` and ``kernel.X``, so a local copy fails loudly.
# --------------------------------------------------------------------------- #
from .kernel import (
    REGULATOR_JURISDICTION as REGULATOR_JURISDICTION,
)
from .kernel import (
    SEVERITY_RANK as SEVERITY_RANK,
)
from .kernel import (
    AgentCard as AgentCard,
)
from .kernel import (
    AgentSkill as AgentSkill,
)
from .kernel import (
    AuditEvent as AuditEvent,
)
from .kernel import (
    Citation as Citation,
)
from .kernel import (
    Decision as Decision,
)
from .kernel import (
    EvalMetricResult as EvalMetricResult,
)
from .kernel import (
    EvalReport as EvalReport,
)
from .kernel import (
    Jurisdiction as Jurisdiction,
)
from .kernel import (
    LlmMessage as LlmMessage,
)
from .kernel import (
    LlmRequest as LlmRequest,
)
from .kernel import (
    LlmResponse as LlmResponse,
)
from .kernel import (
    MemoryItem as MemoryItem,
)
from .kernel import (
    Regulator as Regulator,
)
from .kernel import (
    RetrievalQuery as RetrievalQuery,
)
from .kernel import (
    Session as Session,
)
from .kernel import (
    Severity as Severity,
)
from .kernel import (
    StrEnum as StrEnum,
)
from .kernel import (
    ThinkingLevel as ThinkingLevel,
)
from .kernel import (
    TokenUsage as TokenUsage,
)
from .kernel import (
    ToolSpec as ToolSpec,
)
from .kernel import (
    utcnow as utcnow,
)

# --------------------------------------------------------------------------- #
# The 12 General Principles and a project submission to validate
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class Principle:
    """One of the 12 General Principles (the catalog ruleset), as policy-as-code.

    ``machine_rule`` is the human-readable statement of the check the policy engine
    applies; ``enforced_by`` names the systems that operationalise the principle
    (e.g. C3 itself for P-02 / P-05).
    """

    id: str  # e.g. "P-03"
    title: str
    statement: str
    machine_rule: str
    enforced_by: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectSubmission:
    """A project's requirements/design submitted to the intake gate (R6).

    The validator inspects the declared region, the declared controls, and the data
    flow flags against each principle. ``attributes`` carries anything else a rule may
    inspect (free-form string map), keeping the model open without weakening the typed
    core fields.
    """

    id: str
    name: str
    description: str
    requirements: str
    declared_region: str | None = None
    declared_controls: tuple[str, ...] = ()  # e.g. ("vpc_sc","cmek","dlp","eval_gate",...)
    uses_pii: bool = False
    uses_rag: bool = False
    uses_fine_tuning: bool = False
    has_exit_plan: bool = False
    attributes: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Findings, injected requirements and the report (the three cited artifacts)
# --------------------------------------------------------------------------- #
class CheckStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    NEEDS_INFO = "NEEDS_INFO"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(frozen=True, slots=True)
class PrincipleFinding:
    """The verdict for one principle against a submission.

    ``rule_id`` is the rego/rule that produced the verdict; ``evidence`` is what in the
    submission drove it; ``citations`` reference the principle (CROSS provenance) and,
    where relevant, a regulator instrument from the KB.
    """

    principle_id: str
    status: CheckStatus
    rule_id: str
    evidence: str
    severity: Severity = Severity.MEDIUM
    remediation: str = ""
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class InjectedRequirement:
    """A missing non-functional requirement auto-injected at intake.

    One per unmet principle, tied to the principle that mandates it, with an
    LLM-drafted rationale grounded in the principle text and any KB citations.
    """

    id: str
    principle_id: str
    requirement_text: str
    rationale: str
    severity: Severity = Severity.MEDIUM
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """The intake-gate verdict for a submission (the top-level C3 artifact).

    ``passed`` is True only when no principle FAILs. ``requires_human_review`` is
    always True when any FAIL or HIGH/CRITICAL finding is present (maker-checker, P-06).
    """

    submission: ProjectSubmission
    findings: tuple[PrincipleFinding, ...] = ()
    injected_requirements: tuple[InjectedRequirement, ...] = ()
    passed: bool = False
    requires_human_review: bool = True
    generated_at: datetime = field(default_factory=utcnow)

    @property
    def failed_principle_ids(self) -> tuple[str, ...]:
        return tuple(f.principle_id for f in self.findings if f.status is CheckStatus.FAIL)
