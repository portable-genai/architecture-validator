// The one place the console's security headers are attached to a response.
//
// `proxy.ts` is Next 16's name for what was `middleware.ts`; it runs on every matched request,
// which is what makes a PER-REQUEST nonce possible at all. The static `headers()` table in
// `next.config.mjs` cannot express one, which is why the CSP does not live there.
//
// Both header sets below are required, and they do different jobs:
//
//   * the REQUEST header is where Next reads the nonce it stamps onto every `<script>` tag it
//     emits. Setting only this proves nothing to a browser.
//   * the RESPONSE header is what the browser actually enforces. Setting only this blocks the
//     very scripts the nonce was added to allow, because the emitted tags carry no nonce.
//
// The request header name must be exactly `Content-Security-Policy`; Next looks for that.

import { type NextRequest, NextResponse } from "next/server";

import {
  contentSecurityPolicy,
  frameAncestors,
  frameOptions,
  generateNonce,
} from "./lib/csp.mjs";

export function proxy(request: NextRequest) {
  const nonce = generateNonce();
  const csp = contentSecurityPolicy(process.env, nonce);

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set("Content-Security-Policy", csp);

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  response.headers.set("Content-Security-Policy", csp);

  const legacy = frameOptions(frameAncestors(process.env));
  if (legacy) response.headers.set("X-Frame-Options", legacy);

  return response;
}

export const config = { matcher: "/:path*" };
