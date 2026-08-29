// The console's Content-Security-Policy, in ONE module so it is built once and read everywhere.
//
// Emitting it inline in `next.config.mjs` through the static `headers()` table allows exactly
// one directive: `frame-ancestors`. No `default-src`, no `script-src`, no
// `object-src`, no `base-uri`. The clickjacking control was real; everything else the header is
// for was simply absent, and every check in this repo was happy because a header that says
// something is indistinguishable from a header that says enough.
//
// Adding `script-src` is not free, and this is the part that bites. Next serves its hydration
// bootstrap as an INLINE `<script>` carrying the Flight payload, so a bare `script-src 'self'`
// blocks it: the server HTML renders, `__next_f` never fills, React never attaches, and the
// console is dead markup that looks perfect in a screenshot. The bootstrap needs a PER-REQUEST
// nonce, a static `headers()` table cannot express a per-request value, and so the policy moved
// here, the nonce is minted in `proxy.ts`, and `next.config.mjs` no longer emits a
// `Content-Security-Policy` at all. Two layers both setting it would give the browser two
// policies to intersect, with the stricter winning per directive, which quietly reinstates the
// defect this module exists to remove.

/**
 * Origin of the API base, when the console is deployed cross-origin from its service.
 *
 * A rooted path is the SAME-ORIGIN deployment, which is what a host portal mounting this console
 * under its own route sets. There is no second origin to name there, and `'self'` already permits
 * it, so "" is the correct answer rather than an error: refusing it made the console answer 500
 * behind the portal, which is a working configuration reported as a broken one.
 *
 * A protocol-relative value is still refused. It names a DIFFERENT host while looking rooted, so
 * treating it as same-origin would drop a genuinely cross-origin API out of `connect-src`, which
 * is the silent-drop this function exists to prevent.
 *
 * @param {Record<string, string | undefined>} env
 * @returns {string} an origin to add to `connect-src`, or "" when same-origin
 */
function apiOrigin(env) {
  const raw = (env.NEXT_PUBLIC_API_BASE || "").trim();
  if (!raw) return "";
  if (raw.startsWith("//")) {
    throw new Error(`NEXT_PUBLIC_API_BASE must name its scheme, got: ${raw}`);
  }
  if (raw.startsWith("/")) return "";
  try {
    return new URL(raw).origin;
  } catch {
    throw new Error(
      `NEXT_PUBLIC_API_BASE must be an absolute URL or a rooted same-origin path, got: ${raw}`,
    );
  }
}

/** Raised when an embedding variable names a wildcard instead of the origins it should allow. */
export class WildcardOriginError extends Error {}

/**
 * Exact tokens that must never be accepted as a framing ancestor.
 *
 * `'*'` is what a quoted Terraform variable or a YAML string renders. `*.*` is a host pattern
 * matching every name with a dot in it. `null` is the one that reads as harmless and is not: it
 * is not a wildcard by spelling and behaves as one, because a SANDBOXED iframe presents the
 * origin `null`, so a policy naming it hands framing rights to any page that can open one.
 */
const WILDCARD_TOKENS = new Set(["*", "'*'", "null", "*.*"]);

/**
 * True when an entry may not be a framing ancestor.
 *
 * Exact matching alone is not enough. `https://*.client.example` is in no token set, and CSP
 * honours a host-source wildcard: every subdomain may frame the console, including one an
 * attacker obtains by takeover or on a user-content subdomain. So ANY entry containing an
 * asterisk is refused, which turns away nothing a deployment could correctly hold, since a real
 * origin never contains the character.
 *
 * @param {string} entry
 * @returns {boolean}
 */
function isWildcard(entry) {
  return WILDCARD_TOKENS.has(entry) || entry.includes("*");
}

/**
 * Refuse an allowlist that names a wildcard, before the value can reach a response header.
 *
 * `src/architecture_validator/api/app.py::_refuse_wildcard` does this for the API surface, and it was the only half that
 * did. There are two `frame-ancestors` emitters, and the one a browser consults before framing
 * this console is the header on the DOCUMENT, which Next serves under the policy this module
 * builds. This resolver passed its configured value straight through, so a deployment whose
 * variable rendered a wildcard refused to start the API and still served a document any origin
 * could frame. The half that was closed is not the half that governs.
 *
 * Tokens are split on commas as well as whitespace. CSP source lists are space separated, so a
 * comma form never names a valid origin anyway; splitting on it here means
 * `*,https://portal.example` is seen as the wildcard it contains rather than as one opaque token
 * that merely fails to equal `*`.
 *
 * @param {string} raw the configured value, before it is normalised
 * @param {string} envName the variable it came from, for the message
 * @throws {WildcardOriginError}
 */
function refuseWildcards(raw, envName) {
  for (const piece of String(raw).split(/[\s,]+/)) {
    const entry = piece.trim();
    if (entry && isWildcard(entry)) {
      throw new WildcardOriginError(
        `${envName} contains ${JSON.stringify(entry)}, which lets ANY origin frame this ` +
          "console: a wildcard frame-ancestors is the clickjacking control switched off, not " +
          `configured. Name the exact parent origins that may frame it, or unset ${envName} to ` +
          "keep the restrictive default.",
      );
    }
  }
}

/**
 * Who may frame this console, read in THREE states to match the service exactly.
 *
 * This deliberately mirrors `_frame_ancestors` in `src/architecture_validator/api/app.py`, which reads
 * `ARCH_VALIDATOR_FRAME_ANCESTORS` the same way, because the two halves of one embedding posture
 * must not disagree. Unset keeps the shipped `'self'`. Set to something naming no origin means an
 * operator deliberately emptied the allowlist, which spells "nobody may frame this": that is
 * `'none'`, NOT an empty directive. `frame-ancestors ` with nothing after it is a CSP parse error
 * that browsers discard, so the two-state `env.X || "'self'"` form would silently REMOVE the
 * clickjacking restriction on exactly the deployment that meant to tighten it.
 *
 * @param {Record<string, string | undefined>} env
 * @returns {string}
 */
export function frameAncestors(env) {
  const raw = env.NEXT_PUBLIC_FRAME_ANCESTORS;
  if (raw === undefined || raw === null) return "'self'";
  refuseWildcards(raw, "NEXT_PUBLIC_FRAME_ANCESTORS");
  return raw.split(/\s+/).filter(Boolean).join(" ") || "'none'";
}

/**
 * The legacy `X-Frame-Options` spelling of a framing policy, or "" when it has none.
 *
 * Only the two values the pre-CSP header can actually express. A NAMED parent-origin allowlist
 * has no X-Frame-Options spelling, so none is sent rather than a `SAMEORIGIN` that would
 * contradict the CSP in an older agent. Mirrors the service's `_LEGACY_FRAME_OPTIONS`.
 *
 * @param {string} ancestors
 * @returns {string}
 */
export function frameOptions(ancestors) {
  if (ancestors === "'self'") return "SAMEORIGIN";
  if (ancestors === "'none'") return "DENY";
  return "";
}

/**
 * The full default-deny policy.
 *
 * `style-src` carries `'unsafe-inline'` because the Next runtime injects critical CSS and there
 * is no nonce path for it. `script-src` does NOT: it takes the per-request nonce plus
 * `'strict-dynamic'`, so the nonced bootstrap may load its own chunks and nothing else may run.
 * Passing no nonce yields the strict `'self'` form, which is correct for any response that is not
 * a Next-rendered document and wrong for one that is.
 *
 * @param {Record<string, string | undefined>} env
 * @param {string} [nonce]
 * @returns {string}
 */
export function contentSecurityPolicy(env, nonce) {
  // Dev only, and never emitted by a production build. `next dev` compiles with `eval` and its
  // HMR client opens a websocket back to the dev server, so a policy refusing both serves a page
  // that renders and never hydrates: React never attaches and every control is dead markup. The
  // branch is keyed off the toolchain's own NODE_ENV, compared against the exact literal
  // "production", so `next build` and `next start` cannot take it, and unset or emptied lands on
  // the dev branch where nothing is deployed. `scripts/assert-hydratable.mjs` runs against the
  // BUILT artefact, so a relaxation leaking into a deployment fails a gate, not a review.
  const isDev = env.NODE_ENV !== "production";
  const connectSrc = ["'self'", apiOrigin(env), isDev ? "ws: wss:" : ""]
    .filter(Boolean)
    .join(" ");
  const scriptSrc = [
    "script-src 'self'",
    nonce ? `'nonce-${nonce}' 'strict-dynamic'` : "",
    isDev ? "'unsafe-eval'" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return [
    "default-src 'self'",
    "base-uri 'self'",
    "form-action 'self'",
    "object-src 'none'",
    scriptSrc,
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data:",
    "font-src 'self' data:",
    `connect-src ${connectSrc}`,
    `frame-ancestors ${frameAncestors(env)}`,
  ].join("; ");
}

/** A fresh per-request nonce. Base64 of 16 random bytes from the Web Crypto global. */
export function generateNonce() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}

/** Raised when the nonce policy and the rendering mode disagree, which serves un-hydratable HTML. */
export class UnhydratableCspError extends Error {}

/**
 * Refuse a build whose CSP mints a nonce the rendered HTML can never carry.
 *
 * Next can only stamp a per-request nonce onto the scripts of a DYNAMICALLY rendered route. A
 * statically prerendered page was built before the nonce existed, so it emits bare script tags
 * while the header advertises a nonce, and because `'strict-dynamic'` switches off the `'self'`
 * fallback, that combination blocks strictly MORE than the unfixed policy did. The half-configured
 * state is therefore WORSE than doing nothing, and it is invisible to every check that does not
 * execute the page: the header is byte-identical either way. So it is refused at build time.
 *
 * No I/O happens here: it takes the source as a string, which keeps the module importable from
 * the proxy runtime.
 *
 * @param {string} layoutSource contents of `app/layout.tsx`
 * @throws {UnhydratableCspError}
 */
export function assertHydratableCsp(layoutSource) {
  if (!/export\s+const\s+dynamic\s*=\s*["']force-dynamic["']/.test(layoutSource)) {
    throw new UnhydratableCspError(
      'app/layout.tsx must set `export const dynamic = "force-dynamic"`. The CSP mints a ' +
        "per-request nonce, and Next can only stamp it onto script tags for a dynamically " +
        "rendered route. Statically prerendered HTML was built before the nonce existed, so " +
        "every script is blocked and the page never hydrates.",
    );
  }
}
