"""Shared remediation-drafting machinery (private to the residency domain layer).

The deterministic :class:`~architecture_validator.domain.residency.detector.ViolationDetector`
decides *what* is in violation; the LLM (via ``LLMPort``) is used only to draft
human-readable remediation / explanation prose for those findings. This module factors
out the LLM plumbing the scan service shares: render violations into the prompt context,
call the LLM with a structured-output schema, defensively parse the JSON, and emit token
usage to the tracer.

It is ``_``-prefixed and not part of the public domain API. Pure domain code — talks only
to ports and models, no Google Cloud / ADK imports.
"""

from __future__ import annotations

import json
from typing import Any

from ..models import (
    LlmMessage,
    LlmRequest,
    LlmResponse,
    ThinkingLevel,
)
from .models import ResidencyViolation
from .prompts import VIOLATION_BLOCK


def render_violations(violations: list[ResidencyViolation]) -> str:
    """Render detected violations into the numbered context block for the prompt."""
    if not violations:
        return "(no violations were detected)"
    blocks: list[str] = []
    for v in violations:
        blocks.append(
            VIOLATION_BLOCK.format(
                rule_id=v.rule_id,
                kind=v.kind.value,
                severity=v.severity.value,
                address=v.resource.address,
                type=v.resource.type,
                found_region=v.found_region if v.found_region is not None else "(none)",
                allowed_regions=", ".join(v.allowed_regions) or "(none)",
                evidence=v.evidence,
            )
        )
    return "".join(blocks)


def parse_structured(response: LlmResponse) -> dict[str, Any]:
    """Parse an LLM structured-output response into a dict, defensively.

    The GCP adapter returns the structured JSON as ``LlmResponse.text`` when a
    ``response_schema`` is set. We ``json.loads`` it; on any failure we fall back to
    extracting the first balanced JSON object, and finally to an empty dict so callers
    degrade gracefully rather than raising on a malformed model reply.
    """
    text = (response.text or "").strip()
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"items": parsed}
    except (json.JSONDecodeError, ValueError):
        pass

    snippet = _extract_json_object(text)
    if snippet is not None:
        try:
            parsed = json.loads(snippet)
            if isinstance(parsed, dict):
                return parsed
        except (json.JSONDecodeError, ValueError):
            pass
    return {}


def _extract_json_object(text: str) -> str | None:
    """Return the first balanced ``{...}`` block in ``text``, or None."""
    start = text.find("{")
    if start == -1:
        return None
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def build_llm_request(
    system_instruction: str,
    user_content: str,
    model: str | None,
    response_schema: dict | None,
    thinking: ThinkingLevel = ThinkingLevel.MEDIUM,
    temperature: float = 0.0,
    max_output_tokens: int = 4096,
) -> LlmRequest:
    """Assemble an ``LlmRequest`` with a single user message and a system prompt.

    ``model=None`` lets the adapter pick its configured default (the reasoning model,
    ``gemini-3.5-flash``).
    """
    return LlmRequest(
        messages=(LlmMessage(role="user", content=user_content),),
        system_instruction=system_instruction,
        model=model,
        thinking=thinking,
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        response_schema=response_schema,
    )


def maybe_record_usage(tracer: Any, response: Any) -> None:
    """Emit token usage to the tracer for FinOps, defensively (never fatal)."""
    try:
        usage = getattr(response, "usage", None)
        model = getattr(response, "model", "") or ""
        if usage is not None and hasattr(tracer, "record_token_usage"):
            tracer.record_token_usage(usage, model)
    except Exception:  # noqa: BLE001 - metrics must never break a generation path
        return


def as_str_list(value: Any) -> list[str]:
    """Coerce an arbitrary model value into a list of stripped non-empty strings."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    return []
