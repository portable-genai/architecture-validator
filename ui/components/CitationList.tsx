import type { Citation } from "@/lib/types";

/** Renders the provenance for a finding or injected requirement. */
export function CitationList({ citations }: { citations: Citation[] }) {
  if (!citations || citations.length === 0) {
    return <p className="text-[11px] text-amber-600">(no citation)</p>;
  }
  return (
    <ul className="mt-1 space-y-0.5">
      {citations.map((c, i) => (
        <li key={`${c.source_id}-${i}`} className="text-[11px] text-ink-500">
          <span className="font-mono text-ink-700">
            [{c.source_id}
            {c.page != null ? ` p.${c.page}` : ""}]
          </span>{" "}
          <span className="text-ink-500">
            {c.regulator}
            {c.title ? ` · ${c.title}` : ""}
          </span>
          {c.url ? (
            <>
              {" "}
              <a
                href={c.url}
                className="text-regblue-600 underline-offset-2 hover:underline"
                target="_blank"
                rel="noreferrer"
              >
                source
              </a>
            </>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
