"""Remote-platform evaluation adapter : thin HTTP client to Hrz4.

At promotion this vertical's quality is checked against the shared **Hrz4 AI Quality /
model-risk** service (``model-quality-gate``). This adapter implements
:class:`EvaluationGatePort` against Hrz4's hardened contract:

* ``evaluate`` -> ``POST /v1/evaluations {target, dataset_id, bundle}`` -> EvalReport.
* ``gate``     -> ``POST /v1/gate {target, dataset_id, bundle}`` -> ``{passed}``.

**Sourced from the shared ``agent-eval-kit`` commons.** The HTTP contract
is ``agent_eval_kit.gate_client.PromotionGateClient``; this adapter configures it (the
registered ``rsk3-architecture-validator`` bundle, the reasoning model, and this repo's S2S auth
headers), maps its report back to the domain :class:`EvalReport` the port returns, and
re-raises its errors as :class:`RemoteEvaluationError`.
"""

from __future__ import annotations

from agent_eval_kit.gate_client import GateClientError, PromotionGateClient

from ...config import Settings
from ...domain.errors import ValidatorError
from ...domain.models import EvalReport
from ...envread import setting_or_default
from . import _s2s

_DEFAULT_URL = "http://localhost:8084"

#: The registered Hrz4 metric bundle for this vertical (Hrz4 owns the metrics + bars).
_BUNDLE = "rsk3-architecture-validator"
#: Prompt/agent version tag; bump when the prompt corpus changes, or source it from a registry.
_PROMPT_VERSION = "v1"


class RemoteEvaluationError(ValidatorError):
    """Raised when the Hrz4 quality service returns a non-2xx response."""


class RemoteEvaluationAdapter:
    """HTTP client for the Hrz4 ``model-quality-gate`` service (via PromotionGateClient)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = PromotionGateClient(
            setting_or_default("HRZ_QUALITY_URL", _DEFAULT_URL),
            bundle=_BUNDLE,
            model=settings.models.reasoning,
            prompt_version=_PROMPT_VERSION,
            auth_headers=lambda: _s2s.headers(),
        )

    def evaluate(self, dataset_path: str) -> EvalReport:
        """Score ``dataset_path`` via Hrz4 and return the client's report UNCHANGED.

        A ``_to_domain`` mapper here, rebuilding a locally-declared ``EvalReport`` from
        three of the client's fields, is an identity function with a hole in it now that
        the domain re-exports the commons type: it drops ``run_id``, ``dataset_version``,
        ``dataset_digest``, ``evaluator``, ``schema_version``, ``artifact_refs`` and
        ``attested`` -- precisely the durable, attested evidence the client has just
        validated, and precisely what a model-risk reviewer needs to retrieve the run
        behind a promotion. Returning the client's report unchanged keeps that evidence
        attached to the verdict.
        """
        try:
            return self._client.evaluate(dataset_path)
        except GateClientError as exc:
            raise RemoteEvaluationError(str(exc)) from exc

    def gate(self, target: str) -> bool:
        """Promotion gate: True iff Hrz4 reports ``target`` passes."""
        try:
            return self._client.gate(target)
        except GateClientError as exc:
            raise RemoteEvaluationError(str(exc)) from exc
