"""Pytest fixtures: the seeded ``local`` adapters + assembled domain services.

The unit suite is driven by the **real** ``local`` deployment adapters
(:mod:`architecture_validator.adapters.local`), not bespoke fakes: each fixture constructs the
registered local adapter with an in-memory ``Settings`` (``:memory:`` SQLite), so the
in-process implementation lives **once** under ``adapters/local`` and is what both the
offline tests and the offline CLI exercise. This is the test-dedup the build brief asks
for: the old hand-written fakes are gone.

The adapters are deterministic and seedable, so the suite stays reproducible with **no
Google Cloud SDK and no network**:

* ``LocalPolicyEngineAdapter`` evaluates the 12 principles via the shared deterministic
  evaluator (:mod:`architecture_validator.domain.principles_eval`), so the local engine and the
  bundled default agree by construction.
* ``LocalFtsKnowledgeBaseAdapter`` is a SQLite FTS5 index self-seeded from the built-in
  synthetic reg corpus; ``empty_knowledge_base`` seeds it with nothing.
* ``LocalDeterministicLLMAdapter`` is schema-driven: it reads the unmet findings the
  injection schema renders into the prompt and returns a deterministic ``items`` array,
  one element per unmet principle, so the requirement-injection mapping is exercised.

A couple of thin recording subclasses (``FakePolicyEngine``) are kept so a test can
construct an adapter with no ``Settings`` argument or override one method; they reproduce
the local adapter's deterministic behaviour rather than re-implementing a fake.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest

from architecture_validator.adapters.local.audit import LocalAppendOnlyAuditAdapter
from architecture_validator.adapters.local.control_mapping import LocalControlMappingAdapter
from architecture_validator.adapters.local.evaluation import LocalOfflineEvalAdapter
from architecture_validator.adapters.local.knowledge import LocalFtsKnowledgeBaseAdapter
from architecture_validator.adapters.local.llm import LocalDeterministicLLMAdapter
from architecture_validator.adapters.local.policy import LocalPolicyEngineAdapter
from architecture_validator.adapters.local.registry import LocalRegistryAdapter
from architecture_validator.adapters.local.scan_residency import LocalScanResidencyAdapter
from architecture_validator.adapters.local.scanner import LocalSeededScannerAdapter
from architecture_validator.adapters.local.tool_catalog import LocalToolCatalogAdapter
from architecture_validator.adapters.local.tracer import LocalNoopTracerAdapter
from architecture_validator.config import LocalSettings, Settings
from architecture_validator.domain.models import LlmRequest, LlmResponse
from architecture_validator.domain.residency.models import ResourceConfig
from tests.fixtures import sample_resources

#: A loopback peer for every API test. The app-object exposure guard refuses the
#: unauthenticated local posture to any other peer, and ``TestClient``'s default peer is the
#: literal host ``"testclient"``, which is not loopback. See
#: ``tests/unit/test_serving_path_exposure.py``.
LOOPBACK_PEER = ("127.0.0.1", 50000)


# --------------------------------------------------------------------------- #
# In-memory settings: point the SQLite-backed local stores at ``:memory:`` so the
# fixtures are ephemeral and deterministic (no files written by the test run).
# --------------------------------------------------------------------------- #
def _settings() -> Settings:
    return Settings(local=LocalSettings(db_path=":memory:", audit_path=":memory:"))


# --------------------------------------------------------------------------- #
# Thin recording subclass: a no-Settings constructor for the few tests that build
# a policy engine directly (and an override point for the OPA-down resilience test).
# --------------------------------------------------------------------------- #
class FakePolicyEngine(LocalPolicyEngineAdapter):
    """The local policy engine, constructible with no ``Settings`` (test convenience)."""

    def __init__(self, settings: Settings | None = None) -> None:
        super().__init__(settings or _settings())


# --------------------------------------------------------------------------- #
# Residency scan fixtures. The seeded live-scanner is the one
# recording wrapper genuinely new to this repo: the local scanner adapter does not
# record the scopes it was asked to scan, and the residency unit tests assert on that
# (``scanner.calls``). Everything else the residency tests need — recording audit /
# tracer / llm — is already native to the ``local`` adapters used by the plain
# ``audit`` / ``tracer`` / ``llm`` fixtures above, so no extra doubles are introduced.
# --------------------------------------------------------------------------- #
# The scope the seeded scanner uses for the in-process default estate.
_SCAN_SCOPE = "*"


class FakeScanner(LocalSeededScannerAdapter):
    """Local seeded scanner (IaCScannerPort) that records the scopes it was asked to scan.

    ``FakeScanner()`` seeds the synthetic ``MIXED_RESOURCES`` estate and
    ``FakeScanner([...])`` seeds an explicit estate. The behaviour is the real
    :class:`LocalSeededScannerAdapter` over ``:memory:`` SQLite.
    """

    def __init__(self, resources: list[ResourceConfig] | None = None) -> None:
        super().__init__(_settings())
        estate = tuple(sample_resources.MIXED_RESOURCES) if resources is None else tuple(resources)
        # Re-seed the default scope with the requested estate (overrides the built-in seed).
        self.seed(estate, scope=_SCAN_SCOPE)
        self.resources: list[ResourceConfig] = list(estate)
        self.calls: list[str] = []

    def scan(self, target: str) -> list[ResourceConfig]:
        self.calls.append(target)
        return super().scan(target)


class BlowingUpLLM:
    """LLM that always raises — proves remediation failure never fails the gate.

    The one deliberate failure double: a seedable local adapter cannot express
    "always raise", so this stays a thin test stub (it is not a registered adapter).
    """

    def generate(self, request: LlmRequest) -> LlmResponse:
        raise RuntimeError("LLM unavailable")

    def classify(self, text: str, labels: list[str]) -> str:
        raise RuntimeError("LLM unavailable")


# --------------------------------------------------------------------------- #
# Service construction — locate the domain service classes wherever they live.
# --------------------------------------------------------------------------- #
_SERVICE_MODULE_CANDIDATES = (
    "architecture_validator.domain.validation_service",
    "architecture_validator.domain.injection_service",
    # Residency domain services (ViolationDetector / ResidencyScanService).
    "architecture_validator.domain.residency.scan_service",
    "architecture_validator.domain.residency.detector",
    "architecture_validator.domain.services",
    "architecture_validator.domain.orchestration",
)
_POLICY_MODULE_CANDIDATES = (
    "architecture_validator.domain.hitl",
    # Residency maker-checker policy (HumanReviewPolicy).
    "architecture_validator.domain.residency.hitl",
    "architecture_validator.domain.policies",
    "architecture_validator.domain.services",
)


def _resolve(symbol: str, candidates: tuple[str, ...]) -> Any:
    last: Exception | None = None
    for mod_name in candidates:
        try:
            module = importlib.import_module(mod_name)
        except ModuleNotFoundError as exc:  # pragma: no cover - layout fallback
            last = exc
            continue
        obj = getattr(module, symbol, None)
        if obj is not None:
            return obj
    raise ImportError(f"Could not locate domain symbol {symbol!r} in any of {candidates}") from last


def load_service(name: str) -> Any:
    return _resolve(name, _SERVICE_MODULE_CANDIDATES)


def load_policy(name: str) -> Any:
    return _resolve(name, _POLICY_MODULE_CANDIDATES)


# --------------------------------------------------------------------------- #
# Pytest fixtures — every one constructs a seeded local adapter.
# --------------------------------------------------------------------------- #
@pytest.fixture
def policy_engine() -> LocalPolicyEngineAdapter:
    return LocalPolicyEngineAdapter(_settings())


@pytest.fixture
def knowledge_base() -> LocalFtsKnowledgeBaseAdapter:
    # Self-seeds the built-in synthetic reg corpus on first use.
    return LocalFtsKnowledgeBaseAdapter(_settings())


@pytest.fixture
def empty_knowledge_base() -> LocalFtsKnowledgeBaseAdapter:
    kb = LocalFtsKnowledgeBaseAdapter(_settings())
    kb.seed([])  # simulate an empty KB
    return kb


@pytest.fixture
def llm() -> LocalDeterministicLLMAdapter:
    return LocalDeterministicLLMAdapter(_settings())


@pytest.fixture
def control_mapping() -> LocalControlMappingAdapter:
    return LocalControlMappingAdapter(_settings())


@pytest.fixture
def residency() -> LocalScanResidencyAdapter:
    # The in-process residency client (LocalScanResidencyAdapter) runs the residency scan
    # service directly, so this fixture exercises the real signal rather than a no-op.
    return LocalScanResidencyAdapter(_settings())


@pytest.fixture
def tracer() -> LocalNoopTracerAdapter:
    return LocalNoopTracerAdapter(_settings())


@pytest.fixture
def audit() -> LocalAppendOnlyAuditAdapter:
    return LocalAppendOnlyAuditAdapter(_settings())


@pytest.fixture
def evaluation() -> LocalOfflineEvalAdapter:
    return LocalOfflineEvalAdapter(_settings())


@pytest.fixture
def registry() -> LocalRegistryAdapter:
    return LocalRegistryAdapter(_settings())


@pytest.fixture
def tool_catalog() -> LocalToolCatalogAdapter:
    return LocalToolCatalogAdapter(_settings())


@pytest.fixture
def validation_service(
    policy_engine, knowledge_base, llm, tracer, audit, control_mapping, residency
):
    """ValidationService wired with the local adapters (arg order mirrors SPEC §5)."""
    cls = load_service("ValidationService")
    return cls(
        policy_engine,
        knowledge_base,
        llm,
        tracer,
        audit,
        control_mapping,
        residency,
    )


@pytest.fixture
def injection_service(llm, tracer):
    """RequirementInjectionService(llm, tracer)."""
    cls = load_service("RequirementInjectionService")
    return cls(llm, tracer)


# --------------------------------------------------------------------------- #
# Residency scan fixtures.
# --------------------------------------------------------------------------- #
@pytest.fixture
def scanner() -> FakeScanner:
    return FakeScanner()


@pytest.fixture
def detector():
    """ViolationDetector with the default ResidencyPolicy."""
    cls = load_service("ViolationDetector")
    return cls()


@pytest.fixture
def scan_service(scanner, detector, llm, tracer, audit):
    """ResidencyScanService(scanner, detector, llm, tracer, audit) — no router bound."""
    cls = load_service("ResidencyScanService")
    return cls(scanner, detector, llm, tracer, audit)
