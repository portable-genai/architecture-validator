# COMPLIANCE: Rsk3 Architecture, Requirements & Residency Validator

Documentation authority is declared in [`docs/doc-authority.md`](docs/doc-authority.md).

## Adopter-owned regulatory crosswalk

These mappings are implementation starting points, not legal conclusions. Each adopting bank owns
applicability analysis, exact clause/version references, legal and compliance approval, and
retained evidence that the configured policy implements its obligations.

| Regulator | Reference family to validate | Rsk3 implementation seam |
| --- | --- | --- |
| MAS | Technology risk, outsourcing and operational resilience obligations | P-01, P-03, P-06, P-07 and bank-owned `policy.allowed_regions` |
| HKMA | Technology risk management, outsourcing and operational resilience guidance | P-01, P-03, P-06, P-07 and jurisdiction evidence attached by the adopter |
| APRA | CPS 230, CPS 234 and cloud/outsourcing expectations | P-03, P-06, P-09 and the deterministic residency scan |
| FSA | Applicable local technology, outsourcing and data-location requirements | P-03, P-06, P-07 and adopter-owned rules/evidence |

Rsk3 is the **meta-enforcer** of the toolkit: it operationalises every General Principle as a
machine check and is the intake gate rule **R6** points to. It also owns a second enforcement
capability, a residency / IaC scanner, beside the design-time architecture checks. This
document maps each principle and rule to the concrete control in *this* repo. Three distinct
senses appear:

- **Rsk3 enforces P-xx** (design-time): Rsk3 *checks* that a validated project honours the
  principle (the `rule_*` in `domain/principles_eval.py` / `policies/principles.rego`).
- **The residency scanner enforces P-xx** (deploy-time): the `ViolationDetector`
  *checks* the bank's own IaC / cloud posture for residency and networking violations. It is
  the concrete enforcer of P-01 and P-03 (and detects P-09 / P-10 CMEK gaps). See the
  residency-scanner section below.
- **The repo itself honours P-xx**: this service's own implementation satisfies the principle.

## General Principles (P-01..P-12)

| Principle | The rule Rsk3 uses to check a project | How Rsk3 itself honours it |
| --- | --- | --- |
| **P-01** Hybrid on-prem + GCP (VPC-SC, no public egress) | `rule_p_01`: FAIL if `vpc_sc` not declared | OPA service is internal-ingress inside the VPC-SC perimeter (`vpc_sc.tf`, `cloud_run.tf`) |
| **P-02** No vendor lock-in (ports & adapters, Gemma fallback) | `rule_p_02`: FAIL if no ports-and-adapters / fallback | **Enforced-by target.** The whole repo is ports-and-adapters; four interchangeable adapter families (gcp / local / platform / onprem) behind each port; the `local` profile runs the whole pipeline off-cloud (SQLite FTS5 + deterministic LLM) and the `onprem` family is the documented exit, both proven interface-parity by the contract test; one rego + in-process evaluator from one source |
| **P-03** Single in-country region | `rule_p_03`: FAIL if region not in the approved set and no signed-off exception | Region pinned `asia-southeast1` in config + Terraform; Org Policy `gcp.resourceLocations` |
| **P-04** Minimise data to the model (DLP) | `rule_p_04`: NEEDS_INFO if PII without DLP; NOT_APPLICABLE if no PII | **N/A for Rsk3 itself**: Rsk3 processes project metadata, not customer PII, so it runs no DLP redaction. (It still *checks* that the validated project honours P-04.) |
| **P-05** Grounding over fine-tuning | `rule_p_05`: FAIL if fine-tuning on PII; NEEDS_INFO if fine-tuning without grounding | **Enforced-by target.** Rsk3 never fine-tunes; the LLM only drafts prose grounded in findings + KB citations |
| **P-06** Human-in-the-loop / maker-checker | `rule_p_06`: FAIL if `maker_checker` not declared | `ReviewPolicy` sets `requires_human_review` on any FAIL or HIGH/CRITICAL finding (`domain/hitl.py`); the escalation is then ROUTED to the Hrz7 maker-checker console (rule R8), not left as a per-repo boolean (`ports/review_router.py`, `adapters/*/review_router.py`) |
| **P-07** Auditable & explainable | `rule_p_07`: FAIL if no audit logging; NEEDS_INFO if no model card | Every verdict is audited to a locked WORM bucket; every finding / requirement is cited; Cloud Trace with content capture OFF |
| **P-08** Eval-gated promotion | `rule_p_08`: FAIL if `eval_gate` not declared | `eval/run_eval.py` + `eval-gate.yaml` + the Cloud Build intake-gate block promotion unless the gate passes |
| **P-09** Defense in depth / zero trust | `rule_p_09`: FAIL if no CMEK; NEEDS_INFO if no least-privilege IAM | CMEK on every CMEK-capable resource; least-privilege per-service SAs; private OPA endpoint (`kms.tf`, `iam.tf`) |
| **P-10** Resilience & graceful degradation | `rule_p_10`: NEEDS_INFO if no kill-switch / circuit-breaker | OPA outage falls back to the in-process evaluator; best-effort Rsk2/Rsk4 degrade silently |
| **P-11** Cost & latency control | `rule_p_11`: NEEDS_INFO if no model routing / caching / token budget | Triage-tier model available; token usage emitted to the tracer for FinOps |
| **P-12** Reversibility / documented exit | `rule_p_12`: FAIL if `has_exit_plan` is false | **Enforced-by target.** The `local` profile proves the domain runs off-cloud (no Google Cloud SDK), and the fail-fast `onprem` placeholder family + contract test are the documented, demonstrable exit path |

## Rules R1..R6, R8

(R7 is the marketing-compliance rule for customer-facing advertising output and does not apply to
an architecture intake validator.)

| Rule | Mapping in this repo |
| --- | --- |
| **R1** (regulator-grounded controls) | Findings and injected requirements cite the principle and, where relevant, the reg KB via `KnowledgeBasePort` (Rsk1 `/ask`) |
| **R2** (maker-checker on consequential output) | Shipped `ReviewPolicy` (P-06) flags every validation report for independent review before intake proceeds; configuration cannot remove this immutable safety floor |
| **R3** (auditable everything) | `AuditSinkPort` writes every verdict to the locked WORM bucket; `to_jsonable` keeps records replayable |
| **R4** (eval-gated promotion) | `EvaluationGatePort` + `eval/run_eval.py` (principle accuracy / injection recall / citation accuracy / safety) |
| **R5** (cross-system reuse / no duplication) | Rsk3 consumes Rsk1 (reg KB), Rsk2 (coverage) and Rsk4 (residency) rather than re-deriving them; registers in Hrz3, audits to Hrz5 |
| **R6** (any new project SHOULD pass Rsk3 at intake) | **Rsk3 IS the intake gate.** `POST /validate` and the `architecture-validator validate` CLI are the R6 enforcement point; the Cloud Build intake-gate wires it into CI/CD |
| **R8** (route `requires_human_review` to Hrz7) | Every shipped-policy `ValidationReport` is submitted to the Hrz7 Human-Review & Maker-Checker Console via the shared `review-kit` client, mapping the verdict to a severity and dual-control flag: `local` enqueues to an in-memory outbox so the routing path runs offline, `gcp`/`platform` submit over S2S to Hrz7's service intake (`HRZ_HUMAN_REVIEW_URL`), `onprem` is the fail-fast sovereign placeholder. The payload carries project metadata only (no customer PII in this repo). `ports/review_router.py`, `adapters/{local,platform,onprem}/review_router.py`, `adapters/_review_payload.py` |

## Residency scanner posture

The residency scanner is a policy-as-code gate over the bank's **own cloud posture / IaC**,
not over customer data: it reads Terraform plans, `.tf` directories, and the live estate
(Cloud Asset Inventory + SCC), so it carries **no customer PII** and, like the rest of this
repo, no Hrz1 Guardrail dependency. Its detector is deterministic, so a scan is reproducible
and auditable (the same plan always grades the same way), and the LLM only drafts remediation
prose (it can never flip a verdict). How the scanner represents each enforced principle:

| Principle | What the scanner detects |
| --- | --- |
| **P-01** Private-by-default networking | `PUBLIC_EGRESS` (a public IP / endpoint, or `public_access_prevention` not enforced) and `RESIDENCY_CONTROL_MISSING` (a data resource not inside a VPC-SC perimeter). Violations cite P-01. |
| **P-03** Single in-country region | `REGION_NOT_ALLOWED`, `GLOBAL_ENDPOINT`, and `UNKNOWN_REGION` against the configurable `allowed_regions`. The Terraform org-policy resource-location allowlist is the prevention boundary; the scanner is the detection gate. Violations cite P-03. |
| **P-09 / P-10** Defense in depth / CMEK | `MISSING_CMEK` on a data resource with no regional CMEK attribute. Violations cite the CMEK control. |

The scanner's own posture also honours the shared principles: every scan writes an immutable
`AuditEvent` to the locked WORM bucket (P-07); any HIGH/CRITICAL scan sets
`requires_human_review` and is routed to the Hrz7 maker-checker console (P-06 / R8); the
offline eval gate scores detection recall, precision, citation accuracy and safety over a
golden set (P-08); and the `local` profile proves the scan domain runs off-cloud while the
`onprem` placeholders are the documented exit (P-02 / P-12). Every `ResidencyViolation` cites
the breached principle and the in-country regulator (MAS / HKMA / APRA / FSA).

`allowed_regions` in the `residency_policy:` block of `config/settings.yaml` must stay in
lockstep with the Terraform `resource_locations` org-policy allow-set: the policy prevents,
the scanner detects.

## Honest N/A

- **P-04 boundary PII redaction / Hrz1 Guardrail** is **N/A for this repo itself**: it handles
  project metadata and design docs (validation) and infrastructure config (residency scan),
  not customer/PII data, so it ships no redaction or guardrail adapter. It still *checks*
  (`rule_p_04`) that a validated project honours P-04.
- Neither capability has a customer-facing surface, so there is no end-user PII flow to redact
  in the audit trail; the validation audit event carries the submission summary and the
  verdict only, and the scan audit event carries the target, verdict, counts and citations
  only (no resource attribute values, content capture OFF).
