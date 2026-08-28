"""Shared grounded retrieve-render-generate-parse machinery (private to the domain).

C3's :class:`ValidationService` runs the LLM in one place — to draft the injected
requirement prose for the unmet principles — and the requirement-injection step needs
the same well-tested skeleton the rest of the toolkit uses: retrieve KB context, render
it into the prompt, call the LLM with a structured-output schema, defensively parse the
JSON, and map the model's ``used_source_ids`` back to ``Citation`` objects (preserving
the page/principle provenance).

This module factors out that machinery. It is ``_``-prefixed and not part of the public
domain API. Pure domain code — talks only to ports and models, no Google Cloud / ADK
imports.
"""

from __future__ import annotations

import json
from typing import Any

from .models import (
    Citation,
    LlmMessage,
    LlmRequest,
    LlmResponse,
    RetrievalQuery,
    Severity,
    ThinkingLevel,
)
from .prompts import KB_PASSAGE_BLOCK

#: Severity rank for picking the "highest" severity across findings.
_SEVERITY_RANK: dict[Severity, int] = {
    Severity.LOW: 0,
    Severity.MEDIUM: 1,
    Severity.HIGH: 2,
    Severity.CRITICAL: 3,
}

_SEVERITY_BY_VALUE: dict[str, Severity] = {s.value: s for s in Severity}


def coerce_severity(value: Any, default: Severity = Severity.MEDIUM) -> Severity:
    """Map a model-emitted severity string to the ``Severity`` enum defensively."""
    if isinstance(value, Severity):
        return value
    if isinstance(value, str):
        return _SEVERITY_BY_VALUE.get(value.strip().lower(), default)
    return default


def highest_severity(severities: list[Severity]) -> Severity | None:
    """Return the most severe entry, or None for an empty list."""
    if not severities:
        return None
    return max(severities, key=lambda s: _SEVERITY_RANK[s])


def render_citations(citations: list[Citation]) -> str:
    """Render KB citations into the numbered context block for the remediation prompt."""
    if not citations:
        return "(no regulatory context was retrieved)"
    blocks: list[str] = []
    for c in citations:
        blocks.append(
            KB_PASSAGE_BLOCK.format(
                source_id=c.source_id,
                regulator=c.regulator.value,
                jurisdiction=c.jurisdiction.value,
                title=c.title,
                version=c.version,
                snippet=(c.snippet or "").strip(),
            )
        )
    return "\n".join(blocks)


def retrieve_citations(
    knowledge_base: Any,
    query_text: str,
    top_k: int = 8,
) -> list[Citation]:
    """Run a KB retrieval through the KnowledgeBasePort defensively."""
    try:
        results = knowledge_base.retrieve(query_text, top_k=top_k)
    except TypeError:
        # Tolerate adapters that take a RetrievalQuery rather than (text, top_k).
        results = knowledge_base.retrieve(RetrievalQuery(text=query_text, top_k=top_k))
    return list(results or [])


def parse_structured(response: LlmResponse) -> dict[str, Any]:
    """Parse an LLM structured-output response into a dict, defensively.

    The GCP adapter returns the structured JSON as ``LlmResponse.text`` when a
    ``response_schema`` is set. We ``json.loads`` it; on any failure (plain text,
    truncation, a fenced block) we fall back to extracting the first balanced JSON
    object, and finally to an empty dict so callers degrade gracefully rather than
    raising on a malformed model reply.
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


def citations_for_source_ids(
    used_source_ids: list[str],
    available: list[Citation],
) -> tuple[Citation, ...]:
    """Map model-returned ``used_source_ids`` back to available Citations.

    ``available`` is the union of the principle citation(s) for the finding plus any KB
    citations retrieved for context. Unknown ids the model may have hallucinated are
    dropped — we only ever cite provenance we actually hold. When the model returns
    nothing usable, we fall back to all available citations so a requirement is never
    left provenance-less.
    """
    by_id: dict[str, list[Citation]] = {}
    for c in available:
        by_id.setdefault(c.source_id, []).append(c)

    wanted = list(used_source_ids or [])
    selected_ids = [sid for sid in wanted if sid in by_id]
    if not selected_ids:
        selected_ids = list(by_id.keys())

    out: list[Citation] = []
    seen: set[tuple[str, int | None]] = set()
    for sid in selected_ids:
        for citation in by_id.get(sid, ()):
            key = (citation.source_id, citation.page)
            if key not in seen:
                seen.add(key)
                out.append(citation)
    return tuple(out)


def build_llm_request(
    system_instruction: str,
    user_content: str,
    model: str | None,
    response_schema: dict | None,
    thinking: ThinkingLevel = ThinkingLevel.HIGH,
    temperature: float = 0.0,
    max_output_tokens: int = 4096,
) -> LlmRequest:
    """Assemble an ``LlmRequest`` with a single user message and a system prompt.

    ``model=None`` lets the adapter pick its configured default (the reasoning model,
    ``gemini-3.5-flash``); thinking defaults to HIGH for grounded reasoning per SPEC.
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
