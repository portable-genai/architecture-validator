"""Configuration and the adapter factory (dependency injection for the hexagon).

The factory reads ``config/settings.yaml`` (with ``${ENV_VAR}`` interpolation) and binds
each port to a concrete adapter by dotted path. Switching the whole system from the GCP
managed stack to an on-prem stack is a one-line change of ``profile`` — proof of the
ports-and-adapters / no-lock-in principle (P-02). Every adapter follows one construction
convention: ``Adapter(settings: Settings)``.
"""

from __future__ import annotations

import importlib
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml
from hex_service_kit.netdefaults import ConfiguredEmptyError, EnvSetting, read_env_setting

from .envread import setting_or_default
from .ports.identity import CLIENT_ASSERTED, declared_end_user_auth

_ENV_PATTERN = re.compile(r"\$\{([A-Z0-9_]+)(?::-(.*?))?\}")

_PROFILE_ENV = "ARCH_VALIDATOR_PROFILE"

#: Every profile the container binds an adapter family for. Membership is exact and
#: case-sensitive: every posture decision downstream compares the profile string exactly, so
#: ``Local`` would select none of the relaxations but also none of the restrictions.
#: Normalising the case here would turn a typo into a silent choice; refusing it turns the
#: typo into a construction failure.
RUNTIME_PROFILES = frozenset({"local", "gcp", "platform", "onprem"})

#: The profile string handed to every relaxation when ``ARCH_VALIDATOR_PROFILE`` was never
#: set. It is deliberately NOT a member of :data:`RUNTIME_PROFILES` and never reaches
#: :class:`Settings`: it exists so that "no choice was made" is a distinct input to the
#: security layers rather than being indistinguishable from a chosen ``local``.
UNCONSENTED_PROFILE = "unconfigured"


def _validate_profile(profile: str) -> str:
    """Fail closed on a profile string nothing binds, INCLUDING a capitalisation typo."""
    if profile not in RUNTIME_PROFILES:
        expected = ", ".join(sorted(RUNTIME_PROFILES))
        raise ValueError(f"unknown {_PROFILE_ENV} {profile!r}; expected one of: {expected}")
    return profile


#: Profiles that mean "running on managed cloud infrastructure", for the banner's runtime half.
_MANAGED_PROFILES: frozenset[str] = frozenset({"gcp"})

#: The port whose ACTIVE binding decides what the provenance banner's model half says.
#: Named once here so rebinding it for a profile changes the banner in the same edit.
_GENERATOR_PORT: str = "llm"

#: Where this service's managed model id lives, as a dotted attribute path on ``Settings``, or
#: the empty string when it keeps none there.
#:
#: Most of the fleet pins the id in its settings file rather than in the adapter, under a name
#: chosen per repository. Resolving it from a path named ONCE here keeps the banner reading the
#: same value the adapter passes to the model call, instead of a second copy that drifts.
_GENERATOR_MODEL_ATTR: str = "models.reasoning"

#: Constant names a managed adapter may declare its model id under. Several spellings because
#: the fleet uses several, and a resolver that knew only one would report a bound model as
#: unnamed.
_MODEL_CONSTANTS: tuple[str, ...] = ("_MODEL", "_DEFAULT_MODEL")


def _model_from_settings(settings: object, path: str) -> str:
    """The model id at ``path``, or ``""`` when the deployment has not pinned one.

    Honours the hard-reasoning opt-in where a repository has one. A deployment that flips
    ``models.use_hard_reasoning`` sends reasoning-tier calls to the stronger model, so a banner
    that kept naming ``models.reasoning`` would state a model the service is no longer calling.
    """
    models = getattr(settings, "models", None)
    # Read through getattr into a local rather than touching `models.hard_reasoning` after the
    # guard: `models` is deliberately untyped here (not every repo has one) so the checker
    # cannot narrow it, and the attribute access is a real union-attr error.
    hard_reasoning = getattr(models, "hard_reasoning", "")
    if (
        path == "models.reasoning"
        and getattr(models, "use_hard_reasoning", False)
        and hard_reasoning
    ):
        return str(hard_reasoning)
    value: object = settings
    for part in path.split("."):
        value = getattr(value, part, None)
        if value is None:
            return ""
    return str(value or "")


def _declared_model(binding: str) -> str:
    """The model id the bound managed adapter declares, or an honest statement that it names none.

    Resolved from the BINDING rather than from a settings string, which is the point: a settings
    field would be a claim ABOUT the binding, and the two drift the first time somebody rebinds a
    profile without remembering the second field. Importing the adapter module here is safe with
    no cloud SDK installed -- every cloud import in these adapters lives inside the method that
    needs it, which is the portability property the parity suite already asserts.

    Returns ``""`` when the adapter declares no model constant, which is the common case: most
    of the fleet pins the id in settings instead, and :attr:`Settings.generator_model` reads
    that first. An empty answer here is "not declared on the adapter", never "no model".
    """
    from importlib import import_module

    module_path, _, class_name = binding.partition(":")
    try:
        module = import_module(module_path)
    except ImportError:  # pragma: no cover - the bound module is importable offline
        return "managed-model-unavailable"
    for holder in (module, getattr(module, class_name, None)):
        for name in _MODEL_CONSTANTS:
            value = getattr(holder, name, None)
            if value:
                return str(value)
    return ""


@dataclass(frozen=True, slots=True)
class ProfileChoice:
    """The ONE resolution of ``ARCH_VALIDATOR_PROFILE``, and what each consumer keys off.

    Every module that needs the profile goes through :func:`resolve_profile` (or the
    :class:`Settings` properties derived from it). No module may re-derive it with its own
    ``os.environ.get("ARCH_VALIDATOR_PROFILE", "local")``: that fallback reads an UNSET
    variable as consent, which is the fail-open this type exists to remove
    (``tests/unit/test_profile_single_source.py`` fails the build if one reappears).

    The two derived profile strings differ because the two decisions fail closed in OPPOSITE
    directions, so a single "effective profile" string would harden one and weaken the other.
    """

    #: Which adapter family to bind. Absent consent this is still ``local`` (the SDK-free
    #: adapters), because the alternative would import cloud SDKs that are not installed; the
    #: local IDENTITY adapter refuses to construct when :attr:`explicit` is False, so an
    #: unconsented run has data adapters but no end-user identity.
    profile: str = "local"
    #: Was the profile named DELIBERATELY (env var, or a reviewed ``profile:`` in settings)?
    explicit: bool = True

    @property
    def exposure_profile(self) -> str:
        """The profile every *relaxation* keys off: the CORS dev-origin fallback.

        That decision grants something extra to ``local``, so an unconsented run must NOT
        look like ``local``: it gets :data:`UNCONSENTED_PROFILE`, which is no origin's
        allowlist.
        """
        return self.profile if self.explicit else UNCONSENTED_PROFILE

    @property
    def bind_profile(self) -> str:
        """The profile the bind guard keys off, where ``local`` is the RESTRICTIVE case.

        ``resolve_bind_host`` confines ``local`` to loopback and lets fronted profiles take
        ``0.0.0.0``, so here an unconsented run must look like ``local`` and stay on loopback.
        """
        return self.profile if self.explicit else "local"


def _profile_setting(environ: Mapping[str, str] | None) -> EnvSetting:
    """Return the single profile choice with absent and configured-empty kept distinct."""
    if environ is None:
        return read_env_setting(_PROFILE_ENV)
    raw = environ.get(_PROFILE_ENV)
    return EnvSetting(name=_PROFILE_ENV, raw=raw, value="" if raw is None else raw.strip())


def resolve_profile(
    environ: Mapping[str, str] | None = None, *, configured: str = ""
) -> ProfileChoice:
    """Read ``ARCH_VALIDATOR_PROFILE`` once, treating absent/blank as NO CHOICE, not ``local``.

    Three states, where unset is not a member of the valid set: the variable is absent (no
    choice was made), it is present but blank (refused here: emptying it expressed an intent
    and it names no profile), or it names a value, which is validated so a typo is a failure
    rather than a silent posture. ``configured`` is
    the reviewed ``profile:`` key from ``config/settings.yaml``, which counts as a deliberate
    choice because a human wrote it into a reviewed file; the environment still wins over it.
    """
    setting = _profile_setting(environ)
    if setting.is_configured_empty:
        raise ConfiguredEmptyError(
            f"{_PROFILE_ENV} is set to an empty value, which is not a profile. Unset it to "
            "leave the choice to settings.yaml, or set one of "
            f"{', '.join(sorted(RUNTIME_PROFILES))}."
        )
    raw = setting.value if setting.has_value else (configured or "").strip()
    if raw:
        _validate_profile(raw)
    return ProfileChoice(profile=raw or "local", explicit=bool(raw))


def _interpolate(value: Any) -> Any:
    """Interpolate settings while keeping absent and configured-empty distinct.

    ``${VAR:-default}`` is a resolver too: ``os.environ.get(name, default)`` would hand an
    emptied variable the reviewed default, reintroducing the collapse one layer below where
    no scan of adapter call sites would find it.
    """
    if isinstance(value, str):

        def repl(m: re.Match[str]) -> str:
            setting = read_env_setting(m.group(1))
            if setting.is_configured_empty:
                raise ConfiguredEmptyError(
                    f"{m.group(1)} is set to an empty value; unset it to inherit the reviewed "
                    "settings default, or give it a value"
                )
            return (m.group(2) or "") if setting.is_unset else setting.value

        return _ENV_PATTERN.sub(repl, value)
    if isinstance(value, dict):
        return {k: _interpolate(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_interpolate(v) for v in value]
    return value


@dataclass(frozen=True)
class ModelSettings:
    #: The Vertex location the model client calls, NOT the compute region. Gemini 3
    #: serves the `us` and `eu` multi-regions only; `global` carries no residency
    #: guarantee. See models.location in config/settings.yaml.
    location: str = "us"
    reasoning: str = "gemini-3.5-flash"
    triage: str = "gemini-3.5-flash"
    hard_reasoning: str = "gemini-3.5-flash"  # Preview — feature-flagged off by default
    use_hard_reasoning: bool = False


@dataclass(frozen=True)
class PolicySettings:
    # OPA REST service (Cloud Run) that evaluates the bundled rego policies.
    opa_url: str = ""
    bundle_path: str = "src/architecture_validator/policies"
    decision_path: str = "arch/validate"
    allowed_regions: tuple[str, ...] = (
        "asia-southeast1",
        "australia-southeast1",
        "australia-southeast2",
        "asia-east2",
        "asia-northeast1",
    )
    review_all_reports: bool = True
    high_severities: tuple[str, ...] = ("high", "critical")

    def __post_init__(self) -> None:
        if not self.allowed_regions:
            raise ValueError("policy.allowed_regions must not be empty")
        if any(not value.strip() for value in self.allowed_regions):
            raise ValueError("policy.allowed_regions must contain non-empty values")
        if not isinstance(self.review_all_reports, bool):
            raise ValueError("policy.review_all_reports must be true or false")
        if not self.review_all_reports:
            raise ValueError("policy.review_all_reports is an immutable production safety floor")
        if not self.high_severities:
            raise ValueError("policy.high_severities must not be empty")
        allowed_severities = {"low", "medium", "high", "critical"}
        invalid = {value.lower() for value in self.high_severities} - allowed_severities
        if invalid:
            raise ValueError(f"policy.high_severities contains invalid values: {sorted(invalid)}")


@dataclass(frozen=True)
class AssetSettings:
    """Cloud Asset Inventory live-scan scope (the gcp IaCScannerPort)."""

    scope: str = ""  # projects/PROJECT_ID | folders/ID | organizations/ID
    content_type: str = "RESOURCE"
    page_size: int = 500


@dataclass(frozen=True)
class SccSettings:
    """Security Command Center settings for enriching live residency findings."""

    organization: str = ""  # organizations/ID
    finding_filter: str = 'category="DATA_RESIDENCY" OR category="PUBLIC_BUCKET_ACL"'


@dataclass(frozen=True)
class ResidencyPolicySettings:
    """The residency policy the residency scan gate grades against (mirrors ResidencyPolicy).

    Kept distinct from :class:`PolicySettings` (the OPA principle-engine config) — the two
    ``policy``-family blocks are ``policy:`` (OPA) and ``residency_policy:`` (this) in
    ``settings.yaml``.
    """

    allowed_regions: tuple[str, ...] = (
        "asia-southeast1",
        "australia-southeast1",
        "australia-southeast2",
        "asia-east2",
        "asia-northeast1",
    )
    required_controls: tuple[str, ...] = (
        "cmek",
        "vpc_sc",
        "no_public_egress",
        "no_global_endpoint",
    )
    gate_severity: str = "high"


@dataclass(frozen=True)
class KnowledgeBaseSettings:
    # File Search data store (A2 Enterprise KB) on the Agent Platform.
    data_store_id: str = "architecture-validator-reg-kb"
    location: str = "asia-southeast1"
    serving_config: str = "default_search"
    engine_id: str = "architecture-validator-engine"


@dataclass(frozen=True)
class LoggingSettings:
    log_name: str = "architecture-validator-audit"
    bucket: str = "architecture-validator-worm"
    retention_days: int = 2557  # ~7 years


@dataclass(frozen=True)
class AgentEngineSettings:
    resource_name: str = ""  # reasoningEngine resource id, set after deploy
    display_name: str = "architecture-validator"


@dataclass(frozen=True)
class LocalSettings:
    """Paths for the SDK-free ``local`` profile stores (SQLite FTS5 + append-only audit).

    The ``local`` profile is a WORKING offline laptop stack (a real third deployment
    option beside ``gcp`` and the fail-fast ``onprem``): it runs the whole intake
    pipeline with no Google Cloud, no API key and no running emulators by default. Empty
    strings select the per-package default under ``~/.architecture_validator/``; tests pass
    ``:memory:`` for ephemeral, deterministic stores. No Google Cloud here.
    """

    db_path: str = ""  # SQLite FTS5 reg-KB index; "" => ~/.architecture_validator/local.db
    audit_path: str = ""  # append-only audit store; "" => ~/.architecture_validator/audit.db


@dataclass(frozen=True)
class Settings:
    project_id: str = "your-gcp-project"
    region: str = "asia-southeast1"
    profile: str = "local"  # local (default, SDK-free) | gcp | platform | onprem
    kms_key: str = ""  # projects/.../cryptoKeys/... (regional)
    models: ModelSettings = field(default_factory=ModelSettings)
    policy: PolicySettings = field(default_factory=PolicySettings)
    knowledge_base: KnowledgeBaseSettings = field(default_factory=KnowledgeBaseSettings)
    asset: AssetSettings = field(default_factory=AssetSettings)
    scc: SccSettings = field(default_factory=SccSettings)
    residency_policy: ResidencyPolicySettings = field(default_factory=ResidencyPolicySettings)
    logging: LoggingSettings = field(default_factory=LoggingSettings)
    agent_engine: AgentEngineSettings = field(default_factory=AgentEngineSettings)
    local: LocalSettings = field(default_factory=LocalSettings)
    # Was the profile chosen DELIBERATELY, or merely inherited from the fallback? ``load``
    # sets this False when ARCH_VALIDATOR_PROFILE is absent AND settings.yaml names no
    # profile. Direct construction is deliberate by definition (a caller named the profile in
    # code), so the default is True. The seeded-persona identity adapter refuses to construct
    # when this is False: an intake gate must never hand out an approver persona, with no
    # authentication at all, because an env var went missing.
    profile_explicit: bool = True
    # port_name -> { profile -> "module.path:ClassName" }
    adapters: dict[str, dict[str, str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        _validate_profile(self.profile)

    @property
    def exposure_profile(self) -> str:
        """The profile every relaxation keys off (see :meth:`ProfileChoice.exposure_profile`)."""
        return ProfileChoice(self.profile, self.profile_explicit).exposure_profile

    @property
    def bind_profile(self) -> str:
        """The profile the bind guard keys off (see :meth:`ProfileChoice.bind_profile`)."""
        return ProfileChoice(self.profile, self.profile_explicit).bind_profile

    @staticmethod
    def load(path: str | os.PathLike[str] | None = None) -> Settings:
        path = Path(path or setting_or_default("ARCH_VALIDATOR_SETTINGS", "config/settings.yaml"))
        raw = _interpolate(yaml.safe_load(path.read_text())) if path.exists() else {}
        raw = raw or {}
        nested = {
            "models": ModelSettings(**(raw.pop("models", {}) or {})),
            "policy": _policy_settings(raw.pop("policy", {}) or {}),
            "knowledge_base": KnowledgeBaseSettings(**(raw.pop("knowledge_base", {}) or {})),
            "asset": AssetSettings(**(raw.pop("asset", {}) or {})),
            "scc": SccSettings(**(raw.pop("scc", {}) or {})),
            "residency_policy": _residency_policy_from(raw.pop("residency_policy", {}) or {}),
            "logging": LoggingSettings(**(raw.pop("logging", {}) or {})),
            "agent_engine": AgentEngineSettings(**(raw.pop("agent_engine", {}) or {})),
            "local": LocalSettings(**(raw.pop("local", {}) or {})),
        }
        # Three-state resolution: unset/blank is NO CHOICE, not ``local``. ``profile`` and
        # ``profile_explicit`` come only from here, so a settings file cannot assert consent
        # on the operator's behalf by writing ``profile_explicit: true``.
        choice = resolve_profile(configured=str(raw.pop("profile", "") or ""))
        reserved = {"profile", "profile_explicit"}
        known = {f for f in Settings.__dataclass_fields__ if f not in nested and f not in reserved}
        flat = {k: v for k, v in raw.items() if k in known}
        # ``flat`` / ``nested`` are validated against the dataclass fields above; the
        # heterogeneous **dict unpack is intentional (YAML-driven construction).
        return Settings(
            profile=choice.profile,
            profile_explicit=choice.explicit,
            **flat,
            **nested,  # type: ignore[arg-type]
        )

    def build_residency_policy(self) -> Any:
        """Build the domain ``ResidencyPolicy`` from the configured ``residency_policy`` block.

        Named ``build_residency_policy`` (not ``residency_policy``) so it does not collide
        with the ``residency_policy`` settings field it reads.
        """
        from .domain.models import Severity
        from .domain.residency.models import ResidencyControl, ResidencyPolicy

        controls = frozenset(
            ResidencyControl(c) for c in self.residency_policy.required_controls if _is_control(c)
        )
        return ResidencyPolicy(
            allowed_regions=frozenset(self.residency_policy.allowed_regions),
            required_controls=controls,
            gate_severity=Severity(self.residency_policy.gate_severity),
        )

    @property
    def runtime(self) -> str:
        """WHERE this process runs, as the UI banner states it: ``gcp`` or ``local``.

        Derived from the profile, never sniffed from the environment. A console that read its
        runtime from ``window.location`` would be right until the day the deployment served
        through a proxy and wrong silently after that, so the service is the party asked.

        ``onprem`` reads ``local`` because that is its entire point, and a managed model call
        does not make a process cloud-hosted: this states where the PROCESS runs, and
        :attr:`generator_model` states whose model answers.
        """
        return "gcp" if self.profile in _MANAGED_PROFILES else "local"

    @property
    def generator_model(self) -> str:
        """WHICH model answers, as the UI banner states it (org decision, 2026-08-30).

        These systems are demonstrated on a laptop and on a deployment, sometimes in the same
        hour, and a screenshot of one is indistinguishable from the other. A viewer who cannot
        tell which they are looking at cannot tell whether a figure came from a managed model or
        a deterministic offline stub, which is exactly the confusion an audit-first pitch cannot
        afford. So the page states it, always, rather than the presenter stating it sometimes.

        ``no-model`` is deliberately NOT ``deterministic-offline-stub``. The stub string claims a
        model-shaped port bound to a stub; ``no-model`` says there is no such port at all, and a
        reviewer approving an escalation is entitled to know which of the two they are reading.
        """
        if not _GENERATOR_PORT:
            return "no-model"
        table = self.adapters.get(_GENERATOR_PORT) or {}
        binding = str(table.get(self.profile, "") or "")
        if not binding:
            return "no-model"
        if self.profile not in _MANAGED_PROFILES:
            # The on-prem adapters are fail-fast migration placeholders: they raise rather than
            # generating, so naming a model would advertise one that never answers.
            if self.profile == "onprem":
                return "onprem-not-implemented"
            return "deterministic-offline-stub"
        # Managed. The id lives in settings in most of the fleet and on the adapter in a few,
        # so both are read here and the banner never names a model the binding does not use.
        if _GENERATOR_MODEL_ATTR:
            named = _model_from_settings(self, _GENERATOR_MODEL_ATTR)
            if named:
                return named
            # The field exists and this deployment has not pinned a model. Saying so is
            # actionable; naming a default would advertise one the deployment never calls.
            return "managed-model-unset"
        declared = _declared_model(binding)
        if declared:
            return declared
        # Neither a settings field nor an adapter constant. This managed path is a
        # deployment-wired placeholder that raises rather than generating, so there is no model
        # to name -- which is a different statement from one that exists and is unset.
        return "managed-not-implemented"


def _residency_policy_from(raw: dict[str, Any]) -> ResidencyPolicySettings:
    """Coerce a YAML residency_policy block (lists) into the frozen settings (tuples)."""
    default = ResidencyPolicySettings()
    return ResidencyPolicySettings(
        allowed_regions=tuple(raw.get("allowed_regions", default.allowed_regions)),
        required_controls=tuple(raw.get("required_controls", default.required_controls)),
        gate_severity=str(raw.get("gate_severity", default.gate_severity)),
    )


def _policy_settings(raw: dict[str, Any]) -> PolicySettings:
    """Coerce list-valued YAML policy fields into the immutable settings contract."""
    allowed = {
        "opa_url",
        "bundle_path",
        "decision_path",
        "allowed_regions",
        "review_all_reports",
        "high_severities",
    }
    unknown = set(raw) - allowed
    if unknown:
        raise ValueError(f"unknown policy settings: {sorted(unknown)}")
    default = PolicySettings()
    review_all = raw.get("review_all_reports", default.review_all_reports)
    if not isinstance(review_all, bool):
        raise ValueError("policy.review_all_reports must be true or false")
    regions_raw = raw.get("allowed_regions", default.allowed_regions)
    severities_raw = raw.get("high_severities", default.high_severities)
    if not isinstance(regions_raw, (list, tuple)) or not isinstance(severities_raw, (list, tuple)):
        raise ValueError("policy region and severity fields must be lists")
    return PolicySettings(
        opa_url=str(raw.get("opa_url", default.opa_url)),
        bundle_path=str(raw.get("bundle_path", default.bundle_path)),
        decision_path=str(raw.get("decision_path", default.decision_path)),
        allowed_regions=tuple(str(value).strip() for value in regions_raw),
        review_all_reports=review_all,
        high_severities=tuple(str(value).strip().lower() for value in severities_raw),
    )


def _is_control(value: str) -> bool:
    from .domain.residency.models import ResidencyControl

    return value in {c.value for c in ResidencyControl}


def instantiate(dotted: str, settings: Settings) -> Any:
    """Import ``module.path:ClassName`` and construct it with ``settings``."""
    module_path, _, class_name = dotted.partition(":")
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    return cls(settings)


class Container:
    """Lazily-built registry of port -> adapter instances.

    Adapters are imported only on first access so that, e.g., a unit test using the
    on-prem profile never needs the Google Cloud SDKs installed.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def _bind(self, port_name: str) -> Any:
        binding = self.settings.adapters.get(port_name, {})
        dotted = binding.get(self.settings.profile)
        if not dotted:
            raise KeyError(
                f"No adapter configured for port '{port_name}' "
                f"under profile '{self.settings.profile}'."
            )
        return instantiate(dotted, self.settings)

    # One cached_property per port keeps wiring declarative and type-greppable.
    @cached_property
    def policy_engine(self) -> Any:
        return self._bind("policy_engine")

    @cached_property
    def knowledge_base(self) -> Any:
        return self._bind("knowledge_base")

    @cached_property
    def control_mapping(self) -> Any:
        return self._bind("control_mapping")

    @cached_property
    def residency(self) -> Any:
        return self._bind("residency")

    @cached_property
    def scanner(self) -> Any:
        return self._bind("scanner")

    @cached_property
    def llm(self) -> Any:
        return self._bind("llm")

    @cached_property
    def audit(self) -> Any:
        return self._bind("audit")

    @cached_property
    def tracer(self) -> Any:
        return self._bind("tracer")

    @cached_property
    def evaluation(self) -> Any:
        return self._bind("evaluation")

    @cached_property
    def registry(self) -> Any:
        return self._bind("registry")

    @cached_property
    def tool_catalog(self) -> Any:
        return self._bind("tool_catalog")

    @cached_property
    def identity(self) -> Any:
        return self._bind("identity")

    @cached_property
    def review_router(self) -> Any:
        return self._bind("review_router")


def build_container(settings: Settings | None = None) -> Container:
    return Container(settings or Settings.load())


def identity_adapter_class(settings: Settings) -> type:
    """The identity adapter CLASS the active binding names, resolved WITHOUT constructing it.

    Reads the same ``adapters:`` table the container binds from, so a deployment that rebound
    the identity port in ``config/settings.yaml`` (the documented on-premises path: swap the
    placeholder for the client's own IdP adapter) is answered about the adapter it ACTUALLY
    runs, not about the one the profile name suggests.

    Constructing is deliberately avoided: the seeded-persona adapter refuses to construct under
    an inherited profile, so a posture computed from an instance would be unobtainable in one
    of the exact cases it has to describe.
    """
    target = settings.adapters["identity"][settings.profile]
    module_path, _, class_name = target.partition(":")
    resolved = getattr(importlib.import_module(module_path), class_name)
    if not isinstance(resolved, type):
        raise TypeError(f"identity binding {target!r} does not name a class")
    return resolved


def end_user_auth_kind(settings: Settings | None = None) -> str:
    """What the BOUND identity adapter declares it does for end-user authentication.

    This is the one question "are this service's end-user routes authenticated?" reduces to.
    See ``ports/identity.py``: the profile string cannot answer it, because ``onprem`` names a
    placeholder today and a real IdP once a client rebinds it.

    Any failure to establish the answer resolves to ``CLIENT_ASSERTED``. A guard that switches
    OFF because a lookup raised is a guard that fails open, and nothing is lost by failing
    closed here: the same failure surfaces loudly at the first request, when the container
    resolves the identical binding for real.
    """
    try:
        return declared_end_user_auth(identity_adapter_class(settings or Settings.load()))
    except Exception:
        return CLIENT_ASSERTED
