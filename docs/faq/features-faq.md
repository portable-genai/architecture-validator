# Features FAQ

For product, architecture-review-board, and delivery teams: what this gate does, what is
deterministic vs LLM, how the OPA/Rego policy-as-code fits, and, importantly, where its
responsibilities **stop** and a sibling catalog system takes over. Cross-references:
[`README.md`](../../README.md), [`SPEC.md`](../../SPEC.md),
[`COMPLIANCE.md`](../../COMPLIANCE.md).

### What does `architecture-validator` actually produce?

It is the **policy-as-code gate at project intake**. From a `ProjectSubmission` (the
project's requirements and design metadata) it produces three cited artifacts:

1. **ValidationReport**: the overall verdict (PASS only if no principle FAILs), the
   per-principle findings, the injected requirements, and the `requires_human_review` flag.
2. **PrincipleFinding[]**: one per principle (P-01..P-12): `principle_id`, `status`
   (PASS / FAIL / NEEDS_INFO / NOT_APPLICABLE), the `rule_id` that checked it, the evidence
   that drove the verdict, `severity`, `remediation`, and `citations`.
3. **InjectedRequirement[]**: the missing non-functional requirements auto-injected at
   intake (for example "Pin all data and processing to `asia-southeast1` (P-03)", "Place
   managed-service APIs inside a VPC-SC perimeter, no public egress (P-01)"), each tied to
   the principle that mandates it, with rationale, severity, and citations.

So a project cannot start non-compliant: it either passes the 12 principles or it leaves
intake carrying the exact requirements it must satisfy. This is the enforcement point rule
**R6** refers to.

### What is policy-as-code here, concretely? Where does OPA / Rego come in?

The 12 General Principles are expressed **twice from one source of truth**: as a Rego bundle
(`policies/principles.rego`, `policies/validate.rego`, decision path `arch/validate`)
evaluated by an **OPA REST service** on the managed profile, and as an in-process
deterministic evaluator (`domain/principles_eval.py`) that produces the identical verdicts.
The `local` and `onprem` profiles run entirely on the in-process evaluator (no OPA service),
and on the managed profile an **OPA outage falls back** to it, so a verdict is always
produced (P-10). Keeping the two in step is a contract rule: a change to a principle check
touches `principles_eval.py`, the rego rule, and a test together.

### What is deterministic vs done by the LLM?

The consequential verdicts are **deterministic and replayable** (pure stdlib, unit-tested in
`test_principles_eval.py`): all 12 PASS / FAIL / NEEDS_INFO / NOT_APPLICABLE decisions and
the maker-checker escalation policy. The LLM only **drafts** the injected-requirement prose,
grounded in the finding and reg-KB citations, and never sets a verdict
(`domain/injection_service.py`). An architecture reviewer can recompute every decision
without the model. This is the "deterministic domain service" pattern.

### Is anything auto-approved?

Nothing auto-executes. `ReviewPolicy` sets `requires_human_review=True` on any FAIL or any
HIGH/CRITICAL open finding (`domain/hitl.py`), and that escalation is then **routed to the
`human-review-console`** through the shared `review-kit` client
(rule R8), not left as a per-repo boolean. A fully clean report (all PASS / NOT_APPLICABLE)
may pass without a checker by design, because that is the point of a gate that lets compliant
intakes through; a non-clean one goes to a human.

### Which capabilities does this repo own vs integrate from the catalog?

This is one system in a catalog of composable GRC systems. It **owns** the principle
evaluation, the requirement-injection logic, and the policy-as-code bundle. It **integrates**
(via the `platform` profile's httpx delegates) several cross-cutting concerns owned by
sibling systems; do not rebuild these in a fork:

| Concern | Owned by (catalog id / repo) | `architecture-validator`'s role |
|---|---|---|
| Regulatory Q&A / reg-KB with citations | `compliance-advisory` | consumes it (`/ask`) to ground findings and injected requirements |
| Control coverage / evidence packs | `compliance-advisory` (`domain/control_mapping/`) | consumes its coverage / evidence-pack output; does not re-derive control maps |
| Agent registry, versioning, discovery | `agent-registry` | publishes its A2A AgentCard for discovery |
| AI-quality / eval / model-risk promotion gate | `model-quality-gate` | its eval metrics gate promotion (bundle `rsk3-architecture-validator`); the offline gate mirrors it |
| Observability + immutable WORM audit | `agent-observability` | writes audit events to it; traces spans through it |
| Human-review / maker-checker console | `human-review-console` | routes every `requires_human_review` escalation to it (R8) |

The guardrail gateway (`agent-guardrail-gateway`) is **N/A** for this repo: `architecture-validator` processes project metadata, not
customer PII, so there is no runtime redactor to place behind a guardrail port.

### Can I use this to enforce a different principle set?

Yes, that is the point. The 12-principle set is a deliberately closed governance ruleset, but
it is data plus rules: you replace the principle definitions (`policies/principles.yaml` +
the rego rules + `domain/principles_eval.py`, kept in step by the contract rule) and the
injection prompts for your own control framework, and keep the whole hexagon, the four
profiles, the eval gate, and the `human-review-console` routing. See [`docs/ADOPTING.md`](../ADOPTING.md) and
[adoption-faq.md](adoption-faq.md).

### How do I see it working?

`make demo` runs the presenter-controlled walkthrough (real `ValidationService`, `local`
profile, no cloud and no API key) and `make demo-server` serves a live click-through on port
8092. Everything runs on synthetic, fictional submissions.
