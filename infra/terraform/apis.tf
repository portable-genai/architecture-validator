# apis.tf — Enable exactly the managed services C3 depends on.
#
# General Principle map:
#   P-01 (managed-first / minimal surface): only the services the pinned stack (SPEC §3)
#         actually uses are enabled — nothing speculative.
#   P-03 (residency): enabling these APIs is a prerequisite for the regional,
#         CMEK-protected resources defined in the sibling files.
#
# disable_on_destroy = false so a `terraform destroy` of this stack does not yank platform
# APIs out from under other workloads in a shared project.

locals {
  required_services = [
    "aiplatform.googleapis.com",           # Gemini Enterprise Agent Platform / Agent Runtime
    "discoveryengine.googleapis.com",      # File Search (governed RAG) for grounding context
    "cloudasset.googleapis.com",           # Cloud Asset Inventory — the live IaCScannerPort
    "securitycenter.googleapis.com",       # Security Command Center — residency findings enrichment
    "run.googleapis.com",                  # Cloud Run — the OPA policy service host
    "cloudbuild.googleapis.com",           # Cloud Build — the intake / OPA image build
    "artifactregistry.googleapis.com",     # Artifact Registry — OPA + app images
    "logging.googleapis.com",              # Cloud Logging (WORM locked bucket + audit)
    "cloudtrace.googleapis.com",           # Cloud Trace (OpenTelemetry spans)
    "cloudkms.googleapis.com",             # Regional CMEK key ring (P-09)
    "accesscontextmanager.googleapis.com", # VPC Service Controls perimeter (P-01/P-03)
    "assuredworkloads.googleapis.com",     # Assured Workloads (sovereignty controls, P-03)
    # Supporting services the above transitively require.
    "compute.googleapis.com",   # VPC
    "iam.googleapis.com",       # Service accounts / least-privilege IAM
    "orgpolicy.googleapis.com", # Org Policy residency constraints (P-03)
  ]
}

resource "google_project_service" "required" {
  for_each = toset(local.required_services)

  project            = var.project_id
  service            = each.value
  disable_on_destroy = false
}
