"""ADK FunctionTools that expose the C3 domain services to the agent.

Each tool is a thin, side-effect-honest wrapper: it builds the relevant domain service
from a :class:`~architecture_validator.config.Container` (so every port is bound to the adapter
selected by the active profile), invokes the service, and returns a JSON-safe dict via
:func:`~architecture_validator.domain.serialization.to_jsonable`.

Design notes
------------
* The domain services own orchestration (evaluate -> ground -> inject -> review -> audit;
  SPEC §5). These tools deliberately add **no** business logic of their own.
* ``google.adk`` is imported lazily inside :func:`build_function_tools` so this module
  imports cleanly under the on-prem/test profile with no ADK installed (SPEC §4). The
  plain Python tool callables are importable and unit-testable without ADK.
* Every callable carries a precise type-hinted signature and docstring: ADK derives the
  tool's name, description and JSON parameter schema from them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..config import Container, Settings, build_container

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from google.adk.tools import FunctionTool

_DEFAULT_ACTOR = "architecture-validator-agent"


def _container(settings: Settings | None) -> Container:
    """Build the DI container, honouring an optionally-injected ``Settings``."""
    return build_container(settings)


def _to_submission(submission: dict[str, Any]):  # -> ProjectSubmission
    from ..domain.models import ProjectSubmission

    return ProjectSubmission(
        id=str(submission.get("id", "")),
        name=str(submission.get("name", "")),
        description=str(submission.get("description", "")),
        requirements=str(submission.get("requirements", "")),
        declared_region=submission.get("declared_region"),
        declared_controls=tuple(submission.get("declared_controls", []) or ()),
        uses_pii=bool(submission.get("uses_pii", False)),
        uses_rag=bool(submission.get("uses_rag", False)),
        uses_fine_tuning=bool(submission.get("uses_fine_tuning", False)),
        has_exit_plan=bool(submission.get("has_exit_plan", False)),
        attributes={str(k): str(v) for k, v in (submission.get("attributes") or {}).items()},
    )


def validate_project(
    submission: dict[str, Any],
    actor: str = _DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Validate a project submission against the 12 General Principles.

    Returns a JSON-safe ValidationReport: the verdict (PASS only if no principle FAILs),
    one finding per principle, and the auto-injected non-functional requirements. Flagged
    for human review on any FAIL (maker-checker, P-06).

    Args:
      submission: the project submission (id, name, description, requirements,
        declared_region, declared_controls, uses_pii, uses_rag, uses_fine_tuning,
        has_exit_plan, attributes).
      actor: authenticated user / service identity the request is made for.
    """
    from ..api.deps import build_validation_service
    from ..domain.serialization import to_jsonable

    service = build_validation_service(_container(settings))
    return to_jsonable(service.validate(_to_submission(submission), actor))


def inject_requirements(
    submission: dict[str, Any],
    actor: str = _DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Return the missing non-functional requirements for a submission's unmet principles.

    Evaluates the submission, then drafts one injected requirement per unmet (FAIL /
    NEEDS_INFO) principle, each tied to the principle and cited.

    Args:
      submission: the project submission (same shape as ``validate_project``).
      actor: authenticated user / service identity the request is made for.
    """
    from ..domain import principles_eval
    from ..domain.serialization import to_jsonable

    container = _container(settings)
    sub = _to_submission(submission)
    findings = principles_eval.evaluate_all(sub)
    citations = []
    try:
        citations = container.knowledge_base.retrieve(sub.name)
    except Exception:  # noqa: BLE001 - KB is best-effort here
        citations = []
    from ..api.deps import build_injection_service

    injector = build_injection_service(container)
    return to_jsonable(injector.inject(sub, findings, list(citations)))


def list_principles(settings: Settings | None = None) -> list[dict[str, Any]]:
    """Return the 12 General Principles (P-01..P-12) the intake gate enforces."""
    from ..domain.principles import all_principles
    from ..domain.serialization import to_jsonable

    return to_jsonable(all_principles())


# The plain callables, in stable order, so the agent layer and tests share one list.
TOOL_FUNCTIONS = (
    validate_project,
    inject_requirements,
    list_principles,
)


def build_function_tools() -> list[FunctionTool]:
    """Wrap each domain-service callable as an ADK ``FunctionTool``.

    ADK introspects each function's signature and docstring to derive the tool name,
    description and parameter JSON schema. ``google.adk`` is imported here (lazily) so the
    module is import-safe without ADK installed (SPEC §4).
    """
    from google.adk.tools import FunctionTool

    return [FunctionTool(func=fn) for fn in TOOL_FUNCTIONS]
