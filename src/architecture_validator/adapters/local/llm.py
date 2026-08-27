"""Local LLM adapter (LLMPort) — a deterministic, schema-driven generator.

The ``local`` profile's stand-in for **Gemini**: no model, no network, fully
reproducible. C3 uses the LLM in exactly one place, to draft the injected-requirement
prose for the unmet principles, so this adapter reads the unmet findings the requirement
schema renders into the user prompt (``- P-0X [STATUS, sev]``) and emits one ``items``
element per unmet principle, citing that principle id via ``used_source_ids`` (so the
service's used_source_ids -> Citation mapping genuinely runs). It never decides a verdict.
There is no Google emulator for Gemini, so this path is unconditional.

The schema-driven ``FakeLLM`` is a real, registered adapter rather than a test fixture, so
the in-memory implementation lives once under ``adapters/local`` and drives both the offline
tests and the CLI.
"""

from __future__ import annotations

import json
import re
from typing import Any

from ...config import Settings
from ...domain.models import LlmRequest, LlmResponse, TokenUsage

# The requirement-injection prompt renders each unmet finding as
# ``- P-0X [STATUS, severity] (rule ...): evidence``; recover the principle id + severity
# so one injected requirement is drafted per unmet principle.
_UNMET_RE = re.compile(r"^- (P-\d{2}) \[(FAIL|NEEDS_INFO),\s*([a-z]+)\]", re.MULTILINE)


def _schema_properties(schema: dict | None) -> dict[str, Any]:
    if not schema:
        return {}
    props = schema.get("properties")
    return props if isinstance(props, dict) else {}


class LocalDeterministicLLMAdapter:
    """Deterministic LLM whose ``generate`` returns JSON matching the request schema.

    For the requirement-injection schema (an object with an ``items`` array) it parses
    the unmet findings rendered into the prompt and emits one item per unmet principle.
    For any other (flat) schema it returns a deterministic object whose keys match the
    requested properties, so the adapter stays correct for whatever service calls it.
    """

    REASONING_MODEL = "gemini-3.5-flash"
    TRIAGE_MODEL = "gemini-3.5-flash"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._reasoning_model = settings.models.reasoning or self.REASONING_MODEL
        self._triage_model = settings.models.triage or self.TRIAGE_MODEL
        # Captured for optional inspection / test assertions.
        self.requests: list[LlmRequest] = []
        self.classify_calls: list[tuple[str, list[str]]] = []

    # ------------------------------------------------------------------ #
    # LLMPort
    # ------------------------------------------------------------------ #
    def generate(self, request: LlmRequest) -> LlmResponse:
        self.requests.append(request)
        body = self._body_for_schema(request.response_schema, self._user_content(request))
        return LlmResponse(
            text=json.dumps(body),
            usage=TokenUsage(input_tokens=128, output_tokens=64, thinking_tokens=32),
            model=request.model or self._reasoning_model,
            raw=body,
        )

    def classify(self, text: str, labels: list[str]) -> str:
        # Deterministic triage: first label (services use this only for routing).
        self.classify_calls.append((text, labels))
        return labels[0] if labels else ""

    # ------------------------------------------------------------------ #
    # Schema-driven body
    # ------------------------------------------------------------------ #
    @staticmethod
    def _user_content(request: LlmRequest) -> str:
        for message in reversed(request.messages):
            if message.role == "user":
                return message.content
        return ""

    def _body_for_schema(self, schema: dict | None, user: str) -> dict[str, Any]:
        props = _schema_properties(schema)
        if "items" in props:
            return {"items": self._injection_items(user)}
        # Flat schema (or none): emit deterministic placeholder values per property.
        if not props:
            return {"items": self._injection_items(user)}
        return {name: self._flat_field(name) for name in props}

    @staticmethod
    def _injection_items(user: str) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for principle_id, _status, severity in _UNMET_RE.findall(user):
            items.append(
                {
                    "principle_id": principle_id,
                    "requirement_text": (
                        f"Add the control mandated by {principle_id} before intake."
                    ),
                    "rationale": f"{principle_id} is unmet; this requirement closes the gap.",
                    "severity": severity,
                    "used_source_ids": [principle_id],
                }
            )
        return items

    @staticmethod
    def _flat_field(name: str) -> Any:
        return {
            "rationale": "Grounded in the unmet finding and the cited principle.",
            "requirement_text": "Add the mandated control before intake.",
            "severity": "medium",
            "used_source_ids": [],
        }.get(name, "")
