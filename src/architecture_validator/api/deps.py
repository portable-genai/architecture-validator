"""FastAPI dependency wiring for the C3 Architecture Validator.

This module builds a single, process-wide :class:`~architecture_validator.config.Container`
(the ports-and-adapters registry) and assembles the orchestration services from the
Container's port instances. The Container is created lazily on first access so importing
this module — and therefore the FastAPI app — never touches Google Cloud: a unit test or
the on-prem profile can import the API with no GCP SDK installed.

Each ``get_*`` factory is a FastAPI ``Depends`` provider. Services take *explicit port
instances* in their constructors (SPEC §5), so the wiring here is the single place that
knows which ports each service needs.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Any

from fastapi import Depends

from ..adapters.controls import RecordingReviewRouter
from ..config import Container, Settings, build_container
from ..domain.hitl import ReviewPolicy
from ..domain.models import Severity
from ..domain.residency.detector import ViolationDetector
from ..domain.residency.scan_service import ResidencyScanService
from ..domain.services import RequirementInjectionService, ValidationService


@lru_cache(maxsize=1)
def get_container() -> Container:
    """Return the process-wide Container, building it on first use."""
    return build_container(Settings.load())


def get_settings() -> Settings:
    """Convenience accessor for the active settings (region, profile, ...)."""
    return get_container().settings


# --------------------------------------------------------------------------- #
# Service factories — assemble each service from the Container's ports.
# Constructor argument order mirrors SPEC §5 exactly.
# --------------------------------------------------------------------------- #


def get_request_review_router() -> RecordingReviewRouter:
    """The review router for ONE request, wrapped so the response reports the hand-off.

    FastAPI resolves a dependency once per request, so the route and the service it builds
    receive the same wrapper and the route reads what the service's hand-off did.
    """
    return RecordingReviewRouter(get_container().review_router)


#: Injected by FastAPI; ``None`` when a getter is called directly (the MCP server may), which
#: binds the container's router unwrapped unless the caller passes its own wrapper.
RequestReviewRouter = Annotated[RecordingReviewRouter | None, Depends(get_request_review_router)]


def get_validation_service(review_router: RequestReviewRouter = None) -> ValidationService:
    """Assemble the ValidationService from the process-wide Container (SPEC §5)."""
    return build_validation_service(get_container(), review_router=review_router)


def get_injection_service() -> RequirementInjectionService:
    """RequirementInjectionService(llm, tracer)."""
    return build_injection_service(get_container())


def get_scan_service(review_router: RequestReviewRouter = None) -> ResidencyScanService:
    """Assemble the ResidencyScanService from the process-wide Container."""
    return build_scan_service(get_container(), review_router=review_router)


# --------------------------------------------------------------------------- #
# Container-explicit factories.
#
# The ``get_*`` factories above use the cached, process-wide Container (right for the
# long-lived FastAPI app). The CLI and the ADK tools build their own Container per
# invocation — honouring ``ARCH_VALIDATOR_PROFILE`` at call time — so they call these
# ``build_*`` variants with an explicit Container. Argument order mirrors SPEC §5.
# --------------------------------------------------------------------------- #


def build_validation_service(
    container: Container, *, review_router: Any = None
) -> ValidationService:
    """Assemble a :class:`ValidationService` from an explicit Container.

    ``review_router`` replaces the container's for one call: a caller that reports the
    hand-off passes a :class:`RecordingReviewRouter` wrapping the container's router.
    """
    return ValidationService(
        policy_engine=container.policy_engine,
        knowledge_base=container.knowledge_base,
        llm=container.llm,
        tracer=container.tracer,
        audit=container.audit,
        control_mapping=container.control_mapping,
        residency=container.residency,
        review_policy=ReviewPolicy(
            review_all_reports=container.settings.policy.review_all_reports,
            high_severities=frozenset(
                Severity(value) for value in container.settings.policy.high_severities
            ),
        ),
        allowed_regions=container.settings.policy.allowed_regions,
        review_router=review_router or container.review_router,
    )


def build_injection_service(container: Container) -> RequirementInjectionService:
    """Assemble a :class:`RequirementInjectionService` from an explicit Container."""
    return RequirementInjectionService(llm=container.llm, tracer=container.tracer)


def build_scan_service(container: Container, *, review_router: Any = None) -> ResidencyScanService:
    """Assemble a :class:`ResidencyScanService` from an explicit Container.

    The detector is built from the container's configured ResidencyPolicy so the gate is
    graded against the deployment's policy (allowed regions, required controls, gate
    severity).
    """
    detector = ViolationDetector(container.settings.build_residency_policy())
    return ResidencyScanService(
        scanner=container.scanner,
        detector=detector,
        llm=container.llm,
        tracer=container.tracer,
        audit=container.audit,
        review_router=review_router or container.review_router,
    )


def create_app():  # -> fastapi.FastAPI
    """App factory used by ``uvicorn ...:create_app --factory`` (and the CLI ``serve``)."""
    from .app import app

    return app
