"""Service-to-service (S2S) transport hardening shared by the platform adapters.

The ``platform`` profile's adapters are thin HTTP clients to the sibling
horizontal-platform and de-risking services. Base URLs must be ``https://`` outside
loopback (caught at adapter construction); when ``S2S_TOKEN`` is set every request
carries it as an ``Authorization: Bearer`` header, and ``S2S_SIGNING_KEY``
optionally propagates a verified end-user actor as an HMAC-signed ``X-Av-Actor`` /
``X-Av-Actor-Sig`` pair.

Both credentials resolve in three states. UNSET attaches no
header, which is what lets the offline gate and a loopback sibling run with zero secrets.
SET-AND-EMPTY raises :class:`hex_service_kit.netdefaults.ConfiguredEmptyError`: a
credential an operator deliberately emptied is an expressed intent, and reading it as
absent is how an emptied secret leaves as an unauthenticated call with nothing refusing
anywhere in this process.

**Sourced from the shared ``hex-service-kit`` commons.** This module
passes this repo's env-var and header names to :mod:`hex_service_kit.s2s`, so a fix to
the S2S transport rule is a version bump of the package rather than an N-repo edit.
"""

from __future__ import annotations

from hex_service_kit.s2s import client_headers, validate_base_url

#: Env var holding the bearer credential for S2S calls. UNSET attaches no header (the offline
#: zero-secret posture); SET-AND-EMPTY raises rather than inheriting that default.
TOKEN_ENV = "S2S_TOKEN"
#: Env var holding the HMAC key for signing the propagated end-user actor.
SIGNING_KEY_ENV = "S2S_SIGNING_KEY"
_ACTOR_HEADER = "X-Av-Actor"
_ACTOR_SIG_HEADER = "X-Av-Actor-Sig"

__all__ = ["SIGNING_KEY_ENV", "TOKEN_ENV", "headers", "validate_base_url"]


def headers(actor: str = "") -> dict[str, str]:
    """Auth headers for one S2S request (bearer token + optional signed actor)."""
    return client_headers(
        actor,
        token_env=TOKEN_ENV,
        signing_key_env=SIGNING_KEY_ENV,
        actor_header=_ACTOR_HEADER,
        actor_sig_header=_ACTOR_SIG_HEADER,
    )
