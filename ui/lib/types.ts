/**
 * TypeScript mirrors of the C3 domain dataclasses.
 *
 * Source of truth: `src/architecture_validator/domain/models.py`.
 * The backend serialises dataclasses with `domain/serialization.to_jsonable` (SPEC §5):
 * dataclass field names are preserved (snake_case) and every enum is rendered as its
 * `.value` string. These types follow that contract exactly.
 */

export type Regulator = "MAS" | "HKMA" | "APRA" | "FSA" | "CROSS";
export type Jurisdiction = "SG" | "HK" | "AU" | "JP" | "GLOBAL";
export type Severity = "low" | "medium" | "high" | "critical";
export type CheckStatus = "PASS" | "FAIL" | "NEEDS_INFO" | "NOT_APPLICABLE";

export interface Citation {
  source_id: string;
  regulator: Regulator;
  jurisdiction: Jurisdiction;
  title: string;
  url: string;
  version: string;
  page: number | null;
  snippet: string;
  score: number | null;
}

export interface Principle {
  id: string;
  title: string;
  statement: string;
  machine_rule: string;
  enforced_by: string[];
}

export interface ProjectSubmission {
  id: string;
  name: string;
  description: string;
  requirements: string;
  declared_region: string | null;
  declared_controls: string[];
  uses_pii: boolean;
  uses_rag: boolean;
  uses_fine_tuning: boolean;
  has_exit_plan: boolean;
  attributes?: Record<string, string>;
}

export interface PrincipleFinding {
  principle_id: string;
  status: CheckStatus;
  rule_id: string;
  evidence: string;
  severity: Severity;
  remediation: string;
  citations: Citation[];
}

export interface InjectedRequirement {
  id: string;
  principle_id: string;
  requirement_text: string;
  rationale: string;
  severity: Severity;
  citations: Citation[];
}

export interface ValidationReport {
  submission: ProjectSubmission;
  findings: PrincipleFinding[];
  injected_requirements: InjectedRequirement[];
  passed: boolean;
  requires_human_review: boolean;
  generated_at: string;
}

export const STATUS_TONE: Record<CheckStatus, string> = {
  PASS: "text-emerald-600 bg-emerald-50 ring-emerald-200",
  FAIL: "text-rose-600 bg-rose-50 ring-rose-200",
  NEEDS_INFO: "text-amber-600 bg-amber-50 ring-amber-200",
  NOT_APPLICABLE: "text-ink-400 bg-ink-50 ring-ink-200",
};

export const SEVERITY_TONE: Record<Severity, string> = {
  low: "text-ink-500",
  medium: "text-amber-600",
  high: "text-orange-600",
  critical: "text-rose-600",
};
