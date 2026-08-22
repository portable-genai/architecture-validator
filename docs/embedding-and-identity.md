# Embedding and identity: client integration guide (Rsk3 architecture-validator)

This guide shows how a client runs the C3 Architecture and Requirements Validator and, when
desired, embeds its UI inside an existing web application with secure single sign-on (SSO), so
users never see a second login. Everything below is backed by code on the current tree: the
FastAPI backend (`src/architecture_validator/api/`), the `IdentityPort` and its per-profile adapters
(`src/architecture_validator/ports/identity.py`, `adapters/{local,gcp,onprem}/identity.py`), the
embedding-surface controls in `api/app.py` (CORS plus CSP `frame-ancestors`), the UI build knobs
in `ui/next.config.mjs` / `ui/app/layout.tsx`, and the profile bindings in
`config/settings.yaml`.

For the deployment shapes here, no application code changes are required to integrate: the work
is operational (choose a profile, set environment variables, and add a proxy route plus an iframe
tag).

---

## 1. The two pieces

The validator ships as two cooperating pieces:

- **Backend**: a FastAPI service (default port `8088`) exposing the intake gate (`POST /validate`),
  the 12 General Principles (`GET /principles`), health (`GET /healthz`), the seeded persona list
  (`GET /v1/personas`), and the A2A agent card (`/.well-known/agent-card.json`).
- **UI**: a Next.js console (default port `3000`) that calls the backend and renders the cited
  ValidationReport. `NEXT_PUBLIC_EMBED=1` drops the UI's own chrome (`ui/app/layout.tsx` plus the
  page TopBar); the UI base path and API base are build-time env vars (`ui/next.config.mjs`,
  `ui/lib/api.ts`).

---

## 2. The three deployment shapes

Pick the cheapest shape the host can actually satisfy.

| # | Shape | Use when the host... | Host work | Isolation | Identity |
|---|-------|----------------------|-----------|-----------|----------|
| 1 | **Embedded, same-origin reverse proxy** | controls its own edge (nginx or Next.js rewrites) and can federate its IdP into Cloud IAP. | Two proxy routes plus one `<iframe src="/validator/">`. | iframe gives hard CSS/JS isolation; same-origin (first-party, no CORS, no third-party cookies). | IAP-verified `x-goog-iap-jwt-assertion` (`adapters/gcp/iap_identity.py`); the proxy forwards the header. |
| 2 | **Standalone behind Cloud IAP** | has no host app, or wants a separate console at its own URL. | DNS plus HTTPS LB plus IAP. | Top-level app (not framed); `frame-ancestors 'self'`. | IAP-verified assertion; IAP plus Workforce Identity Federation gives SSO. |
| 3 | **Local dev, no auth** | is evaluating offline, with no IdP. | None. | N/A (offline). | Seeded personas via `X-Dev-Persona` (`adapters/local/identity.py`). |

---

## 3. Shape 3: run locally, no auth

Local mode (`ARCH_VALIDATOR_PROFILE=local`) runs the entire pipeline offline: SQLite FTS5
retrieval, a deterministic LLM, and **no IdP, AD, or LDAP**. Identity is resolved from a small set
of seeded dev personas (`adapters/local/identity.py`) selected by an `X-Dev-Persona` request
header, with the first persona as the default.

```bash
# Backend (repo root)
export ARCH_VALIDATOR_PROFILE=local
make run-api                      # uvicorn on http://localhost:8088

# UI (in ./ui)
cp .env.local.example .env.local  # NEXT_PUBLIC_API_BASE defaults to http://localhost:8088
npm install && npm run dev        # http://localhost:3000
```

The UI shows a "Demo identity" picker (only when `GET /healthz` reports `profile == "local"`); it
loads `GET /v1/personas` and default-selects the first. Selecting a persona sends the
`X-Dev-Persona` header on subsequent calls, so you can exercise per-user and per-tenant
authorization (including a cross-tenant persona) without standing up any identity provider.

The seeded personas:

| id | subject | tenant | entitlements |
|----|---------|--------|--------------|
| `analyst` (default) | `demo.analyst@bank.example` | `demo-bank` | `group:arch-reviewer`, `group:risk` |
| `approver` | `demo.approver@bank.example` | `demo-bank` | plus `group:arch-approver` |
| `auditor` | `demo.auditor@bank.example` | `demo-bank` | `group:audit` |
| `other-tenant` | `user@other-tenant.example` | `other-bank` | `group:arch-reviewer` |

An unknown persona id is a 401 (the adapter raises `IdentityError`), which proves the server
rejects an identity it cannot resolve rather than falling back to an anonymous default.

---

## 4. Shape 2: standalone behind Cloud IAP

When there is no host application, deploy the validator on its own URL:

1. Deploy backend and UI behind the same HTTPS load balancer and Cloud IAP.
2. Set `ARCH_VALIDATOR_PROFILE=gcp` and `ARCH_VALIDATOR_IAP_AUDIENCE` so the backend verifies the
   IAP assertion.
3. Point the UI at the backend with `NEXT_PUBLIC_API_BASE`. If the UI and backend are on
   **different** origins, also set `ARCH_VALIDATOR_CORS_ORIGINS` to the UI origin (an explicit
   allowlist, never `"*"`):

   ```bash
   export ARCH_VALIDATOR_CORS_ORIGINS="https://validator.client.com"
   export NEXT_PUBLIC_API_BASE="https://api.validator.client.com"
   ```

4. Share the URL with authorized users or groups. IAP plus Workforce Identity Federation gives SSO
   from the corporate IdP.

Leave `ARCH_VALIDATOR_FRAME_ANCESTORS` at its `'self'` default: nothing should iframe a standalone
deployment.

### Secure IAP note

In secure mode authentication is configured **on the GCP service** (IAP in front of the HTTPS load
balancer), not hand-rolled in the app. IAP authenticates the user and injects a signed JWT in
`x-goog-iap-jwt-assertion`. The `IapIdentityAdapter` verifies that assertion (signature, audience,
issuer, expiry) using lazy Google imports, derives the `Principal` from the `email`/`sub` claims
(tenant from `hd`), and never logs the assertion. The audience must be the exact structured
protected-resource path and is required: with `ARCH_VALIDATOR_IAP_AUDIENCE` unset the adapter
refuses to verify and returns a 401. Federating the client's own IdP into IAP via Workforce
Identity Federation is what gives the seamless SSO.

---

## 5. Shape 1: embed via same-origin reverse proxy

This is the smallest change for a host that controls its edge: serve the validator **under your own
origin** at a sub-path (for example `/validator/`) via a reverse proxy, then drop an iframe pointing
at that same-origin path. Because the iframe is first-party, there are no third-party-cookie issues
and no CORS to configure. The client owns exactly two things: a proxy route and an iframe tag.

### 5a. Reverse-proxy `/validator/*` to the validator service

**nginx**:

```nginx
# On https://portal.client.com
location /validator/ {
    proxy_pass         http://validator-ui.internal:3000/;    # the Next.js UI
    proxy_set_header   Host              $host;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
}

# The UI's API calls (NEXT_PUBLIC_API_BASE=/validator/api) also resolve same-origin:
location /validator/api/ {
    proxy_pass         http://validator-backend.internal:8088/;
    proxy_set_header   Host              $host;
    proxy_set_header   X-Forwarded-Proto $scheme;
    # IAP runs in front of this origin, so x-goog-iap-jwt-assertion is present on the
    # inbound request and forwarded through to the backend.
}
```

**Next.js host app** (if the parent is itself Next.js, use `rewrites()` in its own config):

```js
// next.config.mjs of the PARENT app
const nextConfig = {
  async rewrites() {
    return [
      { source: "/validator/api/:path*", destination: "http://validator-backend.internal:8088/:path*" },
      { source: "/validator/:path*",     destination: "http://validator-ui.internal:3000/:path*" },
    ];
  },
};
export default nextConfig;
```

### 5b. Mount the validator UI under the sub-path and hide its chrome

```bash
# Environment for the validator UI (build-time)
NEXT_PUBLIC_BASE_PATH=/validator      # mount the UI and its assets under the sub-path
NEXT_PUBLIC_API_BASE=/validator/api   # same-origin API calls (no CORS needed)
NEXT_PUBLIC_EMBED=1                   # hide the UI's own header/nav chrome when embedded
```

### 5c. The iframe tag (host page)

```html
<!-- On https://portal.client.com, inside your existing page, in a sized container -->
<iframe
  src="/validator/"
  title="Architecture and Requirements Validator"
  style="width:100%; height:100%; border:0;"
  loading="lazy">
</iframe>
```

Height caveat: `height:100%` only renders correctly inside a host container that already has a
fixed pixel height, because there is no child-to-parent resize message today.

### 5d. Allow the parent origin to frame the UI

Framing is controlled in **two** places, and both must permit the parent origin, because
`frame-ancestors` is only honored on the HTTP response of the document the browser actually frames:

- **Backend** (`api/app.py` middleware) emits `Content-Security-Policy: frame-ancestors
  <ARCH_VALIDATOR_FRAME_ANCESTORS>` on API responses, and adds the legacy `X-Frame-Options`
  backstop for the two values that header can express: `'self'` gives `SAMEORIGIN` and `'none'`
  gives `DENY`. A multi-origin allowlist is left to CSP alone, which is the only header that can
  express it.
  The variable resolves in **three** states, because an emptied allowlist is a configuration and
  not an omission: unset keeps `'self'`; **set and empty resolves to `'none'`**, which is the
  operator's expressed intent (nobody may frame this) and the most restrictive value the
  directive has; set names exactly those parent origins. Before this, an emptied variable emitted
  `frame-ancestors` with no value, which browsers discard as a parse error, and skipped the
  `X-Frame-Options` branch as well, so the clickjacking control disappeared from both headers.
- **UI** (`ui/proxy.ts`, from the policy in `ui/lib/csp.mjs`) emits the same `frame-ancestors`
  value (from `NEXT_PUBLIC_FRAME_ANCESTORS`, read with the identical three-state rule), plus
  `X-Frame-Options` only for the two values that header can express (`'self'` to `SAMEORIGIN`,
  `'none'` to `DENY`; a named parent-origin allowlist gets none, because sending `SAMEORIGIN`
  beside it would contradict the CSP in an older agent). The document the browser frames is served
  by Next.js, so this anti-clickjacking policy must be emitted at the UI layer too, not only on
  the API.

### The console's full Content-Security-Policy

A console that emits `frame-ancestors` and nothing else, with no `default-src`, no `script-src`,
no `object-src` and no `base-uri`, is the defect. This one serves a complete default-deny policy,
built in exactly one place and emitted from exactly one place.

- **One policy module.** `ui/lib/csp.mjs` builds the whole policy string and is the only thing that
  knows what it contains. `ui/next.config.mjs` emits no `Content-Security-Policy` at all; it
  keeps only the two headers a static table can express correctly (`X-Content-Type-Options:
  nosniff`, `Referrer-Policy: no-referrer`). Two layers both emitting a CSP is not additive
  hardening: the browser intersects them and the stricter value wins per directive, which is how a
  fixed policy silently reverts.
- **Two enforcement points, both required.** `ui/proxy.ts` (Next 16's name for `middleware.ts`)
  mints a fresh nonce per request and sets the policy on the REQUEST headers, which is where Next
  reads the nonce it stamps onto every script tag, AND on the RESPONSE headers, which is what the
  browser enforces. Setting only the request header proves nothing to a browser; setting only the
  response header blocks the very scripts the nonce exists to allow.
- **`script-src 'self' 'nonce-...' 'strict-dynamic'`, and the route must be dynamic.** Next serves
  its hydration bootstrap as an INLINE script carrying the Flight payload, so a bare `script-src
  'self'` blocks it: the HTML renders, `__next_f` never fills, React never attaches, and the
  console is dead markup that looks correct in a screenshot. The nonce fixes that only on a
  DYNAMICALLY rendered route, because statically prerendered HTML was built before the nonce
  existed. Getting that half-right is worse than doing nothing, since `'strict-dynamic'` switches
  off the `'self'` fallback that had at least been loading the chunk scripts. So `ui/app/layout.tsx`
  sets `export const dynamic = "force-dynamic"`, `assertHydratableCsp` in `ui/next.config.mjs`
  refuses to build or boot without it, and `ui/scripts/assert-hydratable.mjs` starts the BUILT
  server and asserts every served script tag carries the served nonce. That last check is the only
  one that can tell the two cases apart: the response header is byte-identical in both.
- **`NEXT_PUBLIC_API_BASE` widens `connect-src` to that URL's ORIGIN**, never the full URL, so a
  cross-origin deployment can call its backend without opening the directive to everything.

```bash
# backend
export ARCH_VALIDATOR_FRAME_ANCESTORS="https://portal.client.com"
# UI (build-time)
export NEXT_PUBLIC_FRAME_ANCESTORS="https://portal.client.com"
# multiple parents are space-separated per the CSP grammar:
# "https://portal.client.com https://admin.client.com"
```

In shape 1 the framed document is served same-origin through the proxy, so aligning the two values
keeps the policy consistent end to end.

---

## 6. The identity contract

One rule underpins every shape: **the server never trusts a client-asserted identity.**

- The `POST /validate` request body carries **no** `actor` field. `api/security.py`
  (`get_principal`) builds a `RequestContext` from all lower-cased request headers and asks the
  active profile's `IdentityPort` to resolve a verified `Principal`. A failure to resolve is a 401.
- The verified `Principal.actor` (its `subject`) is what the `ValidationService` records as the
  audit actor. The `Principal.principals` (entitlement groups) and `tenant` are available for
  governed authorization. Today's KB retrieval takes no ACL predicate, so no per-user ACL is merged
  into retrieval; when a governed retrieval seam is added, `Principal.principals` is the value to
  feed it.
- Which adapter resolves the `Principal` is a one-line profile switch (`config/settings.yaml`
  under `adapters.identity`): `local` -> seeded personas, `gcp`/`platform` -> IAP assertion,
  `onprem` -> the fail-fast placeholder for the client's own IdP.

This is the seam that defeats actor spoofing and the confused-deputy risk: a caller cannot forge an
identity by putting a field in the JSON body, because the server ignores the body for identity and
derives it from a verified transport signal.

---

## 7. Configuration reference

| Variable | Side | Purpose |
|----------|------|---------|
| `ARCH_VALIDATOR_PROFILE` | backend | `local` \| `gcp` \| `platform` \| `onprem`. Selects the identity adapter (and the whole adapter set). |
| `ARCH_VALIDATOR_IAP_AUDIENCE` | backend | The IAP audience string (the exact structured resource path) the backend verifies against. Required in `gcp`/`platform`. |
| `ARCH_VALIDATOR_CORS_ORIGINS` | backend | Explicit origin allowlist for the cross-origin / standalone case. Comma-separated. Never `"*"`. Three states: unset keeps the dev-origin fallback under a deliberate `local` profile, set and empty trusts no origin at all, set uses the origins named. |
| `ARCH_VALIDATOR_FRAME_ANCESTORS` | backend | CSP `frame-ancestors` allowlist: parent origins permitted to iframe the UI. Three states: unset defaults to `'self'`, set and empty resolves to `'none'` (nobody may frame it), set uses the origins named. |
| `NEXT_PUBLIC_API_BASE` | UI | Backend base URL the UI calls. Build-time. |
| `NEXT_PUBLIC_BASE_PATH` | UI | Sub-path the UI (and its assets) is mounted under. Blank keeps the standalone build. Build-time. |
| `NEXT_PUBLIC_EMBED` | UI | Set to `1` to hide the UI's own chrome. Build-time. |
| `NEXT_PUBLIC_FRAME_ANCESTORS` | UI | CSP `frame-ancestors` on the Next-served UI document, resolved in `ui/lib/csp.mjs` and emitted by `ui/proxy.ts`. Same three states as the backend variable: unset defaults to `'self'`, set and empty resolves to `'none'`, set uses the origins named. Read per request by the proxy, so it can be changed without a rebuild. |
| `X-Dev-Persona` | request header | **Local profile only.** Selects a seeded dev persona; ignored in secure profiles. |

---

## 8. Checklists

### Integration checklist

**Shape 1 (same-origin reverse proxy):**

- [ ] Reverse-proxy route mapping `/validator/*` to the validator UI service (5a).
- [ ] Reverse-proxy route mapping `/validator/api/*` to the validator backend service.
- [ ] UI built with `NEXT_PUBLIC_BASE_PATH`, `NEXT_PUBLIC_API_BASE`, `NEXT_PUBLIC_EMBED=1` (5b).
- [ ] `<iframe src="/validator/">` on the host page in a sized container (5c).
- [ ] Both `ARCH_VALIDATOR_FRAME_ANCESTORS` and `NEXT_PUBLIC_FRAME_ANCESTORS` list the parent (5d).
- [ ] IdP federated into IAP (Workforce Identity Federation) so users carry one session through.

**Shape 2 (standalone):**

- [ ] DNS plus HTTPS LB plus IAP fronting the deployment.
- [ ] `ARCH_VALIDATOR_PROFILE=gcp` and `ARCH_VALIDATOR_IAP_AUDIENCE` set.
- [ ] `ARCH_VALIDATOR_CORS_ORIGINS` set if UI and backend are on different origins.
- [ ] URL shared with authorized users/groups.

### Security checklist

- [ ] **HTTPS everywhere** (LB terminates TLS; IAP requires it).
- [ ] **IAP audience configured**: `ARCH_VALIDATOR_IAP_AUDIENCE` set in any IAP profile (the backend
      refuses to verify without it).
- [ ] **Framing locked down**: `ARCH_VALIDATOR_FRAME_ANCESTORS` and `NEXT_PUBLIC_FRAME_ANCESTORS` set
      to the exact parent origin(s); `'self'` for standalone; never a wildcard.
- [ ] **Origins locked down**: same-origin proxy (no CORS) for shape 1; otherwise
      `ARCH_VALIDATOR_CORS_ORIGINS` is an explicit allowlist, never `"*"`.
- [ ] **No client-asserted identity trusted**: production uses `gcp`/`platform` (or an implemented
      `onprem`), never `local`. The request body carries no `actor`.

---

## 9. Further layers (out of scope here, documented)

This slice deliberately stops at server-verified identity plus the same-origin embed and standalone
IAP shapes. The reference implementation in `cdd-sow-research`
(`docs/embedding-and-identity.md`) documents the next hardening layers, which apply equally to this
repo when a host needs them:

- **Cross-origin token handoff** (host cannot run a proxy or will not federate into IAP): a versioned
  front-end loader plus a web component, a hardened `postMessage` contract, and a new
  JWKS-verifying `IdentityPort` adapter that consumes a host-minted `Authorization: Bearer` token in
  memory (never a third-party cookie).
- **Launch in a new tab** (OIDC Authorization Code plus PKCE redirect login with a self-issued
  session cookie) as the simplest portable option and as a pop-out fallback from any framed mode.
- **Per-tenant, request-time policy** for `frame-ancestors`, CORS, and issuer/audience, replacing the
  single process-wide values.
- **Per-hop token exchange (OBO) plus Workload Identity and mTLS** to the sibling Hrz/Rsk services,
  DPoP or step-up (acr/amr) for high-value actions, fail-closed tenant-partitioned retrieval, and
  Trusted Types on the bundles.

Until those land, use shape 1 or 2 for a cooperative, GCP-aligned host, and shape 3 for offline
evaluation.
