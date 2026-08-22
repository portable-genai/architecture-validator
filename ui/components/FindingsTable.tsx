import type { PrincipleFinding } from "@/lib/types";
import { SEVERITY_TONE, STATUS_TONE } from "@/lib/types";
import { CitationList } from "./CitationList";
import { Pill } from "./ui";

/** One row per principle: status, severity, evidence, remediation and citations. */
export function FindingsTable({ findings }: { findings: PrincipleFinding[] }) {
  return (
    <ul className="divide-y divide-ink-200">
      {findings.map((f) => (
        <li key={f.principle_id} className="py-3 first:pt-0 last:pb-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-sm font-semibold text-ink-800">
              {f.principle_id}
            </span>
            <Pill className={STATUS_TONE[f.status]}>{f.status}</Pill>
            <span className={`text-[11px] font-medium ${SEVERITY_TONE[f.severity]}`}>
              {f.severity}
            </span>
            <span className="ml-auto font-mono text-[11px] text-ink-400">{f.rule_id}</span>
          </div>
          <p className="mt-1 text-sm text-ink-700">{f.evidence}</p>
          {f.remediation ? (
            <p className="mt-1 text-[12px] text-ink-500">
              <span className="font-semibold text-ink-600">remediation:</span>{" "}
              {f.remediation}
            </p>
          ) : null}
          <CitationList citations={f.citations} />
        </li>
      ))}
    </ul>
  );
}
