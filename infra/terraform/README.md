# `architecture-validator` infrastructure (Terraform): asia-southeast1

Concrete, single-region (`asia-southeast1`, Singapore) infrastructure for the `architecture-validator`. Only `project_id` and a few genuinely per-tenant
values are variables; every service identifier, location and resource name is concrete, so
the stack is a faithful description of the sovereign deploy rather than a parameterised
template.

## What it provisions

| File | Resource | Principle |
| --- | --- | --- |
| `apis.tf` | Enables aiplatform, discoveryengine, run, cloudbuild, artifactregistry, logging, cloudtrace, cloudkms, accesscontextmanager, assuredworkloads | P-01 minimal surface |
| `kms.tf` | Regional CMEK key ring + key; explicit per-service-agent bindings | P-09, P-03 |
| `artifact_registry.tf` | CMEK-encrypted Docker repo for the OPA + app images | P-08, P-09 |
| `cloud_run.tf` | The **OPA policy service** (internal ingress, dedicated SA) | P-01, P-03 |
| `cloudbuild.tf` | The **intake-gate** build: lint + tests + the `model-quality-gate`, then build/push the OPA image | P-08, P-02 |
| `logging_worm.tf` | Locked WORM audit bucket (~7y) + sink + data-access audit config | P-07, P-03, P-09 |
| `iam.tf` | Least-privilege service identities for app / OPA / build | P-09 |
| `vpc_sc.tf` | VPC Service Controls perimeter around the AI / policy APIs | P-01, P-03 |
| `org_policy.tf` | `gcp.resourceLocations` pinned to SG; deny external VM IPs | P-03, P-01 |

## Usage

```bash
cd infra/terraform
cp terraform.tfvars.example terraform.tfvars   # fill in project_id, org_id, access_policy_id
terraform init
terraform plan
terraform apply
```

After apply, set `ARCH_VALIDATOR_OPA_URL` to the `opa_service_url` output so the validator's
`OpaPolicyAdapter` posts to the managed policy engine; if it is unreachable the validator
falls back to the in-process deterministic evaluator (P-10).

## Irreversible actions

- `logging_worm.tf` sets `locked = true` on the audit bucket. This **cannot be undone** and
  prevents reducing retention or deleting the bucket for the full window. Confirm
  `retention_days` before `apply`.
- `kms.tf` sets `prevent_destroy` on the CMEK key; a destroyed key strands all encrypted data.

## Notes

- The rego bundle the OPA service evaluates lives in `src/architecture_validator/policies` and is the
  managed-path twin of `src/architecture_validator/domain/principles_eval.py`. The Cloud Build step
  bakes it into the OPA image, so the two paths cannot drift (P-02).
- Do not run `terraform` against a production org without reviewing the WORM lock and the
  Org Policy location constraint.
