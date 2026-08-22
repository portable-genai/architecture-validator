# Portability FAQ

For architecture, cloud-governance, and exit-planning teams. The claim this repo makes is
"no vendor lock-in, demonstrably" (General Principle P-02 / P-12), and it is designed to be
*shown*, not asserted. Cross-references: [`ARCHITECTURE.md`](../../ARCHITECTURE.md),
[`docs/onprem-migration.md`](../onprem-migration.md), [`docs/runbook.md`](../runbook.md).

### What does "portable" actually mean here?

That *where* the stack runs is a configuration choice, not a rewrite. The pure-domain core
speaks only to `typing.Protocol` **ports**; four **adapter families** implement them, and
`config/settings.yaml` binds one adapter per port per profile. Setting
`ARCH_VALIDATOR_PROFILE` (or `profile:` in the settings) rebinds the entire stack, and no
`domain/` code changes across any profile. This is the same guarantee the validator
*checks* other projects for (rule_p_02, rule_p_12), applied to itself.

### How does the profile switch work?

- `local`: a WORKING offline stack (SQLite FTS5 reg-KB, a deterministic schema-driven LLM,
  the in-process principle evaluator as the policy engine, an append-only SQLite audit).
  **No Google Cloud SDK, no API key, no emulators.** The default for dev / test / CI.
- `gcp`: real managed services (OPA on Cloud Run, File Search, Gemini, Cloud Logging WORM,
  Cloud Trace, Gen AI evals). All `google-*` imports are lazy.
- `platform`: thin httpx clients delegating to the sibling de-risking and
  horizontal-platform services.
- `onprem`: placeholder stubs that still satisfy every Protocol and construct with a single
  `Settings` arg (the sovereign-exit target); a primary CLI command exits **2** by design.

The contract tests prove it: `tests/contract/test_port_parity.py` shows both the `local`
(working) and `onprem` (fail-fast) families construct and satisfy every port with no cloud
SDK installed, and `tests/contract/test_behavioral_parity.py` proves `local == platform`
boundary parity for the real httpx delegates and that the full `ValidationService` pipeline
runs under `local` and fails fast under `onprem` on a profile change alone.

### How do I prove the profile swap without cloud access?

Run the offline gate: `pytest -m 'not integration' -q` exercises the contract tests above
with `google` absent. You can also run the pipeline end to end offline:
`ARCH_VALIDATOR_PROFILE=local architecture-validator validate eval/datasets/sample_submission.json`
produces a real report (exit 0), and the same command under
`ARCH_VALIDATOR_PROFILE=onprem` exits 2 with the migration message. **Note (check F3, a
known gap):** there is not yet a single `scripts/portability_demo.py` whose exit code gates
the whole profile-swap / parity / audit story; today those claims are proven by the
contract tests and the CLI behaviour above, not one script.

### How does policy-as-code stay portable?

The 12 principles are a Rego bundle (`policies/*.rego`, decision path `arch/validate`)
evaluated by an OPA REST service on the managed profile, and an **in-process deterministic
evaluator** (`domain/principles_eval.py`) that produces the identical verdicts. The `local`
and `onprem` profiles use the in-process evaluator, so the whole policy engine runs with no
OPA service at all; on the managed profile, an OPA outage falls back to it too (P-10). The
rego rule and the Python rule are one source of truth kept in step by a contract rule
(see [`CONTRIBUTING.md`](../../CONTRIBUTING.md)).

### How do we get our data out?

The `local` audit store is a hash chain over canonical JSON with a JSONL export/restore path
(`hex_service_kit.audit.HashChainedAuditLog`, `verify_chain()` exposed), and every domain
artifact serialises via `to_jsonable` (`domain/serialization.py`). The exit story for the
audit trail is "copy the JSONL file and re-verify the chain", not "migrate a product".

### Is on-prem / sovereign deployment real or aspirational?

The `onprem` adapters are deliberate fail-fast placeholders (they raise
`NotImplementedError`) that nonetheless satisfy every Protocol and construct with a single
`Settings` arg, so the *interface contract* for a sovereign migration is proven and enforced
by CI today. The actual on-prem implementations are the migration work, scoped in
[`docs/onprem-migration.md`](../onprem-migration.md). This repo is **not** the sovereign-exit
*planner* (that is the sibling **Rgc9 operational-resilience mapping** system's concentration
and exit planning: APRA CPS 230, MAS / HKMA outsourcing); this repo is one of the systems
whose exit that planner reasons about, and it
is the gate that *checks* other projects have a documented exit (rule_p_12).

### Does residency compromise portability?

No: residency is a deploy-time pin (the region, an Org Policy resource-location allowlist,
CMEK, VPC-SC), and portability is the ability to change *where* the stack runs by
configuration. They are orthogonal. The region is pinned `asia-southeast1` and validated to
fail fast; a second region is a tfvars change, not a fork. Residency enforcement also has a
CI-gate face, the region-violation scanner this repo runs in-process, which the `platform`
profile can instead delegate to a remote scanner via `remote_residency`.
