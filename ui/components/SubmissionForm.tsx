"use client";

import { useState } from "react";
import type { ProjectSubmission } from "@/lib/types";

const ALL_CONTROLS = [
  "vpc_sc",
  "ports_and_adapters",
  "cmek",
  "least_privilege_iam",
  "dlp",
  "eval_gate",
  "maker_checker",
  "audit_logging",
  "model_card",
  "kill_switch",
  "circuit_breaker",
  "model_routing",
  "caching",
  "token_budget",
];

const REGIONS = [
  "asia-southeast1",
  "australia-southeast1",
  "asia-east2",
  "asia-northeast1",
  "us-central1",
  "eu-west1",
];

const DEFAULTS: ProjectSubmission = {
  id: "proj-001",
  name: "Customer-facing GenAI onboarding bot",
  description: "A customer onboarding assistant on the managed agent platform.",
  requirements: "Handle KYC onboarding; ground answers in policy.",
  declared_region: "asia-southeast1",
  declared_controls: ["ports_and_adapters", "audit_logging"],
  uses_pii: true,
  uses_rag: true,
  uses_fine_tuning: false,
  has_exit_plan: false,
};

export function SubmissionForm({
  busy,
  onSubmit,
}: {
  busy: boolean;
  onSubmit: (s: ProjectSubmission) => void;
}) {
  const [s, setS] = useState<ProjectSubmission>(DEFAULTS);

  const toggleControl = (c: string) =>
    setS((prev) => ({
      ...prev,
      declared_controls: prev.declared_controls.includes(c)
        ? prev.declared_controls.filter((x) => x !== c)
        : [...prev.declared_controls, c],
    }));

  return (
    <form
      className="space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        onSubmit(s);
      }}
    >
      <Field label="Project id">
        <input className="input" value={s.id} onChange={(e) => setS({ ...s, id: e.target.value })} />
      </Field>
      <Field label="Name">
        <input className="input" value={s.name} onChange={(e) => setS({ ...s, name: e.target.value })} />
      </Field>
      <Field label="Description">
        <textarea
          className="input min-h-[64px]"
          value={s.description}
          onChange={(e) => setS({ ...s, description: e.target.value })}
        />
      </Field>

      <Field label="Declared region">
        <select
          className="input"
          value={s.declared_region ?? ""}
          onChange={(e) => setS({ ...s, declared_region: e.target.value || null })}
        >
          {REGIONS.map((r) => (
            <option key={r} value={r}>
              {r}
            </option>
          ))}
        </select>
      </Field>

      <Field label="Declared controls">
        <div className="flex flex-wrap gap-1.5">
          {ALL_CONTROLS.map((c) => {
            const on = s.declared_controls.includes(c);
            return (
              <button
                type="button"
                key={c}
                onClick={() => toggleControl(c)}
                className={`rounded-md px-2 py-1 font-mono text-[11px] ring-1 ring-inset ${
                  on
                    ? "bg-regblue-600 text-white ring-regblue-600"
                    : "bg-white text-ink-600 ring-ink-200 hover:bg-ink-50"
                }`}
              >
                {c}
              </button>
            );
          })}
        </div>
      </Field>

      <div className="grid grid-cols-2 gap-2">
        <Toggle label="uses_pii" v={s.uses_pii} on={(v) => setS({ ...s, uses_pii: v })} />
        <Toggle label="uses_rag" v={s.uses_rag} on={(v) => setS({ ...s, uses_rag: v })} />
        <Toggle
          label="uses_fine_tuning"
          v={s.uses_fine_tuning}
          on={(v) => setS({ ...s, uses_fine_tuning: v })}
        />
        <Toggle
          label="has_exit_plan"
          v={s.has_exit_plan}
          on={(v) => setS({ ...s, has_exit_plan: v })}
        />
      </div>

      <button
        type="submit"
        disabled={busy}
        className="w-full rounded-lg bg-regblue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-regblue-700 disabled:opacity-50"
      >
        {busy ? "Validating…" : "Validate at intake"}
      </button>
    </form>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-ink-500">
        {label}
      </span>
      {children}
    </label>
  );
}

function Toggle({
  label,
  v,
  on,
}: {
  label: string;
  v: boolean;
  on: (v: boolean) => void;
}) {
  return (
    <button
      type="button"
      onClick={() => on(!v)}
      className={`flex items-center justify-between rounded-lg border px-2.5 py-2 text-left text-[12px] ${
        v ? "border-regblue-300 bg-regblue-50" : "border-ink-200 hover:bg-ink-50"
      }`}
    >
      <span className="font-mono text-ink-700">{label}</span>
      <span
        className={`h-2 w-2 rounded-full ${v ? "bg-regblue-600" : "bg-ink-300"}`}
      />
    </button>
  );
}
