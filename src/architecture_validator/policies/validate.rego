# OPA entrypoint for the C3 intake gate (decision path: arch/validate).
#
# The OpaPolicyAdapter POSTs {"input": {"submission": {...}, "principles": [...]}} to
# POST /v1/data/arch/validate and reads result.findings — one object per principle with
# {principle_id, status, rule_id, evidence, severity, remediation}. The per-principle rule
# logic lives in principles.rego; this file just assembles the findings array so the
# decision shape matches what the adapter parses.
#
# This rego bundle is the managed-path twin of the deterministic in-process evaluator in
# src/architecture_validator/domain/principles_eval.py; the two are kept in lockstep so the gcp and
# onprem/test paths agree by construction (P-02).

package arch.validate

import data.arch.principles

# The decision the adapter consumes.
findings := principles.findings

# Convenience booleans for callers that only want the verdict.
passed if {
	count([f | some f in findings; f.status == "FAIL"]) == 0
}

requires_human_review if {
	count([f | some f in findings; f.status == "FAIL"]) > 0
}

requires_human_review if {
	some f in findings
	f.status in {"FAIL", "NEEDS_INFO"}
	f.severity in {"high", "critical"}
}
