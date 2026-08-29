import type { Metadata } from "next";
import "./globals.css";

// REQUIRED by the nonce CSP, not a performance preference. `proxy.ts` mints a per-request
// nonce, and Next can only stamp it onto the script tags of a DYNAMICALLY rendered route.
// Statically prerendered HTML was built before the nonce existed, so nothing carries it, and
// because `'strict-dynamic'` disables the `'self'` fallback, that combination blocks strictly
// MORE than a policy with no nonce at all. `assertHydratableCsp` in next.config.mjs refuses to
// build if this line is removed; `ui/scripts/assert-hydratable.mjs` proves it against the served
// bytes, because the response header is byte-identical in the working and the broken case.
export const dynamic = "force-dynamic";

export const metadata: Metadata = {
  title: "Architecture & Requirements Validator",
  description:
    "Policy-as-code intake gate over the 12 General Principles for an APAC bank's agentic-AI platform.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // EMBED mode: the host page owns the chrome. Drop the standalone full-viewport wrapper
  // so the validator sits flush inside the parent's layout (the page's own TopBar is
  // gated on the same NEXT_PUBLIC_EMBED flag).
  const embed = process.env.NEXT_PUBLIC_EMBED === "1";
  return (
    <html lang="en">
      {embed ? (
        <body>{children}</body>
      ) : (
        <body className="min-h-screen">{children}</body>
      )}
    </html>
  );
}
