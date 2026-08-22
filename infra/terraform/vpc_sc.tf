# vpc_sc.tf — VPC Service Controls perimeter around the AI / policy APIs (P-01, P-03).
#
# General Principle map:
#   P-01 (no public egress): the managed-service APIs the validator uses are placed inside a
#         service perimeter so they are reachable only from within the perimeter (private),
#         never the public internet.
#   P-03 (residency): the perimeter is the enforcement boundary that keeps data and
#         processing in-country alongside the regional resources.
#
# Gated on var.enable_vpc_sc and a provided access_policy_id. Creating an Access Context
# Manager policy is an org-level, once-per-org action, so the policy id is an input.

resource "google_access_context_manager_service_perimeter" "validator" {
  count = var.enable_vpc_sc && var.access_policy_id != "" ? 1 : 0

  parent = "accessPolicies/${var.access_policy_id}"
  name   = "accessPolicies/${var.access_policy_id}/servicePerimeters/architecture_validator_sg"
  title  = "architecture-validator-sg-residency"

  status {
    resources = ["projects/${data.google_project.this.number}"]

    # The managed services the validator touches — confined to the perimeter (P-01).
    restricted_services = [
      "aiplatform.googleapis.com",
      "discoveryengine.googleapis.com",
      "run.googleapis.com",
      "artifactregistry.googleapis.com",
      "logging.googleapis.com",
      "cloudtrace.googleapis.com",
      "cloudkms.googleapis.com",
    ]

    vpc_accessible_services {
      enable_restriction = true
      allowed_services   = ["RESTRICTED-SERVICES"]
    }
  }

  depends_on = [google_project_service.required]
}
