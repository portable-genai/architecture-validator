import { ConfiguredEmptyError, readEnvSetting } from "./env-setting.mjs";
/**
 * Typed fetch client for the C3 Architecture Validator FastAPI backend.
 *
 * Routes (SPEC §6):
 *   POST /validate    -> ValidationReport
 *   GET  /principles  -> { principles: Principle[] }
 *   GET  /healthz     -> { status, profile, region }
 */

import type { Principle, ProjectSubmission, ValidationReport } from "./types";

// The API base is resolved in THREE states, not two.
//
// Reading `process.env.NEXT_PUBLIC_API_BASE || "<loopback default>"` hands a
// variable an operator DELIBERATELY EMPTIED the loopback default. That is a widening: the
// console then talks to a local API instead of the configured one, and `connect-src` is built
// from the same value, so the emptied deployment is byte-identical to one that never configured
// the variable at all. Next inlines NEXT_PUBLIC_* AT BUILD TIME, so the wrong value is frozen
// into the bundle and cannot be corrected by fixing the environment at start-up.
//
// Unset keeps the documented loopback default, which is what a laptop wants. Set-and-empty
// refuses, because an emptied value names nothing and the default is the more permissive branch.
const DEFAULT_API_BASE = "http://localhost:8088";
const API_BASE_SETTING = readEnvSetting(process.env, "NEXT_PUBLIC_API_BASE");
if (API_BASE_SETTING.isConfiguredEmpty) {
  throw new ConfiguredEmptyError(
    "NEXT_PUBLIC_API_BASE is set to an empty value. An emptied variable names nothing, " +
      "so it cannot inherit the unset default (" + DEFAULT_API_BASE + "), which points this " +
      "console at a loopback API and widens connect-src to match. Unset it to take that " +
      "default deliberately, or give it the API origin this deployment should call.",
  );
}
export const API_BASE = (API_BASE_SETTING.hasValue ? API_BASE_SETTING.value : DEFAULT_API_BASE).replace(
  /\/+$/,
  "",
);

// Dev-only identity selection. In LOCAL mode the backend resolves identity from the
// X-Dev-Persona header; in secure profiles this is ignored (identity comes from an
// IAP assertion injected by the platform). The request body never carries an actor:
// the server-verified Principal supplies the audit actor.
let devPersona = "";

export function setDevPersona(id: string): void {
  devPersona = id;
}

export function getDevPersona(): string {
  return devPersona;
}

function personaHeaders(): Record<string, string> {
  return devPersona ? { "X-Dev-Persona": devPersona } : {};
}

export class ApiError extends Error {
  status: number;
  body: string;
  constructor(message: string, status: number, body: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

const JSON_HEADERS = { "Content-Type": "application/json" } as const;

async function parseJsonOrThrow(res: Response): Promise<unknown> {
  const text = await res.text();
  if (!res.ok) {
    let detail = text;
    try {
      const parsed = JSON.parse(text);
      detail = (parsed && (parsed.detail || parsed.message)) || text;
    } catch {
      /* keep raw text */
    }
    throw new ApiError(
      `${res.status} ${res.statusText}: ${detail || "request failed"}`,
      res.status,
      text,
    );
  }
  if (!text) return null;
  try {
    return JSON.parse(text);
  } catch {
    throw new ApiError("Malformed JSON in response", res.status, text);
  }
}

export async function validate(submission: ProjectSubmission): Promise<ValidationReport> {
  // No actor in the body: the server resolves the audit actor from the verified
  // Principal (X-Dev-Persona in local mode, an IAP assertion in secure mode).
  const res = await fetch(`${API_BASE}/validate`, {
    method: "POST",
    headers: { ...JSON_HEADERS, ...personaHeaders() },
    body: JSON.stringify({ submission }),
  });
  return (await parseJsonOrThrow(res)) as ValidationReport;
}

export async function principles(): Promise<Principle[]> {
  const res = await fetch(`${API_BASE}/principles`, { method: "GET" });
  const raw = (await parseJsonOrThrow(res)) as { principles?: Principle[] };
  return raw?.principles ?? [];
}

export interface Persona {
  id: string;
  subject: string;
  tenant: string;
  principals: string;
}

export async function listPersonas(): Promise<Persona[]> {
  const res = await fetch(`${API_BASE}/v1/personas`, {
    method: "GET",
    headers: personaHeaders(),
  });
  return ((await parseJsonOrThrow(res)) as Persona[]) ?? [];
}

export interface HealthStatus {
  ok: boolean;
  profile?: string;
  region?: string;
}

export async function healthz(): Promise<HealthStatus> {
  try {
    const res = await fetch(`${API_BASE}/healthz`, { method: "GET" });
    if (!res.ok) return { ok: false };
    const raw = (await res.json().catch(() => ({}))) as Record<string, unknown>;
    return {
      ok: raw.status === "ok",
      profile: raw.profile as string | undefined,
      region: raw.region as string | undefined,
    };
  } catch {
    return { ok: false };
  }
}

export const api = { validate, principles, healthz, listPersonas };
