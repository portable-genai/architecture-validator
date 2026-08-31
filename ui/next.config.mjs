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
  // `next dev` writes AGENTS.md and CLAUDE.md into this directory unless this is false; the
  // writer is node_modules/next/dist/server/lib/generate-agent-files.js. This repo's working
  // agreement is the AGENTS.md at its root and there is no tool-specific alias of it, so a
  // second one here is a second agreement to keep in step and CLAUDE.md is precisely the alias
  // the convention forbids. The generated prose also carries an em-dash, which the catalog's
  // house style forbids in shipped markdown. tests/unit/test_ui_agent_documents.py fails the
  // gate if this line goes away or if either file turns up on disk anyway.
  agentRules: false,
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
