# variables.tf — The only knobs. Everything else is a concrete in-region value.
#
# Per the build contract, ONLY project_id and a few genuinely per-tenant values (org /
# billing ids, the VPC-SC toggle, the deployed OPA image) are variables. All service
# identifiers, locations, and resource names are concrete.

variable "project_id" {
  description = "Target GCP project id (required). Single-tenant, Singapore-resident."
  type        = string
}

variable "allowed_regions" {
  description = <<-EOT
    Residency allowlist: the regions this deployment may be created in (P-03). The region is
    chosen at deploy time (var.region) and validated against this list to FAIL FAST, so an
    operator cannot accidentally deploy to an unvetted region. Extending this list is the
    deliberate residency review point: confirm the regional service availability and your
    residency obligations there first, and widen var.allowed_locations (the org-policy
    resource-location backstop) to match.
  EOT
  type        = list(string)
  default     = ["asia-southeast1"]

  validation {
    condition     = length(var.allowed_regions) > 0
    error_message = "allowed_regions must list at least one residency-approved region."
  }
}

variable "region" {
  description = <<-EOT
    Deployment region, SELECTED AT DEPLOY TIME. Keeps the Singapore default below but is
    overridable. Validated against var.allowed_regions so an unapproved region fails fast at
    `terraform plan` rather than deploying data out of jurisdiction (P-03).
  EOT
  type        = string
  default     = "asia-southeast1"

  validation {
    condition     = contains(var.allowed_regions, var.region)
    error_message = "region must be one of var.allowed_regions (residency allowlist). Add it there first if that region is approved for this workload (P-03)."
  }
}

variable "zone" {
  description = "Default zone within Singapore for zonal resources."
  type        = string
  default     = "asia-southeast1-a"
}

variable "retention_days" {
  description = "WORM audit-log retention in days. Default ~7 years. Lock is irreversible."
  type        = number
  default     = 2557 # ~7 years; mirrors config/settings.yaml logging.retention_days

  validation {
    condition     = var.retention_days >= 2557
    error_message = "Governance retention must be at least 2557 days (~7 years) (P-07)."
  }
}

variable "allowed_locations" {
  description = <<-EOT
    The in-country locations the gcp.resourceLocations org policy permits (P-03). Consumed
    by the google_org_policy_policy resource in org_policy.tf; the default is the
    Singapore-first posture (asia-southeast1, plus asia-southeast2).
  EOT
  type        = list(string)
  default = [
    "in:asia-southeast1-locations", # Singapore (default residency)
    "in:asia-southeast2-locations", # Jakarta
  ]
}

variable "github_repo" {
  description = <<-EOT
    GitHub "owner/name" the Cloud Build residency-gate trigger watches. The trigger runs
    `residency-validator scan --plan plan.json` on each PR and fails the build on a gating
    violation. Leave empty to skip creating the trigger.
  EOT
  type        = string
  default     = ""
}

variable "org_id" {
  description = "Organization id — required for Org Policy and Access Context Manager."
  type        = string
}

variable "billing_account" {
  description = "Billing account id (used by Assured Workloads / FinOps tagging)."
  type        = string
  default     = ""
}

variable "access_policy_id" {
  description = <<-EOT
    Existing Access Context Manager policy id (numeric, no prefix) for the org.
    Required when enable_vpc_sc = true; the service perimeter is created under it.
  EOT
  type        = string
  default     = ""
}

variable "vpc_network_name" {
  description = "Name of the VPC that hosts the private OPA service and platform endpoints."
  type        = string
  default     = "architecture-validator-vpc"
}

variable "enable_vpc_sc" {
  description = "Create the VPC Service Controls perimeter around the AI/policy APIs (P-01/P-03)."
  type        = bool
  default     = true
}

variable "opa_image" {
  description = <<-EOT
    Fully-qualified container image for the OPA policy service on Cloud Run, e.g.
    asia-southeast1-docker.pkg.dev/PROJECT/architecture-validator/opa:latest. The rego bundle in
    src/architecture_validator/policies is baked into this image at build time (P-08 build gate).
  EOT
  type        = string
  default     = ""
}

variable "resource_location_values" {
  description = <<-EOT
    Value groups for the gcp.resourceLocations Org Policy. Empty (the default) derives the
    strictest form from the deploy region: that region and its sub-locations, nothing else.

    Widen it ONLY where a service this stack genuinely needs has no presence at single-region
    granularity, and treat the width as the residency claim rather than as plumbing. Two
    services in this catalog force the question:

      * Agent Search serves `global`, `us` and `eu` and NO Cloud region at all.
      * Document AI serves the deploy region only once Google grants single-region access,
        and routes to the `us` multi-region until then.

    Move to the smallest value group that still describes ONE JURISDICTION -- `in:us-locations`
    keeps every resource inside the United States -- and state the residency claim at that
    granularity rather than pretending it is still single-region. NEVER list an individual
    foreign region to unblock one service: that turns a jurisdiction boundary into a list of
    exceptions nobody can reason about.

    NOT YET VERIFIED BY EXECUTION: whether a `global` Agent Search data store is subject to
    this constraint at all, or is exempt as a global resource. Confirm at first apply and
    record the answer rather than guessing; the failure mode if it IS subject is an apply
    error naming discoveryengine, which is the good kind of failure.
  EOT
  type        = list(string)
  default     = []

  validation {
    condition     = alltrue([for value in var.resource_location_values : startswith(value, "in:") || startswith(value, "is:")])
    error_message = "Each value must be an Org Policy location value group (in:...) or a literal location (is:...)."
  }
}
