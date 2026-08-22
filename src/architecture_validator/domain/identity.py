"""Identity value objects, re-exported from the commons rather than redeclared.

The validator never trusts a client-asserted ``actor`` or ACL. A :class:`Principal` is
resolved server-side by an :class:`~architecture_validator.ports.identity.IdentityPort` adapter
(local dev persona, GCP IAP-verified assertion, or an on-prem client IdP) from the inbound
transport context, and becomes the audit actor plus the entitlement principals fed into
governed retrieval.

None of these types is written out here any more. :class:`Principal`,
:class:`RequestContext`, :class:`IdentityError` and :data:`ANONYMOUS` come from
:mod:`hex_service_kit.identity`, where they are declared once for the whole catalog. This
repo's copies were byte-identical to the originals apart from a docstring, which is exactly
the state that precedes drift: sixteen repositories hand-copied this set and the copies had
already diverged before anyone compared them. A value type copied into N repos is N types,
and ``isinstance`` cannot tell them apart -- so ``tests/contract/test_port_parity.py``
asserts object IDENTITY (``is``), which a look-alike copy cannot satisfy.

Still pure standard library at import time: ``hex_service_kit.identity`` imports no web
framework and no cloud SDK, so the domain core stays framework-free and the SDK-free
``local`` and ``onprem`` profiles are unaffected.

The SEEDED PERSONAS are deliberately NOT taken from the commons. ``DEFAULT_PERSONAS`` there
carries generic ``group:analyst`` / ``group:approver`` entitlements; this repo's local
adapter seeds C3's own vocabulary (``group:arch-reviewer``, ``group:arch-approver``,
``group:audit``) so a local demo exercises the real intake maker-checker gate. That lives in
``adapters/local/identity.py``, which is where deployment-specific data belongs.
"""

from __future__ import annotations

from hex_service_kit.identity import (
    ANONYMOUS as ANONYMOUS,
)
from hex_service_kit.identity import (
    IdentityError as IdentityError,
)
from hex_service_kit.identity import (
    Principal as Principal,
)
from hex_service_kit.identity import (
    RequestContext as RequestContext,
)

__all__ = ["ANONYMOUS", "IdentityError", "Principal", "RequestContext"]
