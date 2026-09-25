"""Sampling is decided per call: pinned where the output is compared, free where it is prose.

**History.** This file began as "the grounded request must not sample by default". On
2026-08-26 two runs of one identical case against the `cdd-sow-research` deployment, minutes
apart, returned different scores, because a shared request builder defaulted to
`temperature=0.2`; the fix put `0.0` on the type and on both builders here, so a call site that
omitted the parameter could not sample.

**What changed (owner decision, 2026-09-23).** A blanket pin also flattened every call that
only drafts prose, and some models (Opus 5, Fable 5) reject the parameter outright. So the
temperature is now PINNED (`0.0`) only where the output is extracted, classified, scored or
compared, and FREE everywhere else, where free means the parameter is not sent at all, never
`1.0`. The request type and both builders default to `None`, and each call site states its
choice. In this service:

* pinned: the managed and live `classify` (a label compared against a fixed set);
* free: requirement drafting (`RequirementInjectionService`), the residency remediation
  narrative (`ResidencyScanService`) and the ADK root agent. None of them owns an outcome: the
  policy engine and the detector decide every verdict before the model is called.

**Temperature 0 is not a promise of determinism, and nothing here asserts one.** It is the
strongest thing a caller controls, and it is what makes a comparison between two runs a
measurement rather than a sample.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest
from tests.fixtures import fake_genai, sample_projects
from tests.fixtures import sample_resources as f

from architecture_validator.adapters.gcp.gemini_llm import GeminiLLMAdapter
from architecture_validator.adapters.local.llm import LocalDeterministicLLMAdapter
from architecture_validator.config import LocalSettings, Settings
from architecture_validator.domain import _grounded as _b0
from architecture_validator.domain import principles_eval
from architecture_validator.domain.kernel import LlmMessage, LlmRequest
from architecture_validator.domain.residency import _remediation as _b1


def test_the_request_type_leaves_sampling_to_the_call_site() -> None:
    assert LlmRequest.__dataclass_fields__["temperature"].default is None


@pytest.mark.parametrize("builder", [_b0.build_llm_request, _b1.build_llm_request])
def test_neither_builder_pins_a_temperature_the_call_site_did_not_choose(builder: object) -> None:
    assert inspect.signature(builder).parameters["temperature"].default is None  # type: ignore[arg-type]


def test_requirement_drafting_sends_no_temperature(
    injection_service: object, llm: LocalDeterministicLLMAdapter
) -> None:
    findings = principles_eval.evaluate_all(sample_projects.NON_COMPLIANT_SUBMISSION)
    injection_service.inject(  # type: ignore[attr-defined]
        sample_projects.NON_COMPLIANT_SUBMISSION, findings, []
    )
    assert llm.requests, "the drafting call never reached the model port"
    assert [request.temperature for request in llm.requests] == [None] * len(llm.requests)


def test_the_remediation_narrative_sends_no_temperature(
    scan_service: object, llm: LocalDeterministicLLMAdapter
) -> None:
    scan_service.scan_resources(  # type: ignore[attr-defined]
        "mixed", list(f.MIXED_RESOURCES), f.SAMPLE_ACTOR
    )
    assert llm.requests, "the remediation call never reached the model port"
    assert [request.temperature for request in llm.requests] == [None] * len(llm.requests)


def _gemini(monkeypatch: pytest.MonkeyPatch) -> tuple[GeminiLLMAdapter, fake_genai.FakeClient]:
    fake_genai.install(monkeypatch)
    adapter = GeminiLLMAdapter(Settings(local=LocalSettings(db_path=":memory:")))
    client = fake_genai.FakeClient(reply="drop")
    adapter._client = client
    return adapter, client


def _request(temperature: float | None) -> LlmRequest:
    return LlmRequest(messages=(LlmMessage(role="user", content="x"),), temperature=temperature)


def test_the_managed_adapter_omits_a_free_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    """Omitted, not sent as ``None`` or ``1.0``: a model that rejects it is never sent one."""
    adapter, client = _gemini(monkeypatch)
    adapter.generate(_request(None))
    assert "temperature" not in client.calls[-1]["config"]


def test_the_managed_adapter_sends_a_pinned_temperature(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, client = _gemini(monkeypatch)
    adapter.generate(_request(0.0))
    assert client.calls[-1]["config"]["temperature"] == 0.0


def test_the_managed_classification_is_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter, client = _gemini(monkeypatch)
    assert adapter.classify("text", ["spike", "drop"]) == "drop"
    assert client.calls[-1]["config"]["temperature"] == 0.0


def test_the_adk_root_agent_leaves_sampling_free() -> None:
    """Read from source: building the agent needs google-adk, which the gate never installs."""
    source = Path("src/architecture_validator/agent/root_agent.py").read_text(encoding="utf-8")
    config = source[source.index("types.GenerateContentConfig(") :]
    config = config[: config.index(")\n")]
    assert "temperature" not in config
