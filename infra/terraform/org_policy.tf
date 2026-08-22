# org_policy.tf — Residency / sovereignty Org Policy constraints (P-03, P-01, P-09).
#
# Declared with the `google_org_policy_policy` resource over four constraints:
# resource_locations, no_external_ip, uniform_bucket_access and restrict_cmek_projects.
# Allowed-region values come from var.allowed_locations, whose default is the
# Singapore-first posture (asia-southeast1).
#
# General Principle map:
#   P-03 (single in-country region): gcp.resourceLocations is constrained to the approved
#         in-country locations so a resource cannot be created outside them.
#   P-01 (private by default): restrict VM external IPs; require uniform bucket access.
#   P-09 (CMEK): require CMEK for the data-bearing services.
#
# Scoped to the project via google_org_policy_policy. To enforce org-wide, move parent
# to "organizations/${var.org_id}".
# verify: https://registry.terraform.io/providers/hashicorp/google/latest/docs/resources/org_policy_policy

# Master residency policy: only allow the in-country locations (the validator control).
resource "google_org_policy_policy" "resource_locations" {
  name   = "projects/${var.project_id}/policies/gcp.resourceLocations"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      values {
        # Confine resources to the allowed in-country locations (P-03).
        allowed_values = var.allowed_locations
      }
    }
  }

  depends_on = [google_project_service.required]
}

# Disable VM external IPs — keep the data plane private (P-01).
resource "google_org_policy_policy" "no_external_ip" {
  name   = "projects/${var.project_id}/policies/compute.vmExternalIpAccess"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      deny_all = "TRUE"
    }
  }

  depends_on = [google_project_service.required]
}

# Require uniform bucket-level access (no per-object ACL exfiltration paths) (P-01).
resource "google_org_policy_policy" "uniform_bucket_access" {
  name   = "projects/${var.project_id}/policies/storage.uniformBucketLevelAccess"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      enforce = "TRUE"
    }
  }

  depends_on = [google_project_service.required]
}

# Require CMEK for the data-bearing services (no Google-managed-key fallback) (P-09).
resource "google_org_policy_policy" "restrict_cmek_projects" {
  name   = "projects/${var.project_id}/policies/gcp.restrictNonCmekServices"
  parent = "projects/${var.project_id}"

  spec {
    rules {
      values {
        denied_values = [
          "bigquery.googleapis.com",
          "storage.googleapis.com",
          "logging.googleapis.com",
        ]
      }
    }
  }

  depends_on = [google_project_service.required]
}
