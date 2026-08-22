# Runbook: Rsk3 Architecture, Requirements & Residency Validator

Operational notes for deploying and running Rsk3 (the policy-as-code intake gate, plus the
residency / IaC scanner) on the Gemini Enterprise Agent Platform in
`asia-southeast1` (Singapore). This is a reference build; adapt it to your own
change-management and model-risk sign-off before any live use.

## 1. Deploy

```bash
# 1. Provision infra (review the plan; the WORM bucket lock is irreversible when
#    locked = true, the default).
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # set project_id, org_id; pick a scenario (see below)
terraform init -input=false && terraform plan
terraform apply

# 2. Export the outputs the app runtime needs (config/settings.yaml resolves them).
export ARCH_VALIDATOR_OPA_URL="$(terraform output -raw opa_service_url)"
export ARCH_VALIDATOR_KMS_KEY="$(terraform output -raw cmek_key)"
export GOOGLE_CLOUD_PROJECT=your-sg-project

# 3. Install the managed stack and run the API.
pip install -e ".[gcp,dev]"          # or: make install-gcp
export ARCH_VALIDATOR_PROFILE=gcp
gcloud auth application-default login
make run-api          # FastAPI on :8088 (override API_PORT / API_HOST)
```

The OPA policy service (which evaluates the rego bundle in `src/architecture_validator/policies/`)
is a regional Cloud Run service stood up by `cloud_run.tf`; its image is built from the
baked-in bundle (`opa_image`, defaults to the in-repo Artifact Registry path). Point the
app at it with `ARCH_VALIDATOR_OPA_URL` (the `opa_service_url` output).

Prerequisites and the two deploy paths: the default posture expects an Access Context
Manager policy id (`access_policy_id`) and `org_id` for Org Policy and the VPC-SC
perimeter. For a quick project-scoped evaluation WITHOUT the org-level perimeter, set
`enable_vpc_sc = false` in `terraform.tfvars` (not compliant for production). See
`infra/terraform/terraform.tfvars.example` for the variable set.

The ADK agent is deployed to Agent Runtime separately via the Agent Platform SDK; record
the resulting `reasoningEngine` resource name in `ARCH_VALIDATOR_AGENT_ENGINE` (or
`settings.agent_engine.resource_name`).

Rsk3 has a UI: a Next.js console (`ui/`) that renders the `ValidationReport`. Run it with
`make run-ui` (dev server). Set `ARCH_VALIDATOR_FRAME_ANCESTORS` (backend) and
`NEXT_PUBLIC_FRAME_ANCESTORS` (UI) together when embedding it into a host app; see
`docs/embedding-and-identity.md`.

## 2. Region selection and fail-fast

The region defaults to `asia-southeast1` in `config/settings.yaml` and in Terraform, where
`region` is a deploy-time input validated against `allowed_regions`, the residency allowlist:
an apply against a region outside that allowlist fails immediately at `terraform plan`, before
anything is created (P-03). The allowlist also defaults to Singapore alone, so deploying
elsewhere means setting both variables, which is the deliberate residency review. The OPA Cloud Run service, the CMEK
key, the WORM bucket and the VPC-SC perimeter are all created in that region, and an Org
Policy resource-location allowlist (`org_policy.tf`) hard-restricts resource creation to
it. Confirm the `region` output equals your chosen region.

## 3. Key rotation

The CMEK crypto key (`kms.tf`) rotates every 90 days (`rotation_period = 7776000s`).
Rotation is transparent to the app; no restart is needed. The key has
`prevent_destroy = true`, so it cannot be torn down while data depends on it.

## 4. Retention and the WORM lock

The audit bucket retention is `retention_days` (default 2557, ~7 years, validated to be at
least that) and the bucket is locked by default (`locked = true` in `logging_worm.tf`),
which is **irreversible**. To trial without locking, set `locked = false` (not compliant
for production). Only verdict summaries, never customer PII, are ever written to the audit
log: Rsk3 processes project metadata, so it has no Hrz1 Guardrail dependency.

## 5. Profiles and the offline default

`ARCH_VALIDATOR_PROFILE` selects the adapter family with no domain change: `local`
(a WORKING SDK-free offline stack, dev/test/CI), `gcp` (managed services),
`platform` (thin HTTP clients to sibling Rsk1/Rsk2/Rsk4/Hrz3/Hrz5 services), and `onprem`
(fail-fast migration placeholders; see `docs/onprem-migration.md`).

**Set it explicitly, in every environment.** The variable has three states, and an unset one
is not a chosen `local`. Unset still binds the SDK-free `local` adapter family, because the
alternative is importing cloud SDKs that are not installed, but no security decision reads it
as consent: the CORS localhost fallback stays off, and the seeded dev personas (an
unauthenticated grant of the arch-approver entitlement) refuse to construct, so protected
routes answer `401`. A value nothing binds, including the capitalisation typo `Local`, is
refused outright rather than silently selecting a posture. Production deploys therefore set
`ARCH_VALIDATOR_PROFILE=gcp` and dev/demo runs set `ARCH_VALIDATOR_PROFILE=local`.

## 6. Kill switch

To stop serving without tearing down state: scale the OPA / app Cloud Run service to zero,
or remove the app service account's model-access binding. The audit trail and validation
history remain intact.

## 7. Common failures

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| CLI exits `2` with a migration message | `ARCH_VALIDATOR_PROFILE=onprem` with placeholder adapters | Set `ARCH_VALIDATOR_PROFILE=gcp` or `local` (or implement the on-prem adapter) |
| `PolicyEvaluationError`, verdict still produced | OPA on Cloud Run unreachable | Expected: the service falls back to the in-process `domain/principles_eval.py` (P-10). Fix `ARCH_VALIDATOR_OPA_URL` to restore rego evaluation |
| `401` on `/validate` | `ARCH_VALIDATOR_IAP_AUDIENCE` unset in `gcp`/`platform` | Set the IAP audience; the identity adapter refuses to verify without it |
| `401` on every route, `/v1/personas` empty, on an offline run | `ARCH_VALIDATOR_PROFILE` unset, so the local profile was inherited rather than chosen | Set `ARCH_VALIDATOR_PROFILE=local` deliberately (see section 5); the seeded personas refuse to serve an unconsented run |
| Empty grounding on an unmet principle | reg-KB / File Search returned no passages | Confirm the reg corpus is ingested; on `local` the SQLite FTS5 KB self-seeds |
| VPC-SC denies the apply | Runner identity outside the perimeter | Apply with `enable_vpc_sc = false`, add the identity, re-apply true |
| `residency-validator scan` exits `2` on `--project` | `ARCH_VALIDATOR_PROFILE=onprem`, or `gcp` without an asset scope | Use `local` / `gcp`; set `ARCH_VALIDATOR_ASSET_SCOPE`. The file scan (`--plan` / `--dir`) still runs under any profile |
| Live scan returns no resources | `ARCH_VALIDATOR_ASSET_SCOPE` / `ARCH_VALIDATOR_SCC_ORG` unset or wrong scope | Set the asset scope (`projects/ID` \| `folders/ID` \| `organizations/ID`) and the SCC org; confirm the Cloud Asset Inventory feed exists |

## 8. Residency scan and the CI gate

The residency scanner runs on the same service (`POST /scan`, `GET /policy`) and as
a CLI gate. The file-based scan (`residency-validator scan --plan plan.json` or
`architecture-validator scan --plan plan.json`) is pure stdlib and runs under any profile with no
cloud SDK, exiting non-zero on a gating violation (0 clean, 1 gating violation, 2 profile
cannot satisfy the command, 3 runtime error), so it drops straight into a pipeline before
`terraform apply`. Wire it as the residency CI gate ahead of the intake gate.

The live-scope scan (`--project`) reads Cloud Asset Inventory + Security Command Center: set
`ARCH_VALIDATOR_ASSET_SCOPE` (`projects/ID` | `folders/ID` | `organizations/ID`) and
`ARCH_VALIDATOR_SCC_ORG`. The Cloud Asset Inventory feed and the `agent_runtime` service
account are provisioned by Terraform (`cloud_asset_inventory.tf`). The scanner is the
detection gate; the Org Policy resource-location allowlist (`google_org_policy_policy`, the
`resource_locations` constraint) is the prevention boundary, so keep the residency policy's
`allowed_regions` (the `residency_policy:` block of `config/settings.yaml`) in lockstep with
it. Only a scan summary (target, verdict, counts, citations), never resource attribute
values, is written to the audit log.
