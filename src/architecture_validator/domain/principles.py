"""The 12 General Principles (P-01..P-12) as canonical :class:`Principle` objects.

This is the bundled ruleset C3 validates against (the catalog "General Principles
(Ruleset)" tab). Each principle carries its canonical statement and a human-readable
``machine_rule`` describing the check applied by
:mod:`architecture_validator.domain.principles_eval` (and, on the gcp/OPA path, by the parallel
rego files under ``policies/``).

Pure-stdlib data only; no Google Cloud / framework imports.
"""

from __future__ import annotations

from .models import Principle

#: The allowed in-country regions (P-03). A declared region outside this set FAILs P-03
#: unless an exception is signed off (recorded in submission attributes).
ALLOWED_REGIONS: tuple[str, ...] = (
    "asia-southeast1",  # Singapore
    "australia-southeast1",  # Sydney
    "australia-southeast2",  # Melbourne
    "asia-east2",  # Hong Kong
    "asia-northeast1",  # Tokyo
)

PRINCIPLES: tuple[Principle, ...] = (
    Principle(
        id="P-01",
        title="Hybrid on-prem + GCP",
        statement=(
            "Connect on-premise estate and Google Cloud over private interconnect inside "
            "a VPC Service Controls perimeter; no public egress for managed-service APIs."
        ),
        machine_rule="FAIL if 'vpc_sc' not in declared_controls (perimeter not declared).",
        enforced_by=("C3", "platform-networking"),
    ),
    Principle(
        id="P-02",
        title="No vendor lock-in",
        statement=(
            "Build ports-and-adapters against open standards with a documented Gemma "
            "fallback, so any managed service can be swapped without changing the domain."
        ),
        machine_rule=(
            "FAIL if 'ports_and_adapters' and a documented fallback are both absent; C3 enforces."
        ),
        enforced_by=("C3",),
    ),
    Principle(
        id="P-03",
        title="Single in-country region",
        statement=(
            "Pin all data and processing to a single approved in-country region; any "
            "exception must be explicitly signed off."
        ),
        machine_rule="FAIL if declared_region not in ALLOWED_REGIONS and no signed-off exception.",
        enforced_by=("C3", "C4"),
    ),
    Principle(
        id="P-04",
        title="Minimise data to the model",
        statement=(
            "Redact PII at the boundary (DLP) before any model call; send the model the "
            "minimum data necessary."
        ),
        machine_rule=(
            "NEEDS_INFO if uses_pii and 'dlp' absent; NOT_APPLICABLE if no PII; PASS with DLP."
        ),
        enforced_by=("A1", "C1"),
    ),
    Principle(
        id="P-05",
        title="Grounding over fine-tuning",
        statement=(
            "Prefer retrieval-augmented grounding on governed data over fine-tuning; never "
            "train on PII."
        ),
        machine_rule=(
            "FAIL if fine-tuning on PII; NEEDS_INFO if fine-tuning without grounding; C3 enforces."
        ),
        enforced_by=("C3", "C1"),
    ),
    Principle(
        id="P-06",
        title="Human-in-the-loop / maker-checker",
        statement=(
            "Keep a human maker-checker in the loop for consequential decisions; no "
            "autonomous approval of material actions."
        ),
        machine_rule="FAIL if 'maker_checker' not in declared_controls.",
        enforced_by=("C1", "C2", "C3"),
    ),
    Principle(
        id="P-07",
        title="Auditable & explainable",
        statement=(
            "Make every decision auditable and explainable: immutable logs, citations and "
            "model cards."
        ),
        machine_rule=(
            "FAIL if 'audit_logging' not in declared_controls; NEEDS_INFO if no model card."
        ),
        enforced_by=("A5", "C3"),
    ),
    Principle(
        id="P-08",
        title="Eval-gated promotion",
        statement="Gate promotion to production on a quantitative evaluation suite.",
        machine_rule="FAIL if 'eval_gate' not in declared_controls.",
        enforced_by=("A4", "C3"),
    ),
    Principle(
        id="P-09",
        title="Defense in depth / zero trust",
        statement=(
            "Apply CMEK, Assured Workloads, least-privilege IAM, private endpoints and "
            "distinct agent identities."
        ),
        machine_rule="FAIL if 'cmek' absent; NEEDS_INFO if 'least_privilege_iam' not confirmed.",
        enforced_by=("C3", "platform-security"),
    ),
    Principle(
        id="P-10",
        title="Resilience & graceful degradation",
        statement=(
            "Provide fallbacks, circuit breakers and a kill-switch (APRA CPS 230 / HKMA "
            "OR-2); degrade gracefully under failure."
        ),
        machine_rule=(
            "NEEDS_INFO if neither 'kill_switch' nor 'circuit_breaker' declared; else PASS."
        ),
        enforced_by=("C3", "platform-sre"),
    ),
    Principle(
        id="P-11",
        title="Cost & latency control",
        statement="Control cost and latency via model routing, caching and token budgets.",
        machine_rule=(
            "NEEDS_INFO if no cost/latency control (model_routing / caching / token_budget)."
        ),
        enforced_by=("A5", "C3"),
    ),
    Principle(
        id="P-12",
        title="Reversibility / documented exit",
        statement="Maintain a documented, tested exit plan so the system is reversible.",
        machine_rule="FAIL if has_exit_plan is false.",
        enforced_by=("C3",),
    ),
)

PRINCIPLES_BY_ID: dict[str, Principle] = {p.id: p for p in PRINCIPLES}


def all_principles() -> list[Principle]:
    """Return the canonical 12 General Principles, in id order."""
    return list(PRINCIPLES)
