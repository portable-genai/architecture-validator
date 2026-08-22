# cloud_run.tf — The OPA policy service (the policy-as-code engine for the intake gate).
#
# General Principle map:
#   P-01 (no public egress): ingress is restricted to internal + the load balancer; the
#         service runs inside the VPC-SC perimeter (vpc_sc.tf) so the validator reaches it
#         privately. P-09: it runs as a dedicated least-privilege service account.
#   P-03 (residency): the service is regional (asia-southeast1). The rego bundle baked into
#         the image is the managed twin of domain/principles_eval.py.
#
# The validator's OpaPolicyAdapter POSTs to this service's /v1/data/arch/validate. If it is
# unreachable, the ValidationService falls back to the in-process evaluator (P-10).

resource "google_service_account" "opa" {
  account_id   = "arch-validator-opa"
  display_name = "C3 OPA policy service (least privilege)"
}

resource "google_cloud_run_v2_service" "opa" {
  name     = "architecture-validator-opa"
  location = var.region # asia-southeast1 (P-03)

  # Internal ingress only — no public egress to the policy engine (P-01).
  ingress = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    service_account = google_service_account.opa.email

    containers {
      # The OPA image bakes in src/architecture_validator/policies (the rego bundle). Built and
      # promoted by Cloud Build (cloudbuild.tf) after the eval gate passes (P-08).
      image = var.opa_image != "" ? var.opa_image : "${var.region}-docker.pkg.dev/${var.project_id}/architecture-validator/opa:latest"

      ports {
        container_port = 8181 # OPA REST default
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }
    }

    scaling {
      min_instance_count = 0
      max_instance_count = 4
    }
  }

  depends_on = [
    google_project_service.required,
    google_artifact_registry_repository.images,
  ]
}
