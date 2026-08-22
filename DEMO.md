# Demo guide - Rsk3 Architecture, Requirements & Residency Validator

Step-by-step scripts for demoing Rsk3 two ways (plus the residency CI gate in
§2.5):

- **Demo A - Policy-as-code intake gate, offline** (the headline flow): two synthetic
  project submissions go through the gate. A customer-facing onboarding bot is **BLOCKED**
  (multiple principle FAILs, maker-checker review raised, one non-functional requirement
  injected per unmet principle); a grounded internal policy assistant **CLEARS** intake
  (every principle satisfied, nothing to inject). Runs **fully offline** (no cloud, no API
  key) under the `local` profile.
- **Demo B - The same gate on the managed GCP stack**: the FastAPI service running under
  the `gcp` profile in `asia-southeast1`, validating a submission via the REST endpoint,
  with the Next.js console on `:3000` talking to the API on `:8088`.

> The synthetic submissions are **fictional**. Do not treat the bundled KB snippets as the
> real regulatory instruments, and run nothing against production data without your own
> legal, security and model-risk sign-off.

---

## 0. Prerequisites

| Need | Demo A (local) | Demo B (GCP) | Notes |
|------|:--:|:--:|-------|
| `git` | yes | yes | clone the repo |
| **Python 3.12+** | yes | yes | the package pins `>=3.12` |
| Node.js 18+ and npm | for the UI / console | for the UI | only if you show the browser console |
| **Playwright** (`pip install playwright` + `playwright install chromium`) | for the guided walkthrough | no | Demo A's presenter walkthrough only; never a core dep |
| A GCP project + `gcloud` | no | yes | billing enabled; `asia-southeast1` available |
| Terraform | no | yes | provisions VPC-SC, CMEK, WORM logging, OPA on Cloud Run |
| Cloud KMS key (regional) | no | yes | CMEK; set `ARCH_VALIDATOR_KMS_KEY` |

Install/setup references (read these once):

- Quickstart and the `local` profile end to end -> [README "Run locally"](README.md#run-locally-the-local-profile-end-to-end-offline)
- HTTP surface (`/validate`, `/principles`, `/healthz`, agent card) -> [README "HTTP surface"](README.md#http-surface)
- The demo scripts -> [`scripts/README.md`](scripts/README.md)
- The UI console -> [`ui/README.md`](ui/README.md)
- Terraform infra -> [`infra/terraform/README.md`](infra/terraform/README.md)
- Config (`${ENV_VAR}` resolved at load) -> [`config/settings.yaml`](config/settings.yaml)

---

## 1. Common setup (both demos)

```bash
git clone https://github.com/portable-genai/architecture-validator.git
cd architecture-validator

python3.12 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"          # core + dev tooling (NO google-cloud-* packages)

# Sanity check the offline stack before presenting:
export ARCH_VALIDATOR_PROFILE=local
make lint test                   # ruff + mypy + pytest (all local, no cloud)
```

---

## 2. Demo A - Policy-as-code intake gate (local, offline)

The gate uses an in-process `local` stack (SQLite FTS5 reg-KB + deterministic LLM), so it
needs **no Google Cloud and no API key** - ideal for a laptop demo. Four ways to present
it, in order of polish.

### 2.1 Guided, presenter-controlled walkthrough (recommended)

A real browser opens; the script narrates each step and **waits for you to press Enter**
before performing it, so you control the pace. (One-time: `pip install playwright &&
playwright install chromium`.)

```bash
# Terminal 1 - the live demo server (http://localhost:8092)
source .venv/bin/activate
PYTHONPATH=src:tests ARCH_VALIDATOR_PROFILE=local python scripts/arch_demo_server.py

# Terminal 2 - the guided walkthrough (a Chrome window opens)
source .venv/bin/activate
python scripts/arch_demo_playwright.py
```

You'll step through, pressing Enter each time:

1. **Gate ready** - two synthetic submissions queued; nothing validated yet.
2. **Onboarding bot - BLOCKED** - PII fine-tuning in `us-central1` with almost no controls:
   **8 principle FAILs** (P-01, P-02, P-03, P-05, P-06, P-08, P-09, P-12), the maker-checker
   review flag, and one injected requirement per unmet principle.
3. **Policy assistant - CLEARS intake** - Singapore region, no PII, RAG over governed docs,
   eval gate, maker-checker, CMEK, VPC-SC, exit plan: every principle satisfied, nothing to
   inject.

**What to point at on screen:** the PASS/FAIL verdict banner and the HUMAN REVIEW flag, the
per-principle findings (status pill + severity + the `rule_id` that produced it), the
citation chips (`CROSS P-0x` provenance back to the principle), and the injected-requirements
panel shrinking to a green "nothing to inject" on the clean case. Full options (`SLOWMO_MS`,
`HEADLESS`, `CHROME_PATH`, ...) are in [`scripts/README.md`](scripts/README.md).

To narrate over the **real Next.js console** instead of the demo server, set
`DEMO_URL=http://localhost:3000` (with §2.2's `make run-ui` + `make run-api` running).

### 2.2 Manual, click-through (no Playwright)

Either drive the demo server yourself, or click through the real console:

```bash
# Option A - the live demo server, drive it in any browser
PYTHONPATH=src:tests ARCH_VALIDATOR_PROFILE=local python scripts/arch_demo_server.py   # http://localhost:8092
```

Open `http://localhost:8092` and click **Next** to validate each submission, **Restart** to
reset. Same three steps as above.

```bash
# Option B - the real console against the local API
make run-api PROFILE=local        # FastAPI on :8088, profile=local
make run-ui                       # Next.js console on http://localhost:3000
```

Open `http://localhost:3000`. Paste a submission into the form (or use the prefilled one)
and click validate; the console renders exactly what `POST /validate` returns. The two
synthetic submissions live in `tests/fixtures/sample_projects.py`; the blocked one is also
`eval/datasets/sample_submission.json`.

### 2.3 Static artifacts (slides / screenshots)

Generate the audit-first pages and JSON without a browser:

```bash
PYTHONPATH=src:tests ARCH_VALIDATOR_PROFILE=local python scripts/arch_demo.py arch_demo.json        # prints the per-case summary
PYTHONPATH=src:tests ARCH_VALIDATOR_PROFILE=local python scripts/render_arch_ui.py arch_demo.json ./out
# -> ./out/arch-case-blocked.html, arch-case-clean.html, arch-index.html
```

Or in one step (writes to `demo_out/`):

```bash
make demo
```

### 2.4 One-shot via the CLI (quick variant)

If you only want a single cited verdict in the terminal (not the browser flow):

```bash
export ARCH_VALIDATOR_PROFILE=local
architecture-validator validate eval/datasets/sample_submission.json    # the blocked onboarding bot
architecture-validator principles                                       # list the 12 General Principles
# or, equivalently:  make seed-local
```

### 2.5 Residency CI gate (offline, the in-repo scanner)

The residency scanner runs the same way, fully offline. The file-based scan is pure stdlib,
so it needs no cloud and no API key and drops straight into a pipeline (exit 0 clean, 1 on a
gating violation):

```bash
export ARCH_VALIDATOR_PROFILE=local

# Scan a Terraform plan JSON (the primary CI-gate path). Either console script works:
residency-validator scan --plan tests/fixtures/sample_plan.json   # preserved CI-gate entry point
architecture-validator scan --plan tests/fixtures/sample_plan.json        # same gate on the primary CLI

# Show the active residency policy (allowed regions, required controls, gate severity):
architecture-validator policy

# The live-scope scan runs offline too (a seeded synthetic estate; exit 1 on FAIL):
architecture-validator scan --project projects/demo-sg
```

Point at the PASS/FAIL verdict and exit code, the per-resource violations (each with its
`rule_id`, found region, and a citation back to P-01 / P-03 / P-10 and the in-country
regulator), and the fact that this is the same scan `POST /validate` consults in-process for
residency context.

---

## 3. Demo B - The intake gate on the managed GCP stack

Shows the same domain and gate running against **real managed services** in
`asia-southeast1` (Gemini, File Search KB, OPA on Cloud Run, CMEK, VPC-SC, WORM audit).

### 3.1 GCP setup

```bash
source .venv/bin/activate
pip install -e ".[gcp,dev]"                 # adds google-adk, google-genai, discoveryengine, ...

export GOOGLE_CLOUD_PROJECT=your-sg-project
export ARCH_VALIDATOR_PROFILE=gcp
export ARCH_VALIDATOR_KMS_KEY="projects/.../locations/asia-southeast1/keyRings/.../cryptoKeys/..."
gcloud auth application-default login
```

### 3.2 Provision infra (one-time)

```bash
make tf-plan          # review the plan - the WORM logging lock is IRREVERSIBLE
cd infra/terraform && terraform apply && cd ../..
# Export the outputs the app reads (see infra/terraform/README.md):
export ARCH_VALIDATOR_KMS_KEY="$(terraform -chdir=infra/terraform output -raw cmek_key)"
export ARCH_VALIDATOR_OPA_URL="$(terraform -chdir=infra/terraform output -raw opa_service_url)"
```

Region is pinned and validated to `asia-southeast1` (P-03); the terraform refuses other
regions. Details in [`infra/terraform/README.md`](infra/terraform/README.md).

### 3.3 Run and show

```bash
make run-api PROFILE=gcp          # FastAPI on :8088, profile=gcp
```

Then demo any surface ([README "HTTP surface"](README.md#http-surface)):

```bash
# REST - validate a submission through the intake gate.
# No "actor" in the body: identity is verified server-side. In the local profile the
# audit actor is the default seeded persona (or pass -H 'X-Dev-Persona: auditor' to pick one).
curl -s localhost:8088/validate -H 'content-type: application/json' -d '{
  "submission": {
    "id": "proj-risky-002",
    "name": "Customer-facing GenAI onboarding bot on public cloud",
    "description": "Customer onboarding assistant, fine-tuned on historical chats, in us-central1.",
    "requirements": "Handle KYC onboarding chats; fine-tune on past customer conversations.",
    "declared_region": "us-central1",
    "declared_controls": ["audit_logging"],
    "uses_pii": true,
    "uses_fine_tuning": true,
    "has_exit_plan": false
  }
}' | python -m json.tool

# The 12 General Principles, health, the local dev personas, and the A2A agent card
curl -s localhost:8088/principles | python -m json.tool
curl -s localhost:8088/healthz
curl -s localhost:8088/v1/personas | python -m json.tool
curl -s localhost:8088/.well-known/agent-card.json | python -m json.tool

# Residency capability: scan a Terraform plan through the same service, and read the policy.
curl -s localhost:8088/scan -H 'content-type: application/json' \
  -d '{"target": "tests/fixtures/sample_plan.json"}' | python -m json.tool
curl -s localhost:8088/policy | python -m json.tool
```

Or the browser console (talks to the API on `:8088`) - see [`ui/README.md`](ui/README.md):

```bash
make run-ui           # http://localhost:3000  (set NEXT_PUBLIC_API_BASE if the API is elsewhere)
```

**What to highlight:** a FAIL verdict is a normal `200` carrying `passed=false` and
`requires_human_review=true` (maker-checker, P-06) - not an HTTP error; every finding and
injected requirement carries a **citation** back to the principle (and, where relevant, a
KB instrument); everything stays in `asia-southeast1` with CMEK + VPC-SC.

---

## 4. Talking points

- **Policy-as-code at intake.** The 12 General Principles (P-01..P-12) are evaluated as
  code; the gate emits one finding per principle, so a reviewer can always trace why a
  project passed or was blocked.
- **The system does the verdict deterministically.** Principle evaluation is a pure
  function (replayable by an auditor); the LLM only drafts remediation and injected-
  requirement prose. The offline `local` profile produces the same verdict as `gcp`.
- **It does not just say no - it injects what's missing.** Every unmet principle yields a
  concrete non-functional requirement to add before intake proceeds.
- **A FAIL is a first-class artifact.** A blocked submission returns a full cited report
  marked human-review, never a 500.
- **No vendor lock-in (P-02 in action).** Switching from the GCP managed stack to the
  offline `local` stack is a one-line profile change; the domain is untouched.

---

## 5. Troubleshooting and cleanup

| Symptom | Fix |
|---------|-----|
| `python3.12: command not found` | Install Python 3.12+; the package pins `>=3.12`. |
| `ModuleNotFoundError: fixtures` | Run from the repo root with `PYTHONPATH=src:tests` (the scripts use the test fixtures). |
| Playwright "executable doesn't exist" | `playwright install chromium`, or set `CHROME_PATH=/path/to/chrome`. |
| No display for the headed walkthrough | Use §2.2 (manual browser) on a machine with a display, or `HEADLESS=1 DEMO_AUTO=1 python scripts/arch_demo_playwright.py` to self-run. |
| "Cannot reach the demo server" | Start §2.1 Terminal 1 first; or set `DEMO_URL` if you changed `--port`. |
| Port 8092 / 8088 in use | `python scripts/arch_demo_server.py --port 9000` (then `DEMO_URL=http://127.0.0.1:9000`); API port via `make run-api API_PORT=...`. |
| Console shows "backend down" | Start the API (`make run-api PROFILE=local`); check `NEXT_PUBLIC_API_BASE` in `ui/.env.local` points at `:8088`. |
| `NotImplementedError` from a CLI command | You're on `ARCH_VALIDATOR_PROFILE=onprem` (fail-fast placeholders). Use `local` (Demo A) or `gcp` (Demo B). |
| GCP region / VPC-SC errors | Region is pinned to `asia-southeast1` (P-03); see [`infra/terraform/README.md`](infra/terraform/README.md). |

**Stop / clean up:** Ctrl-C the demo server and `make run-api`. For GCP, scale the Cloud Run
service to zero or remove the app service account's model-access role - the audit trail
remains intact. `make clean` removes local caches and the `demo_out/` artifacts.
