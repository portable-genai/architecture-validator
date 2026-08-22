# Adopting this repo as your base

This repository (Rsk3, the Architecture and Requirements Validator) is a **common base**
that a bank or other regulated institution forks to build its own **policy-as-code intake
gate**: a service that validates a project's design against a governance ruleset, grounds
each finding in a regulatory knowledge base, and auto-injects the missing non-functional
requirements so a project cannot start non-compliant. It ships a reusable hexagonal core (a
pure-stdlib domain, typed ports, four swappable adapter profiles, a green offline gate) plus
a fully worked 12-principle (P-01..P-12) vertical you can keep, retune, or replace with your
own control framework.

This guide is the step-by-step for making it yours. It has two halves: a **mechanical
rebrand** (one script) and the **human decisions** the script cannot make for you.

> Related reading: [`ARCHITECTURE.md`](../ARCHITECTURE.md) (the port table and topology),
> [`CONTRIBUTING.md`](../CONTRIBUTING.md) (adding a port, and the policy-as-code
> one-source-of-truth rule), the [`faq/`](faq/) directory.

---

## 1. What you keep vs what you rewrite

The core is hexagonal, and the boundary between reusable machinery and your governance
vertical is a physical module split with an enforced dependency direction (practices-audit
check A7). `domain/kernel.py` owns the vertical-neutral contracts and imports nothing from
`architecture_validator`, so you can import it without loading a line of intake-gate logic;
`domain/models.py` holds only the Rsk3 vertical and re-exports every kernel name.

| Layer | Where | For a new control framework |
|---|---|---|
| **Vertical-neutral machinery** | the `Citation` / `LlmRequest` / `LlmResponse` / `AuditEvent` / `EvalReport` / `Severity` / `AgentCard` types and the `StrEnum` vocabularies (all of `domain/kernel.py`), `domain/identity.py`, `domain/serialization.py` (`to_jsonable`), `domain/_grounded.py`, every port in `ports/`, the container wiring in `config.py` | keep untouched |
| **Policy (your numbers)** | `ALLOWED_REGIONS` in `domain/principles.py`, the maker-checker severity bands in `domain/hitl.py`, the per-principle checks in `domain/principles_eval.py`, the eval thresholds in `eval/rubrics/*.yaml` | change deliberately (see the note in section 4) |
| **Vertical (the ruleset itself)** | the C3 models (`Principle`, `ProjectSubmission`, `ValidationReport`, `PrincipleFinding`, `InjectedRequirement`) in `domain/models.py`, the principle definitions (`policies/principles.yaml`), the two rule surfaces (`domain/principles_eval.py` and `policies/*.rego`), `domain/prompts.py`, the local fixtures, and the eval golden set | rewrite for your framework |

If your product is another *governance / assurance* gate, most of the hexagon, the four
profiles, the deterministic-verdict pattern, the eval gate, and the Hrz7 human-review routing
transfer directly; you replace the principle definitions and the injection prompts, and
retune the policy numbers and the taxonomy.

## 2. Core-vs-adopter-owned files (so upstream merges stay mechanical)

Upstream keeps evolving these; avoid diverging from them so you can pull fixes cleanly:

- **Upstream-owned** (take our changes): the vertical-neutral machinery listed above,
  `ports/`, `tests/contract/`, the eval harness mechanics (`eval/run_eval.py`), CI
  workflows, and the hexagon wiring (`config.py` `Container`).
- **Adopter-owned** (yours; expect to edit): `config/settings.yaml` *values*, the principle
  definitions and both rule surfaces, the local reg-KB fixtures, `adapters/onprem/*`, UI
  theming / branding, the golden eval dataset, and `COMPLIANCE.md` jurisdiction rows.

Track upstream via git tags; rebase your adopter-owned
changes onto each release rather than merging `main` continuously.

## 3. The mechanical rebrand (one script)

`scripts/rename_fork.py` rewrites the package name (`architecture_validator`), the CLI entry point
(`architecture-validator`), the `ARCH_VALIDATOR_` env prefix, and the baked-in resource ids
(`architecture-validator`, the `architecture-validator` git / provider id) across the
tree in one pass. Preview first, then apply:

```bash
# Preview (writes nothing):
python scripts/rename_fork.py --package acme_arch_gate --cli acme-arch \
    --env-prefix ACME --resource acme-arch-gate --dry-run

# Apply:
python scripts/rename_fork.py --package acme_arch_gate --cli acme-arch \
    --env-prefix ACME --resource acme-arch-gate --yes

# Then recreate the environment (the distribution name changed) and prove it is green:
python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
make lint test eval
```

`--dist` defaults to the `--resource` value; pass it explicitly if your git id differs from
the resource stem. Add `--include-docs` to sweep Markdown prose too. The script deliberately
does NOT touch the human decisions below.

## 4. The human decisions (the script can't make these)

1. **Region / residency.** Set `ARCH_VALIDATOR_KMS_KEY` and, in tfvars, BOTH the Terraform
   `region` and `allowed_regions` (the residency allowlist the region is validated against)
   to your in-country region, and update `ALLOWED_REGIONS` in `domain/principles.py` so the
   P-03 check enforces *your* residency. The build defaults to `asia-southeast1` (MAS /
   Singapore). See [`docs/runbook.md`](runbook.md).
2. **Identity / IdP.** This repo owns no login flow: the `gcp` / `platform` profiles verify
   the IAP-injected assertion at the edge, `local` uses seeded dev personas, and `onprem` is
   a client IdP placeholder. Wire your issuer on the deployed service (auth configured ON
   the service, not in this code) and set `ARCH_VALIDATOR_IAP_AUDIENCE`. See
   [`docs/embedding-and-identity.md`](embedding-and-identity.md).
3. **The principle set (policy-as-code).** The 12 principles are defined in **three places
   kept in step**: the in-process check (`domain/principles_eval.py`), the Rego rule
   (`policies/principles.rego` / `policies/validate.rego`, decision path `arch/validate`),
   and the principle metadata (`policies/principles.yaml`). To adopt your own control
   framework you edit all three plus a test together; the one-source-of-truth rule in
   [`CONTRIBUTING.md`](../CONTRIBUTING.md) and the offline gate enforce that the OPA verdict
   and the fallback evaluator stay identical.
4. **Policy numbers.** Own the consequential numbers your compliance function sets:
   `ALLOWED_REGIONS` (`domain/principles.py`), the maker-checker severity bands
   (`domain/hitl.py`), and the eval thresholds (`eval/rubrics/*.yaml`). These are
   module-level today rather than a `policy:` settings section (practices-audit check B4);
   change them deliberately and add a test that pins your values. The defaults are a
   reference, not your policy.
5. **Reference data is fictional.** The local reg-KB corpus and every fixture
   (`tests/fixtures/sample_projects.py`, `eval/datasets/`) use obviously-fake project names.
   Replace them with your own synthetic data. **Do not run against real project designs
   without your own security and model-risk sign-off.**
6. **Eval golden set.** Rebuild `eval/datasets/` and the rubrics for your framework: a fork
   inherits a green gate that measures the WRONG ruleset until you do. The gate structure and
   the strict `safety >= 0.99` metric are generic; the golden cases are yours.
7. **Deployment posture.** Review the Dockerfile (digest-pinned base, non-root uid 10001),
   `infra/terraform/` (Org Policy, CMEK, VPC-SC, locked WORM logging), and the
   loopback-by-default binding before you expose anything.

## 5. Do not duplicate the platform

This repo is one system in a catalog of composable GRC systems. Several concerns it
*touches* are owned by sibling platform services, and you should integrate rather than
rebuild them (see [`docs/faq/features-faq.md`](faq/features-faq.md) for the full map). The
`platform` profile's adapters are already thin HTTP clients to them:

- **Rsk1** compliance assistant / reg-KB: consumed via `remote_knowledge` (`/ask`) to ground
  findings and injected requirements.
- **Control-mapping evidence packs**: consumed via `remote_control_mapping` for control coverage,
  served by the Rsk1 compliance assistant's control-mapping module.
- **Residency / region-violation findings**: served in-process by this repo's own residency
  scanner; the `platform` profile can point `remote_residency` at an external scanner instead.
- **Hrz3** agent registry: this agent publishes its A2A AgentCard for discovery.
- **Hrz4** AI-quality / model-risk gate: owns promotion (bundle `rsk3-architecture-validator`);
  the offline eval gate mirrors its thresholds.
- **Hrz5** observability + immutable WORM audit: audit events and trace spans go to it.
- **Hrz7** human-review / maker-checker console: every `requires_human_review` escalation is
  routed to it over the shared `review-kit` (rule R8); you wire your endpoint, you do
  not re-implement the console.

The guardrail gateway (Hrz1) is **not** integrated: Rsk3 processes project metadata, not
customer PII, so there is no runtime redactor to place behind a guardrail port.

## 6. Adoption checklist

- [ ] Ran `scripts/rename_fork.py`, recreated the venv, `make lint test eval` green.
- [ ] Set region + Terraform tfvars + `ALLOWED_REGIONS` to your in-country region.
- [ ] Wired your IdP audience on the deployed service (this repo owns no login flow).
- [ ] Replaced the 12-principle set with your framework across all three rule surfaces plus a test.
- [ ] Owned the policy numbers (`ALLOWED_REGIONS`, severity bands, eval thresholds) with your compliance function.
- [ ] Replaced the local reg-KB corpus and every synthetic fixture.
- [ ] Rebuilt the eval golden set + rubrics for your framework.
- [ ] Reviewed the deploy posture (Dockerfile, Terraform, bind address).
- [ ] Wired your Hrz7 human-review endpoint and decided which sibling services you integrate vs stub.
- [ ] Recorded your baseline upstream tag so you can take future fixes.
