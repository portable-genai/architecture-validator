# Rsk3 Architecture Validator: demo console (UI)

A small React / Next.js console for the Rsk3 Architecture & Requirements Validator. It submits
a `ProjectSubmission` to the FastAPI backend's `POST /validate` and renders the cited
`ValidationReport`: the overall verdict, the per-principle findings (PASS / FAIL /
NEEDS_INFO / NOT_APPLICABLE), and the auto-injected non-functional requirements.

Source only, this is not built or installed as part of the Python gate. It has its own gate:
`make ui-check` (see below).

## Run

```bash
cp .env.local.example .env.local   # point NEXT_PUBLIC_API_BASE at the backend (:8088)
npm install
npm run dev                        # http://localhost:3000
```

The backend must be running (`make run-api`, or `architecture-validator serve`). The UI never
bypasses the gate: it only renders what `/validate` returns.

## Layout

- `app/page.tsx`: the submission form + report view.
- `app/layout.tsx`: the shell. Sets `export const dynamic = "force-dynamic"`, which the nonce CSP
  REQUIRES; see below.
- `lib/types.ts`: TypeScript mirrors of the Rsk3 domain dataclasses (`to_jsonable` shapes).
- `lib/api.ts`: typed fetch client for `/validate`, `/principles`, `/healthz`.
- `lib/csp.mjs`: the ONE Content-Security-Policy module. Builds the policy, resolves
  `frame-ancestors` in the same three states as the backend, mints nonces, and refuses an
  un-hydratable configuration at build time.
- `proxy.ts`: Next 16's middleware. The only place the CSP and `X-Frame-Options` are attached to a
  response, and the only place a per-request nonce can be minted.
- `next.config.mjs`: static headers only (`nosniff`, `Referrer-Policy`) plus the build-time
  refusal. It deliberately emits NO CSP: two layers emitting one get intersected by the browser.
- `scripts/assert-hydratable.mjs`: the hydration check (below).
- `tests/csp.test.mjs`: unit cover for what a policy STRING can decide.
- `components/*`: the verdict banner, findings table, injected-requirements list, citations.

## Gate

```bash
make ui-install     # npm ci from the committed lockfile
make ui-check       # tsc --noEmit; node --test; next build; assert-hydratable
```

`assert-hydratable` runs LAST and against the artefact the build just produced. It starts the
built production server, fetches the served document, and asserts that every required CSP
directive is present and non-empty, that `script-src` carries a nonce, and that EVERY `<script>`
tag in the HTML carries that same nonce.

That last assertion is the reason the script exists. The console's CSP mints a per-request nonce,
and Next can only stamp a nonce onto the scripts of a dynamically rendered route. If the route
were statically prerendered, the HTML would carry bare script tags while the header advertised a
nonce, `'strict-dynamic'` would disable the `'self'` fallback, and the browser would block
strictly MORE than the old no-nonce policy did: React would never attach and no control on the
page would work. The response header is byte-identical in the working and the broken case, so no
header assertion, type-check, build or screenshot can tell them apart. Only the served markup
knows.
