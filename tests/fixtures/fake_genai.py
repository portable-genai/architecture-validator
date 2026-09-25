"""A stand-in for the slice of ``google.genai`` the Gemini adapter touches, with no SDK.

The gate runs with no cloud SDK installed, so the managed adapter's request mapping and what it
notes after a call are proved against this instead: ``install`` puts a fake ``google`` and
``google.genai`` (carrying ``types``) into ``sys.modules`` for one test (``monkeypatch``
restores them), and :class:`FakeClient` records every ``generate_content`` call with the config
kwargs it was built from, so a test reads exactly what would have been sent.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from enum import Enum
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest


class _ThinkingLevel(Enum):
    LOW = "LOW"
    HIGH = "HIGH"


@dataclass
class GenerateContentConfig:
    """Records the kwargs the adapter built its config from, rather than validating them."""

    kwargs: dict[str, Any]


def _config(**kwargs: Any) -> GenerateContentConfig:
    return GenerateContentConfig(kwargs=kwargs)


def _types() -> SimpleNamespace:
    return SimpleNamespace(
        GenerateContentConfig=_config,
        ThinkingConfig=lambda **kwargs: SimpleNamespace(**kwargs),
        ThinkingLevel=_ThinkingLevel,
        Content=lambda **kwargs: SimpleNamespace(**kwargs),
        Part=SimpleNamespace(from_text=lambda text: SimpleNamespace(text=text)),
    )


def install(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``from google.genai import types`` resolve to the fake for this test only."""
    google = ModuleType("google")
    genai = ModuleType("google.genai")
    genai.types = _types()  # type: ignore[attr-defined]
    google.genai = genai  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.genai", genai)


@dataclass
class FakeClient:
    """``client.models.generate_content`` that records each call and answers ``reply``."""

    reply: str = '{"items": []}'
    calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def models(self) -> FakeClient:
        return self

    def generate_content(self, *, model: str, contents: Any, config: Any) -> Any:
        self.calls.append({"model": model, "contents": contents, "config": config.kwargs})
        return SimpleNamespace(text=self.reply, usage_metadata=None)
