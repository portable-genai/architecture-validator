"""OPA policy-engine adapter (PolicyEnginePort) — the policy-as-code intake gate.

Backs the domain ``PolicyEnginePort`` with an **Open Policy Agent (OPA) REST service**
deployed on **Cloud Run** in ``asia-southeast1``. The adapter POSTs the project submission
plus the principle ruleset to OPA's data API (``POST /v1/data/<decision_path>``) and maps
the rego decision back onto domain :class:`PrincipleFinding` objects (one per principle).

The rego bundle that OPA evaluates is shipped as data under ``src/architecture_validator/policies``
and kept in lockstep with the deterministic in-process evaluator
(:mod:`architecture_validator.domain.principles_eval`), so the managed and credential-free paths
agree by construction. If OPA is unreachable or returns a non-2xx, this raises
:class:`PolicyEvaluationError`; the :class:`ValidationService` then falls back to the
in-process evaluator so a verdict is always produced (P-10).

``httpx`` is a core dependency, so no Google Cloud SDK is needed to construct this adapter.
The OPA base URL comes from ``settings.policy.opa_url``.
"""

from __future__ import annotations

import httpx

from ...config import Settings
from ...domain.errors import PolicyEvaluationError
from ...domain.models import (
    CheckStatus,
    Citation,
    Jurisdiction,
    Principle,
    PrincipleFinding,
    ProjectSubmission,
    Regulator,
    Severity,
)
from ...domain.serialization import to_jsonable

_TIMEOUT = httpx.Timeout(15.0, connect=5.0)
_SEVERITY_BY_VALUE = {s.value: s for s in Severity}
_STATUS_BY_VALUE = {s.value: s for s in CheckStatus}


class OpaPolicyAdapter:
    """HTTP client for an OPA REST service evaluating the principle rego bundle."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._base_url = (settings.policy.opa_url or "http://localhost:8181").rstrip("/")
        self._decision_path = settings.policy.decision_path.strip("/")

    def evaluate(
        self, submission: ProjectSubmission, principles: list[Principle]
    ) -> list[PrincipleFinding]:
        """Evaluate ``submission`` against ``principles`` via the OPA data API."""
        url = f"{self._base_url}/v1/data/{self._decision_path}"
        payload = {
            "input": {
                "submission": to_jsonable(submission),
                "principles": [to_jsonable(p) for p in principles],
                "policy": {"allowed_regions": list(self._settings.policy.allowed_regions)},
            }
        }
        try:
            response = httpx.post(url, json=payload, timeout=_TIMEOUT)
        except httpx.HTTPError as exc:
            raise PolicyEvaluationError(f"OPA request to {url} failed: {exc}") from exc
        if response.status_code // 100 != 2:
            raise PolicyEvaluationError(
                f"OPA {url} returned {response.status_code}: {response.text[:500]}"
            )
        body = response.json() or {}
        result = body.get("result") or {}
        return self._parse_findings(result)

    # ------------------------------------------------------------------ #
    # Result mapping (rego decision -> domain findings)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_findings(result: dict) -> list[PrincipleFinding]:
        raw_findings = result.get("findings") if isinstance(result, dict) else None
        if not isinstance(raw_findings, list):
            raise PolicyEvaluationError("OPA decision did not contain a 'findings' array")
        out: list[PrincipleFinding] = []
        for raw in raw_findings:
            if not isinstance(raw, dict):
                continue
            principle_id = str(raw.get("principle_id") or "").strip()
            if not principle_id:
                continue
            status = _STATUS_BY_VALUE.get(
                str(raw.get("status") or "").upper(), CheckStatus.NEEDS_INFO
            )
            severity = _SEVERITY_BY_VALUE.get(
                str(raw.get("severity") or "").lower(), Severity.MEDIUM
            )
            out.append(
                PrincipleFinding(
                    principle_id=principle_id,
                    status=status,
                    rule_id=str(raw.get("rule_id") or f"rule_{principle_id.lower()}"),
                    evidence=str(raw.get("evidence") or ""),
                    severity=severity,
                    remediation=str(raw.get("remediation") or ""),
                    citations=(
                        Citation(
                            source_id=principle_id,
                            regulator=Regulator.CROSS,
                            jurisdiction=Jurisdiction.GLOBAL,
                            title=f"General Principle {principle_id}",
                            url=f"https://rsk.internal/principles/{principle_id}",
                            version="2026",
                        ),
                    ),
                )
            )
        return out
