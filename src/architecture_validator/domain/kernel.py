"""The reusable, vertical-neutral kernel of the domain (system C3, package
``architecture_validator``).

SPEC §2 "Kernel / vertical boundary" divides this domain in two: the shared **evidence,
audit, evaluation, identity, citation and severity** contracts a fork inherits untouched,
and the Rsk3 **vertical** (``ProjectSubmission``, the 12-principle evaluator, requirement
injection, the residency scan artifacts) a fork rewrites. This module is the first half,
made physical.

The rule that gives the boundary teeth is the **dependency direction**: this module
imports nothing from ``architecture_validator``. It depends on the standard library and the
zero-dependency catalog commons only, so a fork can import it, keep every reusable type,
and replace the vertical without editing a mixed module.
:mod:`architecture_validator.domain.models` imports this module and re-exports every name, so
existing import sites are unchanged, and ``tests/unit/test_kernel_boundary.py`` proves
the direction by execution: a fresh interpreter imports the kernel and asserts
``architecture_validator.domain.models`` never enters ``sys.modules``.

Identity is the one kernel concern that is NOT declared here: :class:`Principal`,
:class:`RequestContext`, :class:`IdentityError` and ``ANONYMOUS`` already live in
:mod:`architecture_validator.domain.identity`, which is itself a thin re-export of
``hex_service_kit.identity`` and likewise imports nothing intra-package. It is therefore
already on the kernel side of the boundary and is left where every import site expects it.

C3 processes project metadata and design documents, **not customer PII**, so the kernel
carries no guardrail or redaction verdict types (see COMPLIANCE.md "Honest N/A" for C3 /
C4 and the A1 guardrail dependency being N-A for this system). A fork whose vertical does
handle PII adds those alongside these types rather than inside the vertical module.

Pure standard library plus the commons: no Google Cloud, ADK, FastAPI, httpx or pydantic
import appears at any depth here (General Principle P-02, "no vendor lock-in / ports &
adapters").
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from agent_eval_kit.report import EvalMetricResult as EvalMetricResult
from agent_eval_kit.report import EvalReport as EvalReport
from hex_service_kit import StrEnum as StrEnum
from hex_service_kit.observability import TokenUsage as TokenUsage

# ``StrEnum``, ``TokenUsage``, ``EvalMetricResult`` and ``EvalReport`` are IMPORTED here,
# not declared. Sixteen repositories in this catalog each hand-copied them and, by the time
# anyone compared, the copies disagreed. Re-exporting retires the whole drift class: there
# is exactly one definition to change, and ``tests/contract/test_port_parity.py`` asserts
# object IDENTITY (``is``) so a future local redeclaration fails rather than diverges.
#
# The submodule import paths (``agent_eval_kit.report``, ``hex_service_kit.observability``)
# are deliberate. This module promises to be stdlib-only plus the zero-dependency commons;
# the ``agent_eval_kit`` package root pulls in ``gate_client``, which imports httpx.
# ``hex_service_kit.observability`` carries no dependency at all (the OpenTelemetry
# implementation lives behind the ``otel`` extra).
#
# The commons ``EvalReport`` is a strict superset of a locally declared one: same three
# fields with the same defaults, same fail-closed ``passed`` rule
# (``n_examples > 0 and bool(results) and all(...)``), plus nine defaulted evidence fields
# (run_id, dataset_version, dataset_digest, evaluator, schema_version, trace_id,
# correlation_id, artifact_refs, attested). A constructor naming only the three fields
# still compiles and no verdict moves.


def utcnow() -> datetime:
    """Timezone-aware UTC now -- the single clock the domain uses."""
    return datetime.now(UTC)


# --------------------------------------------------------------------------- #
# Regulatory taxonomy (citation provenance is shared with the rest of the toolkit)
# --------------------------------------------------------------------------- #
class Regulator(StrEnum):
    """Financial-services regulators whose guidance backs a finding, plus CROSS.

    ``CROSS`` is reused as the lightweight provenance regulator for a citation that
    points at a rule in the adopting vertical's own ruleset (for Rsk3, a General
    Principle) rather than at a regulator instrument -- see :class:`Citation` and SPEC §3.
    """

    MAS = "MAS"  # Monetary Authority of Singapore
    HKMA = "HKMA"  # Hong Kong Monetary Authority
    APRA = "APRA"  # Australian Prudential Regulation Authority
    FSA = "FSA"  # Financial Services Agency of Japan
    CROSS = "CROSS"  # Cross-jurisdiction guidance + ruleset provenance


class Jurisdiction(StrEnum):
    SG = "SG"
    HK = "HK"
    AU = "AU"
    JP = "JP"
    GLOBAL = "GLOBAL"


REGULATOR_JURISDICTION: dict[Regulator, Jurisdiction] = {
    Regulator.MAS: Jurisdiction.SG,
    Regulator.HKMA: Jurisdiction.HK,
    Regulator.APRA: Jurisdiction.AU,
    Regulator.FSA: Jurisdiction.JP,
    Regulator.CROSS: Jurisdiction.GLOBAL,
}


# --------------------------------------------------------------------------- #
# Citation -- regulator-grade / ruleset provenance
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Citation:
    """Provenance attached to every finding and injected requirement.

    A finding may cite a regulator instrument (page-level provenance, as the rest of
    the toolkit requires) and/or a rule from the adopting vertical's ruleset. In Rsk3 a
    principle reference uses ``regulator=CROSS`` with the principle id as ``source_id``
    (e.g. "P-03"), so a reviewer can always trace a verdict back to the rule that
    produced it.
    """

    source_id: str
    regulator: Regulator
    jurisdiction: Jurisdiction
    title: str
    url: str
    version: str = "unknown"
    page: int | None = None
    snippet: str = ""
    score: float | None = None


# --------------------------------------------------------------------------- #
# Generation (LLM) -- the envelope every profile's LLM adapter speaks
# --------------------------------------------------------------------------- #
class ThinkingLevel(StrEnum):
    MINIMAL = "minimal"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True, slots=True)
class LlmMessage:
    role: str  # "user" | "model" | "system"
    content: str


@dataclass(frozen=True, slots=True)
class LlmRequest:
    messages: tuple[LlmMessage, ...]
    system_instruction: str | None = None
    model: str | None = None  # None => adapter default from config
    thinking: ThinkingLevel = ThinkingLevel.MEDIUM
    temperature: float = 0.2
    max_output_tokens: int = 4096
    response_schema: dict | None = None  # JSON schema for structured output


# TokenUsage was declared here. It now comes from ``hex_service_kit.observability`` (see the
# import block at the top of this module), byte-identical to the copy it replaced.


@dataclass(frozen=True, slots=True)
class LlmResponse:
    text: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str = ""
    raw: dict | None = None


# --------------------------------------------------------------------------- #
# Retrieval -- governed RAG / reg-KB context behind a cited finding
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class RetrievalQuery:
    text: str
    top_k: int = 8
    # Structured filters resolved by the adapter (e.g. {"regulator": "MAS"}).
    filters: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Runtime, session & memory (kept for parity with the toolkit's runtime ports)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class Session:
    id: str
    user_id: str
    case_id: str | None = None
    created_at: datetime = field(default_factory=utcnow)


@dataclass(frozen=True, slots=True)
class MemoryItem:
    id: str
    content: str
    scope: str = "user"  # "user" | "case" | "global"
    created_at: datetime = field(default_factory=utcnow)


# --------------------------------------------------------------------------- #
# Audit & observability -- A5 Observability, Audit & FinOps concerns
# --------------------------------------------------------------------------- #
class Decision(StrEnum):
    ALLOWED = "allowed"  # report produced, no FAIL
    BLOCKED = "blocked"  # validation could not proceed
    ESCALATED = "escalated"  # routed to a human (maker-checker)


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """An immutable, WORM-stored record of one interaction.

    C3 handles project metadata / design docs, not customer PII, so the prompt/response
    fields carry the submission summary and the verdict (no redaction model is needed
    -- see SPEC §2 and COMPLIANCE.md on P-04 being N/A for C3 itself).
    """

    action: str  # "validate" | "inject_requirements" | "list_principles" | "scan_iac" | ...
    actor: str  # authenticated user / service identity
    decision: Decision
    summary_prompt: str  # the submission summary (project metadata, no customer PII)
    summary_response: str  # the verdict summary
    citations: tuple[Citation, ...] = ()
    resource: str = "architecture-validator"
    # ``target`` names the artifact the event is about (e.g. a residency scan target /
    # plan path); optional so the C3 validation callers are unaffected while the residency
    # scan service can record what it scanned. (Kernel-unified AuditEvent.)
    target: str = ""
    trace_id: str | None = None
    timestamp: datetime = field(default_factory=utcnow)
    metadata: dict[str, str] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Evaluation gate -- A4 AI Quality & Model-Risk concerns
# --------------------------------------------------------------------------- #
# EvalMetricResult and EvalReport were declared in this repo. They now come from
# ``agent_eval_kit.report`` (see the import block at the top of this module). The
# fail-closed ``passed`` rule this repo hardened -- ``n_examples > 0 and bool(results) and
# all(...)``, so that a report which scored nothing cannot certify a promotion -- is the
# rule the commons type carries, so re-exporting weakens nothing. Metric NAMES stay the
# vertical's business: "principle_accuracy", "injection_recall", "citation_accuracy",
# "safety" for the architecture family and the "residency_"-prefixed four for the
# residency family, all defined with their thresholds in ``eval/rubrics/``.


# --------------------------------------------------------------------------- #
# Governance -- A3 Agent Registry & Governance concerns (A2A AgentCard)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class AgentSkill:
    id: str
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class AgentCard:
    """Minimal A2A-style agent card published at /.well-known/agent-card.json."""

    name: str
    description: str
    url: str
    version: str
    skills: tuple[AgentSkill, ...] = ()
    provider: str = "architecture-validator"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    """A governed, least-privilege tool exposed to the agent (typically via MCP)."""

    name: str
    description: str
    input_schema: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Severity (shared scale)
# --------------------------------------------------------------------------- #
class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


#: Severity rank for comparing against a gate severity (higher == worse). Shared by the
#: residency scan verdict / maker-checker gate.
SEVERITY_RANK: dict[Severity, int] = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}
