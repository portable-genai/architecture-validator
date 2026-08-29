# Security FAQ

For an application-security team reviewing this repo before adopting it as a base. Answers
reflect the current code. Cross-references: [`ARCHITECTURE.md`](../../ARCHITECTURE.md),
[`COMPLIANCE.md`](../../COMPLIANCE.md),
[`docs/embedding-and-identity.md`](../embedding-and-identity.md).

### How is a request authenticated? Can a client spoof its identity?

No. Identity is resolved **server-side** from the transport context by an `IdentityPort`
adapter (`api/security.py`), never from the request body. The request schemas carry no
`actor` field (`api/schemas.py`), and any client-asserted actor or ACL is discarded. The
audit actor comes from the verified `Principal`. Per profile: `local` = seeded dev personas
selected by the `X-Dev-Persona` header (no IdP / AD / LDAP, offline demo and test only),
`gcp`/`platform` = the IAP-injected signed assertion verified at the edge, `onprem` = a
client IdP placeholder. A route with no resolvable principal returns 401.

### Is this multi-tenant? How is object-level isolation enforced?

There is no per-tenant stored evidence to isolate, so tenant isolation (check C2) is **N/A
by design**, and that is a deliberate, code-confirmed decision rather than a gap. The
reg-KB is a **shared regulatory corpus** (identical for every caller, no per-case or
per-tenant documents), and `/validate` is **stateless**: a submission goes in and a report
comes out with no ACL-scoped read-back. The `Principal` still carries `tenant` and
`principals` for the audit actor. If you fork this into a product that *does* store
per-tenant artifacts, you must add object-level authorization at that point; the reference
build does not need it.

### What about the service-to-service calls in the `platform` profile?

The platform adapters source their client from the shared `hex_service_kit.s2s`
(`adapters/platform/_s2s.py`). Every delegate validates its base URL at construction
(`https://` required outside loopback, rejected otherwise) and attaches an S2S bearer plus
the verified end-user actor as a signed header pair, not a spoofable JSON body field. The
six delegates are `remote_knowledge` (Rsk1), `remote_control_mapping` (Rsk1's
control-mapping module), `remote_residency` (a remote residency scanner), `remote_registry`
(Hrz3), `remote_audit` (Hrz5), and `remote_evaluation` (Hrz4). The receiving services own
verification.

### Does anything bind 0.0.0.0 by default?

No, not under the profile that serves the no-auth persona adapter. `main()` binds via
`hex_service_kit.resolve_bind_host`: under the `local` profile the API binds **loopback
(127.0.0.1)** and refuses a non-loopback interface unless
`ARCH_VALIDATOR_ALLOW_INSECURE_DEMO=1` is set. The Makefile defaults `API_HOST` to
`127.0.0.1`. Secure profiles keep the container-friendly `0.0.0.0` because ingress is
fronted by the platform. Proven by `tests/unit/test_netdefaults.py`.

### What HTTP security headers are set?

Both surfaces set CSP `frame-ancestors` (and the API sets `X-Frame-Options: SAMEORIGIN`).
CORS is an explicit allowlist (`ARCH_VALIDATOR_CORS_ORIGINS` via
`hex_service_kit.cors_allowlist`, never `*`; the localhost dev-origin fallback is
`local`-profile-only). **Known gap (check C6, PARTIAL):** the surfaces do not yet emit
`X-Content-Type-Options: nosniff`, `Referrer-Policy`, a full `default-src 'self'` /
scoped `connect-src` CSP, or API HSTS on secure profiles. Add these before exposing the
service; they are tracked in the practices audit, not silently missing.

### How tamper-evident is the audit trail? What are its limits?

The `local` audit store wraps the shared `hex_service_kit.audit.HashChainedAuditLog`: a
SHA-256 hash chain over canonical JSON, with SQLite `UPDATE`/`DELETE` blocked by triggers,
a JSONL export/restore path, and an exposed `verify_chain()`. The module docstring states
exactly which tamper classes are and are not caught (the chain alone carries no secret, so
it cannot by itself detect a full rewrite or tail truncation without an external anchor).
In production the `gcp` profile writes to a **locked WORM bucket**, which provides
non-rewritability itself. This repo does not replace the platform audit system (**Hrz5**);
see [features-faq.md](features-faq.md).

### Does the audit trail contain customer PII?

No. Rsk3 processes project metadata and design documents, **not customer PII** (stated in
`domain/models.py` and `COMPLIANCE.md`). No model, index, registry, audit, or human-review
call ingests PII, so there is no boundary redactor to review and no `pii_patterns` pack
(checks C3 / C4 are **N/A by design**). The audit event carries the submission summary and
the verdict only. `rule_p_04` still *checks* that the validated project honours P-04.

### Supply chain: are dependencies pinned and scanned?

Yes. Committed lockfiles (`requirements-dev.lock`, `requirements-gcp.lock`, uv pip compile,
py3.12) are installed in CI and the Docker build; the shared commons are pinned by tag with
the exact SHA in both locks; the base image is pinned by digest; GitHub Actions are
SHA-pinned; `dependabot.yml` proposes bumps; and a CI job runs `pip-audit` as a hard gate.
`ruff` is pinned exactly (its formatter output changes between releases).

### Where are secrets? Are any committed?

No secret values are in the repo. `config/settings.yaml` stores only the **names** of env
vars holding secrets and endpoints (`${VAR:-default}` interpolation, for example
`ARCH_VALIDATOR_KMS_KEY`, `ARCH_VALIDATOR_OPA_URL`, `S2S_TOKEN`); values are read at
construction time. A literal-secret grep over `config/` is clean. Every fixture and golden
dataset is obviously fictional.

### What is explicitly out of scope / a residual risk?

- The security-header baseline is incomplete on both surfaces (C6, above).
- There is no unattended demo self-test or executable portability script yet (checks F2 /
  F3), so a broken demo step would not fail CI today.
- This is a reference build: run your own pen-test, threat model, and model-risk review
  before any live deployment (stated throughout the docs).
