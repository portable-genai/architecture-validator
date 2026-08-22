# SPEC: Rsk3 Architecture, Requirements & Residency Validator

Documentation authority is declared in [`docs/doc-authority.md`](docs/doc-authority.md).

Authoritative build spec for `architecture_validator`. The repo is a faithful ports-and-adapters
clone of the Rsk1 pattern with the Rsk3 domain (policy-as-code intake gate) substituted. It
also carries an in-repo residency / IaC scanner family, so this one service is a single
policy-as-code gate over both project designs and cloud posture.

## 1. What it is

Rsk3 is the policy-as-code gate at project intake. Given a `ProjectSubmission`, it validates
the project against the 12 General Principles (P-01..P-12), cross-checks the regulatory
knowledge base, and auto-injects the missing non-functional requirements so a project
cannot start non-compliant. It is the system rule **R6** points to ("any new project SHOULD
pass Rsk3 at intake"). It handles project metadata and design docs, not customer/PII data, so
it carries no Hrz1 Guardrail dependency.

Beside the design-time architecture checks it runs a **residency / IaC scanner**. Given a
Terraform plan JSON (`terraform show -json`), a directory of
`.tf` files, or a live GCP scope (Cloud Asset Inventory + Security Command Center), the
scanner emits a `ResidencyScan` with a PASS/FAIL verdict over region and residency violations
(disallowed region, global / multi-region endpoint, missing regional CMEK, public egress, no
VPC-SC perimeter). The detector is deterministic and pure-stdlib on the file path, so it drops
into a pipeline as a CI gate that exits non-zero on FAIL. The scanner also handles
infrastructure config, not customer PII, so it too carries no Hrz1 Guardrail dependency. The
same gate is what `POST /validate` consults in-process for residency context.

- Catalog identity: Rsk3 · group `rsk` · priority P1 · buyer Architecture Review Board / Risk (also owns the residency / IaC scanner)
- Package `architecture_validator`; primary CLI `architecture-validator` (with `validate`, `scan`, `policy`, `principles`, ...); the `residency-validator scan` console script is the CI-gate entry point; service port 8088
- Profile env var `ARCH_VALIDATOR_PROFILE` (gcp | local | platform | onprem; dev/tests/CI set local, prod sets gcp, both explicitly). Unset is a THIRD state, not a chosen `local`: the adapter family still falls back to the SDK-free `local` one, but every security decision treats "nobody chose" as its own input, so the CORS dev-origin fallback is off and the no-auth seeded personas refuse to serve. An unknown or mis-capitalised value is refused outright. `RESIDENCY_VALIDATOR_*` variables are not read.

### Deployment profiles

| Profile | Backends | Google Cloud SDK | Use |
| --- | --- | --- | --- |
| `gcp` | OPA on Cloud Run, File Search, Gemini, Cloud Logging WORM, Cloud Trace, Gen AI eval, A2A registry, MCP | required (`[gcp]` extra), imports lazy | production (set `ARCH_VALIDATOR_PROFILE=gcp` explicitly) |
| `local` | SQLite **FTS5** reg-KB, deterministic schema-driven LLM, in-process principle evaluator, append-only SQLite audit, no-op tracer, offline eval gate, in-process Rsk2/Rsk4/registry/catalog | none on the default path | a WORKING offline laptop run; dev/tests/CI default |
| `platform` | thin `httpx` clients to sibling services (Rsk1/Rsk2/Rsk4/Hrz3/Hrz5) | none | the agentic mesh |
| `onprem` | fail-fast placeholders (raise `NotImplementedError`) | none | Google Distributed Cloud migration target |

The `local` profile runs the whole intake pipeline with no Google Cloud, no API key and no
running emulators by default; the reg-KB self-seeds a tiny synthetic corpus into SQLite FTS5
so a validation is grounded out of the box. Optional Google emulators are auto-detected and
opt-in (set the standard `*_EMULATOR_HOST` env var and install the `[gcp]` extra); the google
client is imported lazily, only on that branch. There is no emulator for File Search, Gemini,
OPA or the eval service, so those stay on the SDK-free workaround.

## 2. Locked decisions

- **Region** pinned to `asia-southeast1` (Singapore) for residency. No global default.
- **Domain core is pure stdlib** (`src/architecture_validator/domain`): frozen dataclasses, enums,
  pure services that take explicit port instances. No google-cloud / ADK / FastAPI / httpx
  / pydantic imports in the domain.
- **Kernel / vertical boundary:** shared evidence, audit, evaluation, identity, citation and
  severity contracts are the reusable kernel. `ProjectSubmission`, the 12-principle evaluator,
  requirement injection and residency scan models are the Rsk3 vertical. A fork preserves the
  kernel contracts and replaces the vertical rules/artifacts. The split is **physical, and the
  dependency direction is enforced**: `domain/kernel.py` owns the neutral contracts and imports
  nothing from `architecture_validator`, `domain/identity.py` is the identity half of the kernel (a thin
  re-export of `hex_service_kit.identity`, likewise free of intra-package imports), and
  `domain/models.py` holds only the vertical while re-exporting every kernel name so no import
  site changed. `tests/unit/test_kernel_boundary.py` proves it by execution: a fresh interpreter
  imports the kernel and asserts `architecture_validator.domain.models` never enters `sys.modules`.
- **One construction convention**: every adapter is `Adapter(settings: Settings)`.
- **GCP imports are lazy** in every `adapters/gcp/*` (inside methods / under `TYPE_CHECKING`).
- **The verdict is the policy engine's, not the model's.** The LLM only drafts the
  human-facing requirement / rationale prose; PASS/FAIL/NEEDS_INFO is decided by the
  deterministic evaluator (or OPA), never by Gemini.
- **A FAIL is not an error.** The API returns a 200 ValidationReport with `passed=false`.

## 3. Pinned stack (mid-2026 GA)

- Python 3.12, `from __future__ import annotations`, ruff line-length 100, ruff select
  `["E","F","I","UP","B","SIM"]`, target py312, hatchling backend.
- The product is Gemini Enterprise Agent Platform; host `aiplatform.googleapis.com`.
- Models: reasoning `gemini-3.5-flash` (thinking=high), triage `gemini-3.1-flash-lite`.
  Unified SDK `google-genai`; ADK `google-adk==2.3.0`; A2A v1.0 + MCP 2025-11-25.
- Policy engine: **OPA** on Cloud Run evaluating the bundled rego (`src/architecture_validator/policies`).
  The OPA call uses `httpx` (a core dep); the rego bundle ships as data files.
- Grounding: **File Search** (Hrz2 Enterprise KB); reg-KB requirement text in practice via **Rsk1** `/ask`.
- Audit: Cloud Logging locked WORM bucket, retention 2557 days. Tracing: Cloud Trace via
  OpenTelemetry, message-content capture OFF. Eval: Gen AI evaluation service.
- `[gcp]` extra holds all google-cloud-* / google-adk / google-genai; core deps are
  framework-light (pydantic, pyyaml, httpx, tenacity, typer, fastapi, uvicorn, python-dateutil).

## 4. Adapter convention

`config/settings.yaml` binds every port to `gcp` / `local` / `platform` (where applicable) /
`onprem` dotted paths. The `Container` picks the active profile (falling back to `gcp`).
Module paths + class names there are the build contract;
`tests/contract/test_port_parity.py` reads them and verifies both the `local` (working) and
`onprem` (fail-fast) families.

Ports (10): `policy_engine`, `knowledge_base`, `control_mapping`, `residency`, `llm`,
`audit`, `tracer`, `evaluation`, `registry`, `tool_catalog`.

The `residency` port is backed IN-PROCESS by default: `LocalScanResidencyAdapter` runs the
residency scan service directly, so a validation grounds its residency context with
no network hop. The `RemoteResidencyAdapter` (HTTP to a remote scanner via `RSK_RESIDENCY_URL`)
is bound only under the `platform` profile, for a split deployment. Either way the
call is best-effort (a scanner failure never aborts a validation). The scanner itself resolves
resources through the residency-scan ports (an IaC scanner over Cloud Asset Inventory + SCC on
`gcp`, a seeded in-process estate on `local`) plus the pure-stdlib `pipelines/terraform` parser
for the file / plan path.

The `local` family (`adapters/local/*`) is a real, deterministic, seedable offline stack;
every adapter is SDK-free and constructs with a single `Settings`, and the whole pipeline
runs end to end with no Google Cloud. The `onprem` family are fail-fast placeholder migration
targets: they construct with a single `Settings`, structurally satisfy the Protocol, and
raise `NotImplementedError` from each method (tracer is the exception, it is a no-op so the
pipeline runs without observability).

## 5. The validation pipeline

`ValidationService.validate(submission, actor) -> ValidationReport`:

The `actor` is the audit subject. It is NOT taken from the request body: the API layer
resolves a server-verified `Principal` via the `IdentityPort` (`api/security.py`) and passes
`actor=principal.actor`. See `docs/embedding-and-identity.md`.

1. `tracer.span("validate")`.
2. load the 12 principles → `policy_engine.evaluate(submission, principles)` → findings.
   - On `PolicyEvaluationError` (OPA down) fall back to `domain/principles_eval.evaluate_all`.
3. for each FAIL / NEEDS_INFO finding: `knowledge_base.retrieve(context)` for KB citations,
   plus best-effort `control_mapping.coverage` (Rsk2) and `residency.findings` (Rsk4).
4. `RequirementInjectionService.inject(...)`: the LLM drafts one InjectedRequirement per
   unmet principle (grounded in the finding + KB citations); falls back to the deterministic
   remediation text if the LLM is unavailable.
5. assemble the report: `passed = no FAIL`; `requires_human_review` per the ReviewPolicy
   (any FAIL, or any open finding at HIGH/CRITICAL severity); maker-checker, P-06.
6. `audit.record(verdict summary)`: WORM, no customer PII.

The deterministic per-principle checks live in `domain/principles_eval.py` and back the
`local` policy-engine adapter, the OPA rego bundle (`policies/*.rego`), and the offline eval
gate, so the local and managed verdicts agree by construction.

## 6. HTTP contracts

### Endpoints this repo defines (consumed by the UI / CLI / peers)

- `POST /validate` `{submission:{...}}` → `ValidationReport` (no body `actor`: identity is
  server-verified; in `local` the persona is chosen by the `X-Dev-Persona` header)
  - `ValidationReport` = `{submission, findings:[PrincipleFinding], injected_requirements:[InjectedRequirement], passed, requires_human_review, generated_at}`
  - `PrincipleFinding` = `{principle_id, status, rule_id, evidence, severity, remediation, citations:[Citation]}`
  - `InjectedRequirement` = `{id, principle_id, requirement_text, rationale, severity, citations:[Citation]}`
- `GET /principles` → `{principles:[Principle]}`
- `POST /scan` `{target|plan_json|resources}` → `ResidencyScan` (no body `actor`: identity is
  server-verified as on `/validate`)
  - `ResidencyScan` = `{target, resources_scanned, passed, requires_human_review, generated_at, verdict:ScanVerdict, violations:[ResidencyViolation]}`
  - `ScanVerdict` = `{passed, gate_severity, total_violations, exit_code, counts:[{severity,count}]}`
  - `ResidencyViolation` = `{resource_address, resource_type, kind, found_region, allowed_regions, severity, rule_id, remediation, evidence, citations:[Citation]}`
- `GET /policy` → `ResidencyPolicy` `{allowed_regions, required_controls, gate_severity}`
- `GET /healthz` → `{status, profile, region}`
- `GET /v1/personas` → seeded dev personas (local profile only; `[]` in secure profiles)
- `GET /.well-known/agent-card.json` → AgentCard `{name, description, url, version, provider, skills:[{id,name,description}]}`. The card advertises BOTH the validate skills (`validate_project`, `inject_requirements`, `list_principles`) and the scan skills (`scan_iac`, `scan_project`, `explain_violation`).

JSON field names mirror the domain dataclasses (enums as `.value` strings) via
`domain/serialization.to_jsonable`.

### Sibling contracts this repo consumes

- **Rsk1 compliance** (`RSK_COMPLIANCE_URL`, :8080): `POST /ask` for reg-KB requirement text.
- **Control-mapping** (`RSK_CONTROL_MAPPING_URL`, :8080): `POST /evidence-pack` (best-effort), served by the Rsk1 compliance assistant's control-mapping module.
- **Residency scanner**: called in-process by default (the residency scan service); under the
  `platform` profile only, a remote scanner at `RSK_RESIDENCY_URL` (:8088) is consulted over
  `POST /scan` (best-effort).
- **Hrz3 registry** (`HRZ_REGISTRY_URL`, :8083) and **Hrz5 observability** (`HRZ_OBSERVABILITY_URL`, :8085).

## 7. Coding standards

- Full type hints; `from __future__ import annotations` in every module.
- Domain stays pure; wiring layers (`api`, `cli`, `agent`) keep heavy imports lazy and are
  import-safe with no GCP SDK installed.
- The hard gate (must be green): `ruff check src tests`, `ruff format --check src tests`,
  `pytest -m 'not integration' -q`; `mypy src` and `python eval/run_eval.py` SHOULD pass.
- End to end under `local`: `ARCH_VALIDATOR_PROFILE=local architecture-validator validate
  eval/datasets/sample_submission.json` returns a real cited `ValidationReport` (exit 0)
  with no Google Cloud SDK. Under `onprem` the same command exits 2 with the migration
  message; the contract test proves both families satisfy the Protocols.
- The residency CI gate is pure-stdlib and profile-independent on the file path:
  `residency-validator scan --plan plan.json` (or `architecture-validator scan --plan plan.json`)
  parses the Terraform plan and exits 0 (clean), 1 (a gating violation), 2 (the profile
  cannot satisfy a live `--project` scan), or 3 (runtime error). A live `--project` scan runs
  offline under `local` (seeded estate) and exits 2 under `onprem`.
