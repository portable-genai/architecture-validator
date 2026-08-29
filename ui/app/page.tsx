"use client";

import { useCallback, useEffect, useState } from "react";
import { api, API_BASE, setDevPersona } from "@/lib/api";
import type { Persona } from "@/lib/api";
import type { ProjectSubmission, ValidationReport } from "@/lib/types";
import { SubmissionForm } from "@/components/SubmissionForm";
import { VerdictBanner } from "@/components/VerdictBanner";
import { FindingsTable } from "@/components/FindingsTable";
import { InjectedRequirements } from "@/components/InjectedRequirements";
import { Panel } from "@/components/ui";

export default function Page() {
  const [report, setReport] = useState<ValidationReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [health, setHealth] = useState<"checking" | "up" | "down">("checking");
  const [profile, setProfile] = useState<string | undefined>(undefined);
  const [personas, setPersonas] = useState<Persona[]>([]);
  const [selectedPersona, setSelectedPersona] = useState("");

  useEffect(() => {
    let active = true;
    const probe = async () => {
      const res = await api.healthz();
      if (!active) return;
      setHealth(res.ok ? "up" : "down");
      setProfile(res.profile);
    };
    void probe();
    const id = window.setInterval(probe, 30_000);
    return () => {
      active = false;
      window.clearInterval(id);
    };
  }, []);

  // Demo identity picker: local profile only (no IdP). Loads the seeded personas and
  // default-selects the first so per-user authorization is demoable offline.
  useEffect(() => {
    if (profile !== "local") return;
    let active = true;
    void (async () => {
      try {
        const list = await api.listPersonas();
        if (!active || list.length === 0) return;
        setPersonas(list);
        setSelectedPersona(list[0].id);
        setDevPersona(list[0].id);
      } catch {
        // Persona picker is a dev-only convenience; ignore lookup failures.
      }
    })();
    return () => {
      active = false;
    };
  }, [profile]);

  const onPersonaChange = useCallback((id: string) => {
    setSelectedPersona(id);
    setDevPersona(id);
  }, []);

  const handleSubmit = useCallback(async (submission: ProjectSubmission) => {
    setBusy(true);
    setError(null);
    try {
      setReport(await api.validate(submission));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setReport(null);
    } finally {
      setBusy(false);
    }
  }, []);

  // EMBED mode: the host owns the chrome, so drop our own TopBar (layout.tsx drops the
  // full-viewport wrapper to match).
  const embed = process.env.NEXT_PUBLIC_EMBED === "1";

  return (
    <div className={embed ? "bg-ink-50" : "min-h-screen bg-ink-50"}>
      {embed ? null : <TopBar health={health} profile={profile} />}
      <main className="mx-auto grid max-w-6xl gap-4 p-4 lg:grid-cols-[22rem_minmax(0,1fr)]">
        <aside className="space-y-4">
          {profile === "local" && personas.length > 0 ? (
            <Panel title="Demo identity" subtitle="local profile · no IdP · X-Dev-Persona">
              <label className="block text-sm">
                <span className="text-ink-500">Persona</span>
                <select
                  className="mt-1 w-full rounded border border-ink-200 px-2 py-1.5 text-sm"
                  value={selectedPersona}
                  onChange={(e) => onPersonaChange(e.target.value)}
                >
                  {personas.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.subject} · {p.tenant}
                    </option>
                  ))}
                </select>
              </label>
            </Panel>
          ) : null}
          <Panel title="Project submission" subtitle="POST /validate (intake gate, R6)">
            <SubmissionForm busy={busy} onSubmit={handleSubmit} />
          </Panel>
        </aside>

        <section className="space-y-4">
          {error ? (
            <div className="rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700 ring-1 ring-inset ring-rose-200">
              {error}
            </div>
          ) : null}

          {!report && !error ? (
            <div className="rounded-xl bg-white px-4 py-10 text-center text-sm text-ink-400 shadow-panel ring-1 ring-inset ring-ink-200">
              Submit a project on the left to validate it against the 12 General Principles.
            </div>
          ) : null}

          {report ? (
            <>
              <VerdictBanner report={report} />
              <Panel
                title="Principle findings"
                subtitle="One per principle · PASS only if no FAIL"
              >
                <FindingsTable findings={report.findings} />
              </Panel>
              <Panel
                title="Injected requirements"
                subtitle="Missing non-functional requirements auto-injected at intake"
              >
                <InjectedRequirements requirements={report.injected_requirements} />
              </Panel>
            </>
          ) : null}
        </section>
      </main>
    </div>
  );
}

function TopBar({
  health,
  profile,
}: {
  health: "checking" | "up" | "down";
  profile?: string;
}) {
  const tone =
    health === "up" ? "bg-emerald-500" : health === "down" ? "bg-rose-500" : "bg-amber-400";
  const label =
    health === "up" ? "backend up" : health === "down" ? "backend down" : "checking…";
  return (
    <header className="flex items-center justify-between border-b border-ink-200 bg-white px-4 py-2.5">
      <div className="flex items-center gap-2.5">
        <img
          src="/logo.jpg"
          alt=""
          width={32}
          height={32}
          className="h-8 w-8 rounded-lg object-cover"
        />
        <div>
          <h1 className="text-sm font-semibold leading-tight text-ink-900">
            Architecture &amp; Requirements Validator
          </h1>
          <p className="text-[11px] leading-tight text-ink-400">
            rsk · 12 General Principles · intake gate (R6) · asia-southeast1
          </p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        {profile ? (
          <span className="hidden font-mono text-[11px] text-ink-400 sm:inline">
            profile={profile}
          </span>
        ) : null}
        <span className="hidden font-mono text-[11px] text-ink-400 sm:inline">{API_BASE}</span>
        <span className="inline-flex items-center gap-1.5 rounded-md bg-ink-50 px-2 py-1 text-[11px] font-medium text-ink-600 ring-1 ring-inset ring-ink-200">
          <span className={`h-1.5 w-1.5 rounded-full ${tone}`} />
          {label}
        </span>
      </div>
    </header>
  );
}
