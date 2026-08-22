import type { InjectedRequirement } from "@/lib/types";
import { SEVERITY_TONE } from "@/lib/types";
import { CitationList } from "./CitationList";

/** The auto-injected non-functional requirements, one per unmet principle. */
export function InjectedRequirements({
  requirements,
}: {
  requirements: InjectedRequirement[];
}) {
  if (!requirements.length) {
    return (
      <p className="text-sm text-emerald-600">
        No missing requirements — every principle is satisfied.
      </p>
    );
  }
  return (
    <ul className="space-y-3">
      {requirements.map((r) => (
        <li
          key={r.id}
          className="rounded-lg border border-regblue-200 bg-regblue-50 p-3"
        >
          <div className="flex items-center gap-2">
            <span className="font-mono text-[11px] font-semibold text-regblue-700">
              {r.principle_id}
            </span>
            <span className={`text-[11px] font-medium ${SEVERITY_TONE[r.severity]}`}>
              {r.severity}
            </span>
          </div>
          <p className="mt-1 text-sm font-medium text-ink-800">{r.requirement_text}</p>
          <p className="mt-1 text-[12px] text-ink-500">{r.rationale}</p>
          <CitationList citations={r.citations} />
        </li>
      ))}
    </ul>
  );
}
