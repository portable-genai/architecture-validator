"""FastAPI application for the C3 Architecture & Requirements Validator.

Exposes the validation gate (``POST /validate`` -> ValidationReport), the 12 General
Principles (``GET /principles``), health, the local persona list (``GET /v1/personas``),
and the A2A AgentCard at ``/.well-known/agent-card.json``. The React/Next.js UI and the
CLI consume this surface.

Design constraints:

* **Import-safe.** Building the :class:`~architecture_validator.config.Container` is deferred to
  request time via the ``deps`` factories, so importing this module (or ``app``) never
  touches Google Cloud. The on-prem/test profile imports it with no GCP SDK installed.
* **A blocked / failing validation is not an HTTP error.** A FAIL verdict is a normal
  200 response carrying ``passed=false`` and ``requires_human_review=true``.
* **Identity is server-verified.** Every artifact route takes a :class:`CurrentPrincipal`
  resolved by the active profile's :class:`IdentityPort`; the request body carries no
  ``actor`` (any client-asserted identity is ignored). The verified subject is the audit
  actor.
* **Region pinned** to ``asia-southeast1`` (Singapore) for data residency (SPEC §2).

Run locally with ``python -m architecture_validator.api.app`` (uvicorn on :8088).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from hex_service_kit import cors_allowlist, resolve_bind_host
from hex_service_kit.web import add_loopback_exposure_guard

from ..config import end_user_auth_kind
from ..domain.principles import all_principles
from ..domain.residency.models import ResourceConfig
from ..domain.residency.scan_service import ResidencyScanService
from ..domain.services import ValidationService
from ..envread import boolean_setting, read_env_setting, setting_or_default
from ..ports.identity import VERIFIED
from . import deps
from .schemas import (
    AgentCardModel,
    HealthResponse,
    PrincipleModel,
    PrinciplesResponse,
    ResidencyPolicyModel,
    ResidencyScanResponse,
    ScanRequest,
    ValidateRequest,
    ValidationReportResponse,
)
from .security import CurrentPrincipal

# Local Next.js dev origins the browser UI is served from during development.
_DEV_ORIGINS = ["http://localhost:3000", "http://127.0.0.1:3000"]

# Embedding-surface controls. In secure/embedded mode the validator is served same-origin
# via the parent app's reverse-proxy (no CORS needed); for the cross-origin / standalone
# dev case, ARCH_VALIDATOR_CORS_ORIGINS is an explicit per-tenant allowlist (never "*").
# ARCH_VALIDATOR_FRAME_ANCESTORS is the CSP frame-ancestors allowlist of parent origins
# permitted to iframe the validator UI.
_FRAME_ANCESTORS_ENV = "ARCH_VALIDATOR_FRAME_ANCESTORS"

# The legacy equivalent of each frame-ancestors value that has one, for browsers with no CSP
# support. Any other value names specific parent origins, which X-Frame-Options cannot express.
_LEGACY_FRAME_OPTIONS = {"'self'": "SAMEORIGIN", "'none'": "DENY"}


#: Entries that are a wildcard by BEHAVIOUR rather than by spelling, so the asterisk test below
#: cannot see them. ``null`` is the one that matters: a SANDBOXED iframe presents the origin
#: ``null``, so allowing it hands framing and credentialed cross-origin rights to any page able
#: to open one. ``'*'`` is what a quoted Terraform variable or a YAML string renders, and ``*.*``
#: is a host pattern matching every name with a dot in it. The same set is refused on the
#: document half, in ``ui/lib/csp.mjs``.
_WILDCARD_TOKENS = frozenset({"*", "'*'", "null", "*.*"})


def _refuse_wildcard(origins: list[str], setting: str) -> None:
    """A list naming ``*`` is not an allowlist, so refuse it where the value is resolved.

    Both resolutions below run at import, which makes this a BOOT refusal: a deployment
    configured with a wildcard never starts, rather than serving every origin until somebody
    reads a header. The rule was already written down (``never "*"``, above) and the code
    passed the value straight through, so one operator typo granted ``frame-ancestors *``
    (any page may iframe the console) or a credentialed CORS wildcard (every site on the
    internet gets this service's cookies, since ``allow_credentials=True``).

    An EQUALITY test of ``origin.strip() == "*"`` sees an entry
    that IS an asterisk and not one that CONTAINS one: ``https://*.client.example`` went
    straight through, and CSP honours that host-source form, so every subdomain could frame the
    console including one obtained by takeover or serving user content. Nothing downstream
    inspected these values either, so the other spellings reached a response header verbatim.
    Both halves of the rule are needed: a real origin never contains the character and is never
    one of :data:`_WILDCARD_TOKENS`, so this refuses nothing a deployment could correctly hold.
    """
    offending = [
        origin for origin in origins if "*" in origin or origin.strip() in _WILDCARD_TOKENS
    ]
    if offending:
        raise ValueError(f"{setting} origin policy must never contain a wildcard, got {offending}")


def _frame_ancestors(raw: str | None) -> str:
    """Three-state read of ``ARCH_VALIDATOR_FRAME_ANCESTORS``; an emptied value REFUSES framing.

    Unset keeps the shipped ``'self'``. Set to a value naming no origin, a two-state read emits
    ``Content-Security-Policy: frame-ancestors`` with an EMPTY directive, which is a CSP parse
    error, so browsers drop the directive; the ``== "'self'"`` test below is false as well, so
    ``X-Frame-Options`` goes unsent too and the clickjacking control vanishes on both paths.
    An operator who empties the allowlist means "nobody may frame this", which is spelled
    ``'none'``, so that is what the emptied state produces: the operator's expressed intent,
    and the most restrictive value the directive has.
    """
    if raw is None:
        return "'self'"
    ancestors = raw.split()
    _refuse_wildcard(ancestors, _FRAME_ANCESTORS_ENV)
    return " ".join(ancestors) or "'none'"


_frame_setting = read_env_setting(_FRAME_ANCESTORS_ENV)
_FRAME_ANCESTORS = _frame_ancestors(None if _frame_setting.is_unset else _frame_setting.raw)


def _cors_origins() -> list[str]:
    """Explicit allowlist, never "*"; the localhost dev fallback applies ONLY under a
    deliberately chosen local profile (shared hex-service-kit rule).

    Keys off ``exposure_profile``, not ``profile``: this is a RELAXATION, so a run where
    nobody set ARCH_VALIDATOR_PROFILE must not look like ``local`` and must get no
    cross-origin trust at all.

    The local refusal runs FIRST, on the raw configured value, rather than on what the kit
    hands back. ``cors_allowlist`` now refuses the same wildcards itself, so on the old order
    the kit raised its own ``InsecureCorsError`` before this module's rule was ever reached and
    the policy quietly changed owner. Refusing on the way in keeps :func:`_refuse_wildcard` the
    one authority over both allowlists: a single exception type and a single message naming the
    variable an operator must fix, whether the value came from CORS or from frame-ancestors.
    The kit's check stays as an unreachable backstop, which is what a backstop should be.
    """
    configured = read_env_setting("ARCH_VALIDATOR_CORS_ORIGINS").value
    _refuse_wildcard(
        [origin.strip() for origin in configured.split(",") if origin.strip()],
        "ARCH_VALIDATOR_CORS_ORIGINS",
    )
    return cors_allowlist(
        deps.get_settings().exposure_profile,
        origins_env="ARCH_VALIDATOR_CORS_ORIGINS",
        dev_origins=tuple(_DEV_ORIGINS),
    )


app = FastAPI(
    title="C3 Architecture & Requirements Validator",
    version="0.1.0",
    description=(
        "Policy-as-code intake gate that validates a project against the 12 General "
        "Principles (P-01..P-12), cross-checks the regulatory KB, and auto-injects the "
        "missing non-functional requirements. Built ports-and-adapters on the Gemini "
        "Enterprise Agent Platform (region asia-southeast1)."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Dev-Persona"],
)


@app.middleware("http")
async def _security_headers(request: Request, call_next: Any) -> Any:
    """Emit embedding-surface headers: CSP frame-ancestors (who may iframe the validator).

    ``X-Frame-Options`` backs the policy up on browsers with no CSP support, for both values
    that it can express: ``'self'`` -> SAMEORIGIN and ``'none'`` -> DENY.
    """
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = f"frame-ancestors {_FRAME_ANCESTORS}"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    # HSTS is a positive secure-profile capability. Local/on-prem development and an
    # unconsented settings object are not known to be behind TLS and must not advertise it.
    if deps.get_settings().profile in {"gcp", "platform"}:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    legacy = _LEGACY_FRAME_OPTIONS.get(_FRAME_ANCESTORS)
    if legacy is not None:
        response.headers["X-Frame-Options"] = legacy
    return response


# A request arrives with nothing authenticating the END USER unless BOTH of these hold, and
# the guard bounds every case where either fails:
#
#   1. a profile was chosen. Absent that, nobody selected an identity scheme, the seeded
#      persona adapter refuses to construct, and every artifact route answers 401; but
#      /healthz, /principles, /policy, /v1/personas and the agent card would still answer a
#      stranger, and a deployment in that state has no business being reachable at all. It is
#      also the one case where a settings file that bound a verifying adapter must NOT buy the
#      relaxation: unset is not consent, whatever the binding says;
#   2. the identity adapter the ACTIVE binding names DECLARES that it verifies the end user.
#      Seeded personas arrive on the X-Dev-Persona header the caller wrote (client-asserted)
#      and the on-premises placeholder resolves nobody at all (unimplemented); neither
#      authenticates anyone, so neither may switch this off. Read from the binding rather than
#      from the profile string, so a client that rebinds ``onprem`` to its own verifying IdP
#      adapter is answered about the adapter it actually runs.
_END_USER_AUTHENTICATED = deps.get_settings().profile_explicit and end_user_auth_kind() == VERIFIED

# Registered LAST, so it is the OUTERMOST middleware: an off-loopback caller is refused before
# CORS, before the header baseline above and before any route or dependency runs. Bound to the
# APP OBJECT, not to `main()`: the Dockerfile CMD is
# `exec uvicorn architecture_validator.api.app:app --host 0.0.0.0 --port ${PORT}`, so the
# `resolve_bind_host(...)` call down in `main()` never runs in a shipped process. Executed
# before this guard existed: a LAN peer got 200 on GET /v1/personas with the full
# seeded-persona list AND 200 on GET /principles with the whole P-01..P-12 corpus, machine
# rules included. Do not delete this: without it the container's own CMD re-opens both.
add_loopback_exposure_guard(
    app,
    unauthenticated=not _END_USER_AUTHENTICATED,
    # The SAME opt-in `main()` passes to resolve_bind_host, so an operator who accepts the
    # exposure accepts it once, for both the bind and the request-time guard.
    insecure_demo_env="ARCH_VALIDATOR_ALLOW_INSECURE_DEMO",
    # The EXPOSURE profile, so a run nobody configured names itself 'unconfigured' in the
    # refusal rather than borrowing the name of a profile an operator never chose.
    posture=deps.get_settings().exposure_profile,
)


@app.post("/validate", response_model=ValidationReportResponse, tags=["validate"])
def validate(
    request: ValidateRequest,
    principal: CurrentPrincipal,
    service: Annotated[ValidationService, Depends(deps.get_validation_service)],
) -> ValidationReportResponse:
    """Validate a project submission against the 12 General Principles at intake (R6).

    Returns a cited ValidationReport: the overall verdict (PASS only if no principle
    FAILs), the per-principle findings, and the auto-injected non-functional requirements.
    The audit actor is the server-verified principal, never a client-supplied field.
    """
    report = service.validate(
        request.submission.to_domain(), actor=principal.actor, tenant=principal.tenant
    )
    return ValidationReportResponse.from_domain(report)


@app.get("/principles", response_model=PrinciplesResponse, tags=["principles"])
def principles() -> PrinciplesResponse:
    """Return the 12 General Principles (P-01..P-12) the gate enforces."""
    return PrinciplesResponse(principles=[PrincipleModel.from_domain(p) for p in all_principles()])


@app.post("/scan", response_model=ResidencyScanResponse, tags=["scan"])
def scan(
    request: ScanRequest,
    principal: CurrentPrincipal,
    service: Annotated[ResidencyScanService, Depends(deps.get_scan_service)],
) -> ResidencyScanResponse:
    """Scan a target / inline plan / resource list and return a PASS/FAIL ResidencyScan.

    Provide exactly one of ``target`` (a plan/.tf path or a project scope), ``plan_json``
    (an inline plan), or ``resources`` (an already-parsed list). The audit actor is the
    server-verified :class:`Principal`, never a client-supplied value.
    """
    actor = principal.actor
    if request.resources is not None:
        resources = [
            ResourceConfig(
                address=r.address,
                type=r.type,
                region=r.region,
                attributes=dict(r.attributes),
                source_ref=r.source_ref,
            )
            for r in request.resources
        ]
        result = service.scan_resources("inline-resources", resources, actor)
    elif request.plan_json is not None:
        resources = _resources_from_plan_json(request.plan_json)
        result = service.scan_resources("inline-plan", resources, actor)
    else:
        target = request.target or ""
        is_scope = target.startswith(("projects/", "folders/", "organizations/"))
        action = "scan_project" if is_scope else "scan_iac"
        result = service.scan_target(target, actor, action=action)
    return ResidencyScanResponse.from_domain(result)


@app.get("/policy", response_model=ResidencyPolicyModel, tags=["scan"])
def policy() -> ResidencyPolicyModel:
    """Return the active residency policy (allowed regions, required controls, gate)."""
    return ResidencyPolicyModel.from_domain(deps.get_settings().build_residency_policy())


@app.get("/healthz", response_model=HealthResponse, tags=["ops"])
def healthz() -> HealthResponse:
    """Liveness/readiness probe. Reports the active profile and pinned region."""
    settings = deps.get_settings()
    return HealthResponse(
        status="ok",
        profile=settings.profile,
        region=settings.region,
        runtime=settings.runtime,
        generator_model=settings.generator_model,
    )


@app.get("/v1/personas", tags=["ops"])
def personas() -> list[dict[str, str]]:
    """List seeded dev personas for the local persona picker (empty outside local profile).

    Local mode runs with no IdP; the UI uses this to let a demo/test pick an identity
    (and thus exercise per-user authorization) via the ``X-Dev-Persona`` header. Secure
    profiles resolve identity from the IAP assertion, so this returns an empty list. So does
    a run where nobody chose a profile: the seeded-persona adapter refuses to construct, and
    advertising personas that cannot be resolved would be worse than advertising none.
    """
    from ..domain.identity import IdentityError

    try:
        identity = deps.get_container().identity
    except IdentityError:
        return []
    lister = getattr(identity, "personas", None)
    if lister is None:
        return []
    return [dict(p) for p in lister()]


@app.get("/.well-known/agent-card.json", response_model=AgentCardModel, tags=["governance"])
def agent_card() -> AgentCardModel:
    """Publish this validator's A2A AgentCard for discovery (A3 Registry / interop)."""
    from ..agent.agent_card import build_agent_card

    settings = deps.get_settings()
    return AgentCardModel.from_domain(build_agent_card(settings))


def _resources_from_plan_json(plan: dict) -> list[ResourceConfig]:
    """Parse an inline ``terraform show -json`` document into ResourceConfig objects.

    Reuses the pure-Python plan walker by writing the document to a temp file, so the
    inline path grades identically to the file path the CI gate uses.
    """
    import json
    import tempfile
    from pathlib import Path

    from ..pipelines import terraform

    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
        json.dump(plan, fh)
        path = Path(fh.name)
    try:
        return terraform.parse_plan_json(path)
    finally:
        path.unlink(missing_ok=True)


def main() -> None:
    """Run the API locally with uvicorn (Cloud Run / Agent Runtime use this app object)."""

    import uvicorn

    uvicorn.run(
        "architecture_validator.api.app:app",
        # Fail-closed bind (shared hex-service-kit rule): the no-auth local
        # profile binds loopback unless ARCH_VALIDATOR_ALLOW_INSECURE_DEMO=1; secure profiles keep
        # 0.0.0.0 (container-local; ingress is fronted by the platform). Keys off
        # ``bind_profile``, the opposite direction to the CORS relaxation above: here ``local``
        # is the RESTRICTIVE case, so a run where nobody chose a profile stays on loopback.
        host=resolve_bind_host(
            deps.get_settings().bind_profile,
            host_env="ARCH_VALIDATOR_API_HOST",
            insecure_demo_env="ARCH_VALIDATOR_ALLOW_INSECURE_DEMO",
        ),
        port=int(setting_or_default("PORT", "8088")),
        reload=boolean_setting("ARCH_VALIDATOR_API_RELOAD"),
    )


if __name__ == "__main__":
    main()
