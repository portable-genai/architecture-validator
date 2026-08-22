# artifact_registry.tf — CMEK-encrypted image repo for the OPA policy service + the app.
#
# General Principle map:
#   P-08 (eval-gated promotion): images are built by Cloud Build (cloudbuild.tf) only after
#         the eval gate passes, then pushed here; Cloud Run pulls from this repo.
#   P-09 (CMEK explicit): the repository is CMEK-encrypted (artifactregistry SA binding in
#         kms.tf). P-03: the repo is regional (asia-southeast1).

resource "google_artifact_registry_repository" "images" {
  provider      = google
  location      = var.region # asia-southeast1 (P-03)
  repository_id = "architecture-validator"
  description   = "OPA policy service + validator app images (CMEK, in-region)."
  format        = "DOCKER"

  kms_key_name = google_kms_crypto_key.validator.id

  depends_on = [
    google_project_service.required,
    google_kms_crypto_key_iam_member.artifactregistry,
  ]
}
