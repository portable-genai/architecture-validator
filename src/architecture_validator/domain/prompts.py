"""Prompt templates for the Architecture & Requirements Validator (system C3).

Pure strings only — no imports beyond ``__future__``. The LLM in C3 has a narrow,
grounded job: it drafts the human-facing *prose* for remediation and for the injected
non-functional requirements, grounded in (a) the deterministic finding the policy
engine produced and (b) any regulatory-KB passages retrieved for context. It never
decides a verdict — the policy engine does that — so these templates instruct the
model to explain and remediate, not to judge.

Structured-output schemas are passed separately on the ``LlmRequest``; these templates
describe the *content* contract, the schema enforces the *shape*.

Template index
--------------
* ``KB_PASSAGE_BLOCK`` — per-citation rendering helper for the KB context block.
* ``REMEDIATION_SYSTEM`` / ``REMEDIATION_USER`` — draft injected-requirement prose
  and remediation for the unmet principles.
"""

from __future__ import annotations

#: One KB citation as rendered into the grounding context block handed to the model.
KB_PASSAGE_BLOCK = "[{source_id}] ({regulator}/{jurisdiction}, {title}, v{version})\n{snippet}\n"

#: Grounding discipline reused by the remediation template.
_CITATION_RULES = (
    "Grounding rules:\n"
    "- Base each requirement and rationale on the supplied FINDINGS and CONTEXT only.\n"
    "- You may reference a General Principle by its id (e.g. P-03) and a regulatory "
    "source_id present in CONTEXT; never invent a principle id, a source_id or a clause.\n"
    "- Do not change any verdict; the policy engine has already decided PASS/FAIL/"
    "NEEDS_INFO. Your job is the human-facing requirement text and rationale.\n"
)

REMEDIATION_SYSTEM = (
    "You are C3, the architecture and requirements validator for a regulated APAC bank. "
    "A policy engine has evaluated a project submission against the 12 General "
    "Principles and produced findings. For each UNMET principle (status FAIL or "
    "NEEDS_INFO) you draft the missing non-functional requirement to inject at intake, "
    "plus a short rationale grounded in the principle and any regulatory context.\n\n"
    "{citation_rules}\n"
    "For each injected requirement produce: the principle_id it addresses, a crisp "
    "imperative requirement_text (what the project MUST add), a one-to-two sentence "
    "rationale tying it to the principle and the cited obligation, and a severity of "
    "low | medium | high | critical reflecting regulatory and operational risk.\n\n"
    "Return strictly as JSON matching the response schema: an object with an items "
    "array; each item has principle_id, requirement_text, rationale, severity, "
    "used_source_ids (array of cited source_id strings, principle ids included)."
)

REMEDIATION_USER = (
    "PROJECT:\n{project}\n\n"
    "UNMET FINDINGS:\n{findings}\n\n"
    "CONTEXT (regulatory knowledge base):\n{context}\n\n"
    "Draft one injected requirement per unmet principle, grounded only in the FINDINGS "
    "and CONTEXT above."
)
