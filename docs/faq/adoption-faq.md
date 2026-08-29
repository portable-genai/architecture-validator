# Adoption FAQ

For an engineering lead forking this repo as their institution's base. The step-by-step is
[`docs/ADOPTING.md`](../ADOPTING.md); this answers the "will it hurt later?" questions.

### How do I rebrand it for my institution?

`scripts/rename_fork.py` rewrites the package name (`architecture_validator`), the CLI entry point
(`architecture-validator`), the `ARCH_VALIDATOR_` env prefix, and the baked-in resource ids in one
pass (preview with `--dry-run`, apply with `--yes`). Then recreate the venv,
`pip install -e ".[dev]"`, and run the gate. The script does the mechanical rename; the human
decisions (region, IdP, principle set, eval golden set, fixtures) are the checklist in
`ADOPTING.md`.

### If several banks fork this, how does each take upstream fixes?

Track upstream via **git tags** (semver). The repo declares a **core-vs-adopter-owned boundary** (ADOPTING section 2):
upstream owns `ports/`, `tests/contract/`, the eval harness mechanics, CI, and the hexagon
wiring (`config.py` `Container`); you own `config/settings.yaml` values, the principle
definitions and rego rules, fixtures, `adapters/onprem/*`, and the UI theming. Rebase your
adopter-owned changes onto each release rather than merging `main` continuously, so conflicts
stay in the files you were told to expect.

### How do I add a new outbound dependency (a new port)?

There is a fixed touch list, and the contract test fails loudly if you miss part of it
(`test_port_protocols_matches_settings_adapters` asserts set-equality between `PORT_PROTOCOLS`
and the settings `adapters:` map). Define the `@runtime_checkable` Protocol under `ports/`,
re-export it, implement one adapter per profile (at least `local` and `onprem`), bind all of
them in `config/settings.yaml`, add the port to `PORT_PROTOCOLS` in the parity test, and wire
it in `api/deps.py`. Full instructions in [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

### How do I change the principle checks without breaking the policy-as-code contract?

A principle is defined in **three places kept in step**: the in-process check
(`domain/principles_eval.py`), the Rego rule (`policies/principles.rego` /
`policies/validate.rego`), and the principle metadata (`policies/principles.yaml`). The
one-source-of-truth rule (`CONTRIBUTING.md`) requires you to change all three plus a test
together; the offline gate enforces it. This is what keeps the OPA verdict and the fallback
evaluator identical, so a fork cannot let them drift.

### How do I change the taxonomy (statuses, severities, regulators)?

The six wire vocabularies (`Regulator`, `Jurisdiction`, `ThinkingLevel`, `CheckStatus`,
`Severity`, `Decision`) are `StrEnum`s (via the shared `hex-service-kit` commons): members
**are** their wire values, and the engines are typed on `str`, so you extend a vocabulary
without editing engine code. The 12-principle set itself stays a deliberately closed
governance ruleset.

### How does the human-review routing behave in a fork?

Rule R8 routes any non-clean `ValidationReport` to the Hrz7 Human-Review and Maker-Checker
Console through the shared `review-kit` client (`adapters/*/review_router.py`). In a
fork, `local` enqueues to an in-memory outbox (offline), `gcp`/`platform` submit over S2S to
`HUMAN_REVIEW_URL`, and `onprem` is the fail-fast placeholder. You wire your Hrz7
endpoint; you do not re-implement the console.

### Does the CI run for my fork out of the box?

Yes. `ci.yaml` (`ARCH_VALIDATOR_PROFILE: local`) runs ruff + format + mypy + the test suite,
and `eval-gate.yaml` (`onprem`) runs the eval, both with **no cloud credentials and no org
secrets**. A fork's build is green immediately; you add secrets only when you wire the
`gcp`/`platform` profiles. Note the eval gate measures the *reference* principle set until you
rebuild the golden set for your framework, that is an explicit adoption step, not a silent
pass.

### What is not yet automated that I should know about?

Two known gaps (tracked in [`docs/practices-audit.md`](../practices-audit.md), not hidden):
there is no unattended demo self-test (a broken demo step would not fail CI, check F2) and no
single executable portability script (check F3); the profile-swap claims are proven by the
contract tests today. Both are on the backlog, not shipped as done.
