"""Span ATTRIBUTES carry structure, never content, and this is the test that can tell.

``LocalNoopTracerAdapter`` records span NAMES (``self.spans.append(name)``), which is right
for the tests that assert a pipeline opened its span and structurally blind to the one defect
that matters here: it throws the attributes away, so a span that started carrying the
submission's description, an injected requirement or a violating resource id would keep every
existing test green. A trace backend is not the WORM audit trail. It has no redaction stage, a
wider read audience and no retention rule written against a regulator's requirement, so an
attribute is OUTSIDE the boundary the audit sink holds (P-04, which the adapter's own
docstring claims for message content and nothing enforces for attributes).

C3 opens spans from two domain sites and this module drives both real request paths:
``ValidationService.validate`` (the intake gate, span ``validate``) and
``ResidencyScanService.scan_resources`` (the residency gate, span
``residency.scan``). The non-compliant submission and the violating estate are used
deliberately, because the FAIL path is the one that builds findings, injected requirements
and remediation text, and so is the path a leak would ride.
"""

from __future__ import annotations

from contextlib import AbstractContextManager

import pytest
from tests.conftest import FakeScanner, load_service
from tests.fixtures import sample_projects
from tests.fixtures import sample_resources as f

from architecture_validator.adapters.local.tracer import LocalNoopTracerAdapter
from architecture_validator.config import LocalSettings, Settings
from architecture_validator.domain.residency.detector import ViolationDetector

ACTOR = "arb.reviewer@bank.test"
SUBMISSION = sample_projects.NON_COMPLIANT_SUBMISSION

#: The complete attribute key set a C3 span may carry, per span name. Widening one of these
#: is a decision about what leaves the trust boundary, so it is made here rather than at a
#: call site.
_ALLOWED = {
    "validate": {"action", "actor"},
    "residency.scan": {"action", "actor"},
}

#: Submission content that exists in the fixtures and must never reach a span attribute:
#: the project name, the free-text description and the stated requirements.
_SUBMISSION_CONTENT = (
    SUBMISSION.id,
    SUBMISSION.name,
    SUBMISSION.description,
    SUBMISSION.requirements,
)


class _AttributeRecordingTracer(LocalNoopTracerAdapter):
    """Keeps (name, attributes) per span, unlike the name-only local adapter."""

    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        self.recorded: list[tuple[str, dict[str, str]]] = []

    def span(self, name: str, **attributes: str) -> AbstractContextManager[None]:
        self.recorded.append((name, dict(attributes)))
        return super().span(name, **attributes)


@pytest.fixture
def tracer() -> _AttributeRecordingTracer:  # type: ignore[override]
    """Override the conftest tracer so every service fixture assembles with THIS one."""
    return _AttributeRecordingTracer(
        Settings(local=LocalSettings(db_path=":memory:", audit_path=":memory:"))
    )


def _drive_every_span_site(validation_service, llm, tracer, audit) -> None:
    """Drive both real request paths on their FAIL branches."""
    validation_service.validate(SUBMISSION, actor=ACTOR)
    scan_service = load_service("ResidencyScanService")(
        FakeScanner(list(f.VIOLATING_RESOURCES)), ViolationDetector(), llm, tracer, audit
    )
    scan_service.scan_resources("violating-set", list(f.VIOLATING_RESOURCES), f.SAMPLE_ACTOR)


def test_the_request_paths_open_exactly_the_known_spans(
    validation_service, llm, tracer, audit
) -> None:
    _drive_every_span_site(validation_service, llm, tracer, audit)
    names = {name for name, _ in tracer.recorded}
    assert names == set(_ALLOWED), (
        "the set of spans these request paths open changed; a new span site is a "
        "trust-boundary decision, so record it in _ALLOWED here deliberately"
    )


def test_every_span_carries_allowlisted_keys_only(validation_service, llm, tracer, audit) -> None:
    _drive_every_span_site(validation_service, llm, tracer, audit)
    assert tracer.recorded, "the request paths opened no span at all"
    for name, attributes in tracer.recorded:
        assert name in _ALLOWED, f"unexpected span {name!r}; add it here deliberately"
        assert set(attributes) == _ALLOWED[name], (
            f"span {name!r} attribute keys changed; widening the set is a trust-boundary "
            "decision, so update _ALLOWED here deliberately"
        )


def test_no_span_attribute_carries_the_submission_content(
    validation_service, llm, tracer, audit
) -> None:
    """The project id, name, description and requirements stay out of the trace."""
    _drive_every_span_site(validation_service, llm, tracer, audit)
    emitted = " ".join(value for _, attributes in tracer.recorded for value in attributes.values())
    for content in _SUBMISSION_CONTENT:
        assert content not in emitted, f"span attribute leaked submission content: {content!r}"


def test_no_span_attribute_carries_the_scanned_estate(
    validation_service, llm, tracer, audit
) -> None:
    """Resource addresses and their source refs are scan findings, not span structure."""
    _drive_every_span_site(validation_service, llm, tracer, audit)
    emitted = " ".join(value for _, attributes in tracer.recorded for value in attributes.values())
    for resource in f.VIOLATING_RESOURCES:
        assert resource.address not in emitted, f"span attribute leaked {resource.address!r}"
        if resource.source_ref:
            assert resource.source_ref not in emitted, (
                f"span attribute leaked the source ref {resource.source_ref!r}"
            )


def test_every_attribute_value_is_a_string(validation_service, llm, tracer, audit) -> None:
    """The port declares str values; a structured object smuggles content past a grep."""
    _drive_every_span_site(validation_service, llm, tracer, audit)
    for name, attributes in tracer.recorded:
        for key, value in attributes.items():
            assert isinstance(value, str), f"span {name!r} attribute {key!r} is not a str"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
