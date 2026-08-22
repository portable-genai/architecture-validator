# Per-principle rules for the 12 General Principles (P-01..P-12).
#
# Each principle contributes exactly one object to `findings`. The rules mirror
# domain/principles_eval.py one-for-one so the OPA (managed) path and the deterministic
# in-process (onprem/test) path produce identical verdicts. Inputs:
#   input.submission.declared_controls : array[string]
#   input.submission.declared_region   : string
#   input.submission.uses_pii / uses_rag / uses_fine_tuning / has_exit_plan : bool
#   input.submission.attributes         : object[string,string]
#   input.policy.allowed_regions        : array[string] (bank-owned settings)

package arch.principles

has_control(c) if {
	some declared in input.submission.declared_controls
	lower(declared) == lower(c)
}

region := input.submission.declared_region

region_exception if {
	val := input.submission.attributes.region_exception
	lower(val) in {"true", "yes", "1", "signed", "signed_off", "approved"}
}

# --- P-01 -------------------------------------------------------------------
p01 := {"principle_id": "P-01", "rule_id": "rule_p_01", "severity": "high", "status": s, "evidence": e, "remediation": r} if {
	has_control("vpc_sc")
	s := "PASS"
	e := "VPC Service Controls perimeter declared; managed-service APIs are private."
	r := ""
} else := {"principle_id": "P-01", "rule_id": "rule_p_01", "severity": "high", "status": "FAIL", "evidence": "No VPC Service Controls perimeter declared; managed-service APIs would egress publicly.", "remediation": "Place all managed-service APIs inside a VPC-SC perimeter; no public egress."}

# --- P-02 -------------------------------------------------------------------
p02 := {"principle_id": "P-02", "rule_id": "rule_p_02", "severity": "medium", "status": "PASS", "evidence": "Ports-and-adapters and/or a documented fallback are declared.", "remediation": ""} if {
	has_control("ports_and_adapters")
} else := {"principle_id": "P-02", "rule_id": "rule_p_02", "severity": "medium", "status": "FAIL", "evidence": "No ports-and-adapters boundary or documented fallback declared.", "remediation": "Adopt a ports-and-adapters boundary and document a Gemma fallback."}

# --- P-03 -------------------------------------------------------------------
p03 := {"principle_id": "P-03", "rule_id": "rule_p_03", "severity": "high", "status": "NEEDS_INFO", "evidence": "No region declared; residency cannot be confirmed.", "remediation": "Declare the single in-country region."} if {
	not region
} else := {"principle_id": "P-03", "rule_id": "rule_p_03", "severity": "high", "status": "PASS", "evidence": "Region is an approved in-country region.", "remediation": ""} if {
	some allowed in input.policy.allowed_regions
	allowed == region
} else := {"principle_id": "P-03", "rule_id": "rule_p_03", "severity": "high", "status": "PASS", "evidence": "Region outside the approved set but carries a signed-off exception.", "remediation": ""} if {
	region_exception
} else := {"principle_id": "P-03", "rule_id": "rule_p_03", "severity": "critical", "status": "FAIL", "evidence": "Region is not an approved in-country region and no exception is signed off.", "remediation": "Pin all data and processing to an approved in-country region."}

# --- P-04 -------------------------------------------------------------------
p04 := {"principle_id": "P-04", "rule_id": "rule_p_04", "severity": "low", "status": "NOT_APPLICABLE", "evidence": "No PII processing declared.", "remediation": ""} if {
	not input.submission.uses_pii
} else := {"principle_id": "P-04", "rule_id": "rule_p_04", "severity": "high", "status": "PASS", "evidence": "PII is processed and DLP boundary redaction is declared.", "remediation": ""} if {
	has_control("dlp")
} else := {"principle_id": "P-04", "rule_id": "rule_p_04", "severity": "high", "status": "NEEDS_INFO", "evidence": "PII processed without declared DLP boundary redaction.", "remediation": "Redact PII at the boundary via DLP before any model call."}

# --- P-05 -------------------------------------------------------------------
p05 := {"principle_id": "P-05", "rule_id": "rule_p_05", "severity": "critical", "status": "FAIL", "evidence": "Fine-tunes a model on data that includes PII.", "remediation": "Do not train on PII; prefer grounding on governed data."} if {
	input.submission.uses_fine_tuning
	input.submission.uses_pii
} else := {"principle_id": "P-05", "rule_id": "rule_p_05", "severity": "medium", "status": "NEEDS_INFO", "evidence": "Fine-tunes without a declared grounding approach.", "remediation": "Prefer grounding over fine-tuning; confirm no PII is used."} if {
	input.submission.uses_fine_tuning
	not input.submission.uses_rag
} else := {"principle_id": "P-05", "rule_id": "rule_p_05", "severity": "medium", "status": "PASS", "evidence": "Grounding-first approach with no PII fine-tuning.", "remediation": ""}

# --- P-06 -------------------------------------------------------------------
p06 := {"principle_id": "P-06", "rule_id": "rule_p_06", "severity": "high", "status": "PASS", "evidence": "A maker-checker control is declared.", "remediation": ""} if {
	has_control("maker_checker")
} else := {"principle_id": "P-06", "rule_id": "rule_p_06", "severity": "high", "status": "FAIL", "evidence": "No maker-checker control declared for consequential decisions.", "remediation": "Add a maker-checker gate so a human reviews consequential decisions."}

# --- P-07 -------------------------------------------------------------------
p07 := {"principle_id": "P-07", "rule_id": "rule_p_07", "severity": "high", "status": "FAIL", "evidence": "No immutable audit-logging control declared.", "remediation": "Emit immutable (WORM) audit logs with citations."} if {
	not has_control("audit_logging")
} else := {"principle_id": "P-07", "rule_id": "rule_p_07", "severity": "medium", "status": "NEEDS_INFO", "evidence": "Audit logging declared but no model card.", "remediation": "Publish a model card documenting purpose, data, limitations and evaluation."} if {
	not has_control("model_card")
} else := {"principle_id": "P-07", "rule_id": "rule_p_07", "severity": "high", "status": "PASS", "evidence": "Immutable audit logging and a model card are declared.", "remediation": ""}

# --- P-08 -------------------------------------------------------------------
p08 := {"principle_id": "P-08", "rule_id": "rule_p_08", "severity": "high", "status": "PASS", "evidence": "An evaluation gate guards promotion.", "remediation": ""} if {
	has_control("eval_gate")
} else := {"principle_id": "P-08", "rule_id": "rule_p_08", "severity": "high", "status": "FAIL", "evidence": "No evaluation gate declared; promotion would be ungated.", "remediation": "Gate promotion on a quantitative evaluation suite."}

# --- P-09 -------------------------------------------------------------------
p09 := {"principle_id": "P-09", "rule_id": "rule_p_09", "severity": "high", "status": "FAIL", "evidence": "No CMEK declared.", "remediation": "Encrypt with CMEK; use private endpoints and least-privilege IAM."} if {
	not has_control("cmek")
} else := {"principle_id": "P-09", "rule_id": "rule_p_09", "severity": "medium", "status": "NEEDS_INFO", "evidence": "CMEK declared but least-privilege IAM not confirmed.", "remediation": "Confirm least-privilege IAM and distinct per-agent identities."} if {
	not has_control("least_privilege_iam")
} else := {"principle_id": "P-09", "rule_id": "rule_p_09", "severity": "high", "status": "PASS", "evidence": "CMEK and least-privilege IAM are declared.", "remediation": ""}

# --- P-10 -------------------------------------------------------------------
p10 := {"principle_id": "P-10", "rule_id": "rule_p_10", "severity": "high", "status": "PASS", "evidence": "Resilience controls declared.", "remediation": ""} if {
	has_control("kill_switch")
} else := {"principle_id": "P-10", "rule_id": "rule_p_10", "severity": "high", "status": "PASS", "evidence": "Resilience controls declared.", "remediation": ""} if {
	has_control("circuit_breaker")
} else := {"principle_id": "P-10", "rule_id": "rule_p_10", "severity": "high", "status": "NEEDS_INFO", "evidence": "No kill-switch or circuit-breaker declared.", "remediation": "Add fallbacks, a circuit breaker and a kill-switch (APRA CPS 230 / HKMA OR-2)."}

# --- P-11 -------------------------------------------------------------------
p11 := {"principle_id": "P-11", "rule_id": "rule_p_11", "severity": "low", "status": "PASS", "evidence": "Cost / latency control declared.", "remediation": ""} if {
	some c in {"model_routing", "caching", "token_budget"}
	has_control(c)
} else := {"principle_id": "P-11", "rule_id": "rule_p_11", "severity": "low", "status": "NEEDS_INFO", "evidence": "No cost / latency control declared.", "remediation": "Add model routing, response caching and per-request token budgets."}

# --- P-12 -------------------------------------------------------------------
p12 := {"principle_id": "P-12", "rule_id": "rule_p_12", "severity": "medium", "status": "PASS", "evidence": "A documented exit plan is declared.", "remediation": ""} if {
	input.submission.has_exit_plan
} else := {"principle_id": "P-12", "rule_id": "rule_p_12", "severity": "medium", "status": "FAIL", "evidence": "No documented exit plan; the system is not demonstrably reversible.", "remediation": "Document and test an exit plan that lets the system be migrated off the managed stack."}

# Assemble the findings array (P-01..P-12, in order).
findings := [p01, p02, p03, p04, p05, p06, p07, p08, p09, p10, p11, p12]
