import type { ValidationReport } from "@/lib/types";

/** The top-line PASS / FAIL verdict + the maker-checker review flag (P-06). */
export function VerdictBanner({ report }: { report: ValidationReport }) {
  const failed = report.findings.filter((f) => f.status === "FAIL");
  const tone = report.passed
    ? "bg-emerald-50 text-emerald-700 ring-emerald-200"
    : "bg-rose-50 text-rose-700 ring-rose-200";
  return (
    <div className={`rounded-xl px-4 py-3 ring-1 ring-inset ${tone}`}>
      <div className="flex items-center justify-between">
        <div>
          <div className="text-sm font-bold">
            {report.passed ? "PASS — clears intake" : "FAIL — blocked at intake"}
          </div>
          <div className="text-[11px] opacity-80">
            {report.submission.id} · {report.submission.name}
          </div>
        </div>
        <div className="text-right text-[11px]">
          <div>{report.findings.length} principles checked</div>
          <div>{failed.length} failing · {report.injected_requirements.length} requirements injected</div>
        </div>
      </div>
      {report.requires_human_review ? (
        <p className="mt-2 text-[11px] font-semibold">
          HUMAN REVIEW REQUIRED — maker-checker gate (P-06). A qualified reviewer must sign
          off before intake proceeds.
        </p>
      ) : null}
    </div>
  );
}
