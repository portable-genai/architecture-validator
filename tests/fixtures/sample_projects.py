"""Synthetic project submissions + KB citations for deterministic tests.

Nothing here touches Google Cloud. The submissions are invented but plausible APAC-bank
project intakes; the KB citations mimic the shape of governed regulatory context (with a
source id / title / snippet) so unit tests can assert the full validation pipeline
without any network or SDK. The text is fictional and must not be treated as the real
instruments.
"""

from __future__ import annotations

from architecture_validator.domain.models import (
    Citation,
    Jurisdiction,
    ProjectSubmission,
    Regulator,
)

# --------------------------------------------------------------------------- #
# A clean submission — every principle is satisfied, so the report PASSES.
# --------------------------------------------------------------------------- #
COMPLIANT_SUBMISSION = ProjectSubmission(
    id="proj-clean-001",
    name="Grounded internal policy assistant",
    description=(
        "An internal RAG assistant over governed policy documents for the risk team, "
        "deployed in Singapore on the managed agent platform."
    ),
    requirements=(
        "Answer staff policy questions with citations; no customer data; eval-gated "
        "promotion; maker-checker on published answers."
    ),
    declared_region="asia-southeast1",
    declared_controls=(
        "vpc_sc",
        "ports_and_adapters",
        "cmek",
        "least_privilege_iam",
        "dlp",
        "eval_gate",
        "maker_checker",
        "audit_logging",
        "model_card",
        "kill_switch",
        "model_routing",
    ),
    uses_pii=False,
    uses_rag=True,
    uses_fine_tuning=False,
    has_exit_plan=True,
    attributes={},
)

# --------------------------------------------------------------------------- #
# A non-compliant submission — multiple hard FAILs (wrong region, no VPC-SC, no
# eval gate, no maker-checker, no CMEK, no exit plan) and a PII-without-DLP gap.
# --------------------------------------------------------------------------- #
NON_COMPLIANT_SUBMISSION = ProjectSubmission(
    id="proj-risky-002",
    name="Customer-facing GenAI onboarding bot on public cloud",
    description=(
        "A customer-facing GenAI assistant processing customer onboarding data, "
        "fine-tuned on historical chats, deployed in us-central1."
    ),
    requirements=(
        "Handle KYC onboarding chats; fine-tune on past customer conversations; ship "
        "fast to production."
    ),
    declared_region="us-central1",
    declared_controls=("audit_logging",),
    uses_pii=True,
    uses_rag=False,
    uses_fine_tuning=True,
    has_exit_plan=False,
    attributes={},
)

# Principle ids that NON_COMPLIANT_SUBMISSION should FAIL (hard violations).
NON_COMPLIANT_EXPECTED_FAILS: tuple[str, ...] = (
    "P-01",  # no vpc_sc
    "P-02",  # no ports_and_adapters / fallback
    "P-03",  # us-central1 not allowed, no exception
    "P-05",  # fine-tune on PII
    "P-06",  # no maker_checker
    "P-08",  # no eval_gate
    "P-09",  # no cmek
    "P-12",  # no exit plan
)

# --------------------------------------------------------------------------- #
# Synthetic KB citations the FakeKnowledgeBase returns for grounding context.
# --------------------------------------------------------------------------- #
SAMPLE_KB_CITATIONS: tuple[Citation, ...] = (
    Citation(
        source_id="mas-trm-guidelines",
        regulator=Regulator.MAS,
        jurisdiction=Jurisdiction.SG,
        title="MAS Technology Risk Management Guidelines",
        url="https://example.test/mas/trm",
        version="2021",
        page=42,
        snippet="Pin data and processing to an approved in-country region.",
        score=0.91,
    ),
    Citation(
        source_id="apra-cps-230",
        regulator=Regulator.APRA,
        jurisdiction=Jurisdiction.AU,
        title="APRA CPS 230 Operational Risk Management",
        url="https://example.test/apra/cps230",
        version="2025",
        page=15,
        snippet="Maintain tested resilience controls and a documented exit plan.",
        score=0.84,
    ),
)

PRIMARY_KB_SOURCE_ID: str = SAMPLE_KB_CITATIONS[0].source_id
