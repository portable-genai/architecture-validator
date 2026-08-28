// Unit cover for what a STRING can decide about the console's CSP.
//
// These tests are NOT sufficient, and saying so is the point. Every assertion here passed in the
// broken state too, because the defect this policy exists to fix is not visible in the policy
// text: a nonce CSP served over a statically prerendered route produces a header byte-identical
// to the working case, while the document underneath carries bare script tags the browser then
// blocks. Only `scripts/assert-hydratable.mjs`, which starts the built server and reads the
// served bytes, can see that. What these tests DO cover is the class of mistake that lives in the
// string: a missing directive, an empty directive, a two-state read of a three-state variable.

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  UnhydratableCspError,
  WildcardOriginError,
  assertHydratableCsp,
  contentSecurityPolicy,
  frameAncestors,
  frameOptions,
  generateNonce,
} from "../lib/csp.mjs";

/** Parse a policy string into directive -> value, the way a browser would. */
function directives(csp) {
  return new Map(
    csp
      .split(";")
      .map((part) => part.trim())
      .filter(Boolean)
      .map((part) => {
        const [name, ...value] = part.split(/\s+/);
        return [name.toLowerCase(), value.join(" ")];
      }),
  );
}

test("the policy carries every directive a default-deny posture needs", () => {
  const found = directives(contentSecurityPolicy({}, "n0nce"));
  for (const name of [
    "default-src",
    "base-uri",
    "form-action",
    "object-src",
    "script-src",
    "style-src",
    "img-src",
    "font-src",
    "connect-src",
    "frame-ancestors",
  ]) {
    assert.ok(found.has(name), `missing directive: ${name}`);
  }
  assert.equal(found.get("object-src"), "'none'");
  assert.equal(found.get("base-uri"), "'self'");
});

test("no directive is EVER empty, in any state of the framing variable", () => {
  // An empty directive is a CSP parse error. Browsers discard it, so `frame-ancestors ` with
  // nothing after it removes the clickjacking restriction from the deployment that meant to
  // tighten it. This is the exact bug the service side already fixed.
  for (const env of [
    {},
    { NEXT_PUBLIC_FRAME_ANCESTORS: "" },
    { NEXT_PUBLIC_FRAME_ANCESTORS: "   " },
    { NEXT_PUBLIC_FRAME_ANCESTORS: "\n\t " },
  ]) {
    for (const [name, value] of directives(contentSecurityPolicy(env, "n0nce"))) {
      assert.notEqual(value, "", `directive ${name} is empty for env ${JSON.stringify(env)}`);
    }
  }
});

test("script-src takes the nonce and strict-dynamic only when a nonce is supplied", () => {
  assert.equal(
    directives(contentSecurityPolicy({}, "abc123")).get("script-src"),
    "'self' 'nonce-abc123' 'strict-dynamic'",
  );
  // No nonce means the response is not a Next-rendered document, and 'self' is right there.
  assert.equal(directives(contentSecurityPolicy({})).get("script-src"), "'self'");
});

test("frame-ancestors is three-state, matching the service's _frame_ancestors exactly", () => {
  assert.equal(frameAncestors({}), "'self'");
  assert.equal(frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "" }), "'none'");
  assert.equal(frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "   " }), "'none'");
  assert.equal(
    frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "https://portal.example" }),
    "https://portal.example",
  );
  assert.equal(
    frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: " https://a.example\n https://b.example " }),
    "https://a.example https://b.example",
  );
});

test("X-Frame-Options is sent only for the two policies it can express", () => {
  assert.equal(frameOptions("'self'"), "SAMEORIGIN");
  assert.equal(frameOptions("'none'"), "DENY");
  // A named allowlist has no X-Frame-Options spelling; sending SAMEORIGIN would contradict the
  // CSP in an older agent, so nothing is sent.
  assert.equal(frameOptions("https://portal.example"), "");
  assert.equal(frameOptions("https://a.example https://b.example"), "");
});

test("connect-src widens to the API ORIGIN, never the full URL", () => {
  const value = directives(
    contentSecurityPolicy({ NEXT_PUBLIC_API_BASE: "https://api.example:8443/v1/validate" }),
  ).get("connect-src");
  assert.equal(value, "'self' https://api.example:8443");
});

test("a rooted API base stays same-origin rather than being refused", () => {
  // A host portal mounting this console under its own route sets exactly this. Same-origin is
  // already covered by 'self', so it widens nothing, and refusing it answered 500 on a working
  // deployment. What must never happen is the value being dropped while it names a real origin,
  // which is the case below.
  assert.doesNotThrow(() => contentSecurityPolicy({ NEXT_PUBLIC_API_BASE: "/apps/x/api" }));
});

test("a protocol-relative API base is refused rather than read as same-origin", () => {
  assert.throws(
    () => contentSecurityPolicy({ NEXT_PUBLIC_API_BASE: "//api.example/v1" }),
    /must name its scheme/,
  );
});

test("an API base that is neither absolute nor rooted is refused", () => {
  assert.throws(
    () => contentSecurityPolicy({ NEXT_PUBLIC_API_BASE: "api.example/v1" }),
    /NEXT_PUBLIC_API_BASE/,
  );
});

test("nonces are unique and base64", () => {
  const seen = new Set();
  for (let i = 0; i < 50; i += 1) {
    const nonce = generateNonce();
    assert.match(nonce, /^[A-Za-z0-9+/]+=*$/);
    assert.ok(!seen.has(nonce), "generateNonce repeated a value");
    seen.add(nonce);
  }
});

test("assertHydratableCsp refuses a layout that is not force-dynamic", () => {
  assert.throws(
    () => assertHydratableCsp("export const metadata = {};\n"),
    UnhydratableCspError,
  );
  assert.doesNotThrow(() => assertHydratableCsp('export const dynamic = "force-dynamic";\n'));
  assert.doesNotThrow(() => assertHydratableCsp("export const dynamic = 'force-dynamic'\n"));
});

test("a wildcard frame-ancestors is refused in every spelling a config can render", () => {
  // The FastAPI half already refuses these. This is the OTHER emitter, and it is the one a
  // browser honours for the document, so closing only the service side left the console
  // framable by any origin while every check stayed green.
  for (const wildcard of ["*", "'*'", "null", "*.*"]) {
    assert.throws(
      () => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: wildcard }),
      WildcardOriginError,
      `${JSON.stringify(wildcard)} must be refused, not passed through to the header`,
    );
  }
  assert.throws(
    () => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "https://portal.client.example *" }),
    WildcardOriginError,
    "a wildcard standing beside named origins is still a wildcard",
  );
  assert.throws(
    () => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "*,https://portal.client.example" }),
    WildcardOriginError,
    "a comma is not CSP list syntax, so a comma-joined wildcard must still be seen",
  );
  // A HOST-SOURCE wildcard is the spelling an exact-token set misses, and CSP honours it: every
  // subdomain may frame the console, including one an attacker takes over or registers on a
  // user-content domain. A real origin never contains an asterisk, so refusing the character
  // outright turns away nothing a deployment could correctly hold.
  for (const hostSource of [
    "https://*.client.example",
    "*.client.example",
    "https://*",
    "https://portal.client.example https://*.evil.example",
  ]) {
    assert.throws(
      () => frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: hostSource }),
      WildcardOriginError,
      `${JSON.stringify(hostSource)} is a host-source wildcard and must be refused`,
    );
  }
});

test("the policy the proxy actually serves refuses a wildcard too", () => {
  // `contentSecurityPolicy` is what `proxy.ts` puts on the document response. Refusing inside
  // the resolver alone would be theatre if this path could still build a policy around it.
  for (const wildcard of ["*", "'*'", "null", "*.*", "https://*.client.example"]) {
    assert.throws(
      () => contentSecurityPolicy({ NEXT_PUBLIC_FRAME_ANCESTORS: wildcard }, "n0nce"),
      WildcardOriginError,
      `the served document policy must not carry frame-ancestors ${wildcard}`,
    );
  }
});

test("a legitimate named allowlist is unaffected by the wildcard refusal", () => {
  // A refusal that also refuses valid input is an outage, not a control.
  assert.equal(
    frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "https://portal.client.example" }),
    "https://portal.client.example",
  );
  assert.equal(
    frameAncestors({
      NEXT_PUBLIC_FRAME_ANCESTORS: "https://portal.client.example https://intranet.client.example",
    }),
    "https://portal.client.example https://intranet.client.example",
  );
  assert.equal(frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "'self'" }), "'self'");
  assert.equal(frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: "'none'" }), "'none'");
  assert.match(
    contentSecurityPolicy({ NEXT_PUBLIC_FRAME_ANCESTORS: "https://portal.client.example" }, "n"),
    /frame-ancestors https:\/\/portal\.client\.example/,
  );
});

test("the unset and emptied states are exactly what they were before wildcards were refused", () => {
  // Pinned so a later edit cannot drift them. THIS repo maps an emptied value to 'none' rather
  // than refusing it, mirroring its own FastAPI half; the wildcard case is an addition to that
  // behaviour, never a replacement for it, and 'none' is the one answer a wildcard is not.
  assert.equal(frameAncestors({}), "'self'");
  for (const blank of ["", "   ", "\t", "\n", " \t\n "]) {
    assert.equal(
      frameAncestors({ NEXT_PUBLIC_FRAME_ANCESTORS: blank }),
      "'none'",
      `blank value ${JSON.stringify(blank)} must still resolve to the lockdown value`,
    );
  }
  assert.equal(frameOptions("'none'"), "DENY");
});
