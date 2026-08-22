"""Prompt templates for the residency scan.

Pure strings only — no imports beyond ``__future__``. Every template is a module level
constant exposing ``.format(...)`` parameters. The LLM is used **only** to draft
human-readable remediation / explanation prose for a violation the deterministic detector
already found; the model never decides whether a resource is in violation (that is the
detector's job). The model is told the violation facts and asked to explain and remediate
them, never to invent new findings.

Template index
--------------
* ``REMEDIATION_SYSTEM`` / ``REMEDIATION_USER`` — draft a remediation narrative for a
  set of detected violations.
* ``EXPLAIN_SYSTEM`` / ``EXPLAIN_USER`` — explain a single violation to an engineer.
* ``VIOLATION_BLOCK`` — per-violation rendering helper used to build the context.
"""

from __future__ import annotations

#: One violation as rendered into the context block handed to the model.
VIOLATION_BLOCK = (
    "- [{rule_id}] {kind} ({severity}) on {address} ({type})\n"
    "  found_region={found_region}; allowed_regions={allowed_regions}\n"
    "  evidence={evidence}\n"
)

#: Discipline reused by every residency template: stick to the facts the detector found.
_FACTS_RULES = (
    "Rules:\n"
    "- The deterministic detector has already decided these are violations; do NOT "
    "re-adjudicate or invent new findings.\n"
    "- Write remediation an engineer can act on: name the concrete control to add "
    "(regional CMEK, a VPC Service Controls perimeter, removing a public endpoint, "
    "or moving the resource to an allowed in-country region).\n"
    "- Be precise and neutral; do not give legal advice or a compliance sign-off.\n"
    "- Reference the residency principle (P-01 VPC-SC / no public egress; P-03 single "
    "in-country region) where it clarifies the fix.\n"
)

# --------------------------------------------------------------------------- #
# 1. Remediation narrative for a batch of violations
# --------------------------------------------------------------------------- #
REMEDIATION_SYSTEM = (
    "You are a data-residency / sovereignty validator for APAC banks. You receive "
    "a list of residency VIOLATIONS that a deterministic detector found in "
    "infrastructure configuration, and you draft a concise, actionable remediation "
    "narrative for the engineering team.\n\n"
    "{facts_rules}\n"
    "Return strictly as JSON matching the response schema: an object with a "
    "remediation (string: a short ordered plan to bring the resources into "
    "compliance) and per_violation (array of objects with rule_id and a one-line fix)."
)

REMEDIATION_USER = (
    "TARGET:\n{target}\n\n"
    "VIOLATIONS:\n{violations}\n\n"
    "Draft the remediation plan for these residency violations."
)

# --------------------------------------------------------------------------- #
# 2. Explain a single violation to an engineer
# --------------------------------------------------------------------------- #
EXPLAIN_SYSTEM = (
    "You are explaining a single data-residency / sovereignty violation to an "
    "engineer so they understand why it fails the gate and how to fix it.\n\n"
    "{facts_rules}\n"
    "Return strictly as JSON matching the response schema: an object with an "
    "explanation (string: why this is a residency violation) and remediation (string: "
    "the concrete fix)."
)

EXPLAIN_USER = (
    "VIOLATION:\n{violation}\n\nExplain why this fails residency policy and how to remediate it."
)
