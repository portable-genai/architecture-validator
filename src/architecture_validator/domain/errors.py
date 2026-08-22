"""Domain exceptions for the Architecture & Requirements Validator (system C3).

Pure-Python exception hierarchy raised by the orchestration services. The domain
layer never imports Google Cloud, ADK, or any framework — these errors let callers
(API, CLI, the Agent Runtime adapter) react to domain-level failures without
coupling to any vendor SDK error type.
"""

from __future__ import annotations


class ValidatorError(Exception):
    """Base class for all domain-level errors raised by C3 services."""


class PolicyEvaluationError(ValidatorError):
    """Raised when the policy engine cannot evaluate the principle ruleset.

    The managed OPA adapter raises this on a transport/non-2xx failure. The
    deterministic in-process evaluator never raises it (it is pure Python), so the
    validation pipeline can always fall back to a credential-free evaluation.
    """


class KnowledgeBaseEmptyError(ValidatorError):
    """Raised when grounding context is required but the knowledge base returns none.

    The validation pipeline degrades gracefully (findings are emitted with a
    ``NEEDS_INFO`` provenance caveat rather than fabricated citations) instead of
    raising in normal operation; consumers that *require* KB grounding can raise this.
    """


class SubmissionInvalidError(ValidatorError):
    """Raised when a ``ProjectSubmission`` is malformed and cannot be validated."""


class ScanTargetError(ValidatorError):
    """Raised when a residency scan target cannot be resolved or parsed.

    A missing plan file, an unreadable ``.tf`` directory, or a malformed Terraform plan
    JSON document is a hard error for the residency scan: the CI gate must fail loudly
    rather than emit a misleading PASS over zero scanned resources.
    """
