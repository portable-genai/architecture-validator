# Compliance FAQ

For compliance, risk, and model-risk teams assessing the repo's regulatory posture.
Cross-references: [`COMPLIANCE.md`](../../COMPLIANCE.md) (the full principle-to-control map,
P-01..P-12 and R1..R6 / R8), [`SPEC.md`](../../SPEC.md).

### What is this system, in one line, for a control owner?

It is the **meta-enforcer**: the policy-as-code gate that operationalises every General
Principle (P-01..P-12) as a machine check at project intake, and the enforcement point rule
R6 refers to ("any new project SHOULD pass `architecture-validator` at intake"). It validates a project's design,
grounds each finding in the principle and the reg KB, and auto-injects the missing
non-functional requirements.

### Is this making decisions autonomously?

No. It is a **decision-support** gate. The deterministic engines produce a documented,
replayable verdict; a non-clean `ValidationReport` sets `requires_human_review` and is routed
to the `human-review-console` (rule R8) for a qualified human to dispose.
Nothing auto-executes; escalation signals (a FAIL, a HIGH/CRITICAL finding) raise the review
bar and never lower it.

### How is customer PII handled?

It is not present. `architecture-validator` processes **project metadata and design documents, not customer PII**
(stated in `domain/models.py` and the `COMPLIANCE.md` "Honest N/A" section). Because there is
no PII flow, there is no runtime redactor and no jurisdiction PII pack, and the audit event
carries the submission summary and the verdict only. This is an **honest N/A by design**
(practices-audit checks C3 / C4), confirmed in code, not an omission. The validator still
*checks* (`rule_p_04`) that the projects it validates honour redact-before-everything (P-04);
the runtime DLP/guardrail for a project that *does* handle PII is the sibling `agent-guardrail-gateway`, which such a project consumes.

### How is the work auditable / reproducible?

Every verdict is written to an immutable WORM audit event with the decision and the citation
set (P-07); the managed profile uses a locked WORM bucket and the offline profile a
hash-chained append-only store (`hex_service_kit.audit`). Every `PrincipleFinding` and every
`InjectedRequirement` carries a citation (to the principle and/or the reg KB), and the
consequential math is deterministic, so a reviewer can recompute any verdict from the same
submission. The enterprise WORM audit system is `agent-observability`; the in-repo store is the offline
stand-in (see [security-faq.md](security-faq.md) for its exact tamper-evidence limits).

### What is the model-risk story?

An offline eval gate (`eval/run_eval.py`) scores principle accuracy, injection recall,
citation accuracy, and a strict safety metric against a golden set, failing the build below
threshold (P-08). The safety metric (`safety >= 0.99`) is structurally unable to go falsely
green: a golden project expected to FAIL that is reported `passed` scores 0. The enterprise
promotion gate and model documentation / red-team harness are the sibling `model-quality-gate` system
(registered bundle `rsk3-architecture-validator`); this repo's gate mirrors its thresholds so
merges are guarded locally. A fork must rebuild the golden set for its own framework.

### Which regulators does this map to?

`COMPLIANCE.md` maps the internal P-01..P-12 and R1..R6 / R8 controls to concrete code and
file references. The residency default is `asia-southeast1` (Singapore), and the principle set
was designed against an APAC regulated-industry baseline (MAS / HKMA / APRA / FSA). **Known
gap (check G2, PARTIAL):** there is not yet an adopter-owned per-regulator crosswalk appendix
naming who owns the MAS / HKMA / APRA / FSA mapping; at scale the sibling **`compliance-advisory` compliance
assistant** and its control-mapping module generate and maintain such crosswalks, and a large
estate should integrate them rather than hand-maintain a table.

### Is data residency enforced?

Yes, at deploy time: a single in-country region (default `asia-southeast1`), validated to
fail fast, with an Org Policy `gcp.resourceLocations` allowlist, CMEK, and a VPC-SC perimeter
(P-03, P-09). The residency-violation CI gate is this repo's own residency scanner, served
in-process; the exit / concentration-risk plan belongs to the sibling **`operational-resilience-mapping`
operational-resilience mapping** system. This repo enforces residency in its own infra and is
one of the systems that planner reasons about.

### Can we run it against real project data today?

Yes for its intended input, which is project metadata and design documents, not customer PII;
but treat it as a reference build. Every fixture and golden dataset is obviously fictional,
and the docs state throughout that a live deployment needs your own security, and model-risk
sign-off. The adoption checklist (`docs/ADOPTING.md`) lists the steps, own the principle set,
rebuild the eval golden set, wire your IdP and `human-review-console` endpoint, that precede production use.
