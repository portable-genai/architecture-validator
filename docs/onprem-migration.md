# On-prem migration (exit / portability): General Principles P-02, P-12

The whole point of the ports-and-adapters shape is that `architecture-validator`'s exit story is
**demonstrable, not aspirational**. Switching from the managed GCP stack to a sovereign /
on-premise stack is a one-line profile change (`ARCH_VALIDATOR_PROFILE=onprem`) plus
filling in the adapter bodies. The domain core, the services, the API, the CLI, the UI and
the agent wiring do not change. This is the same no-vendor-lock-in property `architecture-validator` enforces
on every other project at intake, applied to itself.

## What "onprem" gives you today

Setting `ARCH_VALIDATOR_PROFILE=onprem` rebinds every port to a placeholder adapter under
`src/architecture_validator/adapters/onprem/`. Those adapters:

- construct cleanly with a single `Settings` and **no Google Cloud SDK installed** (the
  contract test proves it),
- structurally satisfy the same `@runtime_checkable` `Protocol` as the managed GCP adapter,
  and
- raise `NotImplementedError` from every method that must not silently no-op (policy,
  knowledge base, control mapping, residency, LLM, audit, evaluation, registry, tool
  catalog, identity, review routing). The policy adapter raises rather than waving a
  submission through: an unimplemented intake gate must never silently pass a project. The
  one exception is the tracer, whose `span`/`record_token_usage` are safe no-ops so the
  pipeline still runs with tracing absent.

This is what makes the contract tests (`tests/contract/test_port_parity.py` and
`test_behavioral_parity.py`) meaningful: they import and construct each on-prem placeholder
and assert interface parity with the managed and local families. So a primary CLI command
under the `onprem` profile exits `2` with the migration message, by design.

## The migration checklist

To run `architecture-validator` on a sovereign / on-premise platform, implement these adapter bodies (the only
files that change):

| Port | On-prem file | What to implement |
|------|--------------|-------------------|
| `PolicyEnginePort` | `onprem/policy.py` | A self-hosted OPA (or equivalent) evaluating the rego bundle; can reuse `domain/principles_eval.py` unchanged |
| `KnowledgeBasePort` | `onprem/knowledge.py` | An on-prem governed reg-KB retrieval store returning page-cited passages |
| `ControlMappingClientPort` | `onprem/control_mapping.py` | The `compliance-advisory` control-mapping service on-prem (best-effort coverage) |
| `ResidencyClientPort` | `onprem/residency.py` | The in-process seam to the residency scan service (best-effort residency findings for a validation). In-process by default; only the `platform` profile targets a remote scanner |
| `IaCScannerPort` | `onprem/scanner.py` | The live-scope source for the residency scanner (the on-prem equivalent of Cloud Asset Inventory + SCC). The file-based `pipelines/terraform` parser is pure stdlib and needs no on-prem adapter |
| `LLMPort` | `onprem/llm.py` | An on-prem model-serving endpoint for requirement-prose drafting and classification |
| `AuditSinkPort` | `onprem/audit.py` | An on-prem immutable (WORM) audit store |
| `EvaluationGatePort` | `onprem/evaluation.py` | An on-prem eval backend (the `model-quality-gate` / P-08 promotion gate) |
| `AgentRegistryPort` | `onprem/registry.py` | An on-prem agent catalog (register / get / list) |
| `ToolCatalogPort` | `onprem/tool_catalog.py` | An on-prem MCP tool catalog |
| `IdentityPort` | `onprem/identity.py` | An on-prem IdP assertion verifier resolving the server-side `Principal` |
| `ReviewRouterPort` | `onprem/review_router.py` | An on-prem route to the `human-review-console` human-review / maker-checker console (rule R8) |
| `ObservabilityTracerPort` | `onprem/tracer.py` | Already a safe no-op; wire an on-prem tracer only if you want spans |

Nothing under `src/architecture_validator/domain/` changes. The validation pipeline, the
requirement-injection logic, the deterministic principle evaluator, the citation mapping,
the serialization and the prompts are all profile-agnostic. The rego bundle in
`src/architecture_validator/policies/` is data, portable to any OPA host.

## Why this matters for a regulated buyer

An Architecture Review Board cannot mandate an intake gate it cannot itself exit. Because
the domain depends only on Protocols, the regulator-facing properties (cited findings,
auto-injected NFRs, always-on human review when a principle FAILs, WORM audit) survive a
platform change unchanged, and the migration is a bounded, testable piece of work rather
than a rewrite. That is the reversibility (P-02) and portability (P-12) `architecture-validator` checks for on
every submission, held to on its own build.
