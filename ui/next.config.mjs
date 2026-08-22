import { readFileSync } from "node:fs";

import { assertHydratableCsp } from "./lib/csp.mjs";

// Evaluated by both `next build` and `next start`, so the half-configured CSP -- a per-request
// nonce on a statically prerendered route, which blocks strictly MORE than no nonce at all --
// cannot be built or booted. It is the only failure mode here that no cheaper check can see.
assertHydratableCsp(readFileSync(new URL("./app/layout.tsx", import.meta.url), "utf8"));

/** @type {import('next').NextConfig} */
const basePath = process.env.NEXT_PUBLIC_BASE_PATH || "";

const nextConfig = {
  reactStrictMode: true,
  ...(basePath ? { basePath, assetPrefix: basePath } : {}),
  async headers() {
    // ONLY headers that a static table can express correctly. The Content-Security-Policy and
    // X-Frame-Options are emitted from `proxy.ts` and NOWHERE else: the CSP carries a per-request
    // nonce, which this table cannot produce, and a policy emitted from two layers is intersected
    // by the browser with the stricter value winning per directive -- which is precisely how the
    // hydration defect would come back after being fixed.
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "no-referrer" },
        ],
      },
    ];
  },
};

export default nextConfig;
