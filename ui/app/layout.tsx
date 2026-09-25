import type { Metadata } from "next";
import { ModelPills } from "./ModelPills";
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
  //
  // The model pills render in BOTH modes, mounted here rather than in a page because "at the
  // top of every page" is a property of the console. Embedded is the mode that needs them
  // most: a panel inside somebody else's portal is where a viewer has least context about
  // which model answered. Fixed at the top right, so nothing a page renders can push them off
  // screen; the page starts its own content below them.
  const embed = process.env.NEXT_PUBLIC_EMBED === "1";
  return (
    <html lang="en">
      <body className={embed ? undefined : "min-h-screen"}>
        <ModelPills />
        {children}
      </body>
    </html>
  );
}
