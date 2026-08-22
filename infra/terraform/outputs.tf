# outputs.tf — The handful of values the app deploy / operators need.

output "region" {
  description = "The pinned in-country region (P-03)."
  value       = var.region
}

output "cmek_key" {
  description = "Regional CMEK crypto key id used across the stack (P-09)."
  value       = google_kms_crypto_key.validator.id
}

output "worm_bucket" {
  description = "Locked WORM audit log bucket id (P-07)."
  value       = google_logging_project_bucket_config.worm_audit.id
}

output "opa_service_url" {
  description = "Internal URL of the OPA policy service (set ARCH_VALIDATOR_OPA_URL to this)."
  value       = google_cloud_run_v2_service.opa.uri
}

output "image_repo" {
  description = "Artifact Registry repo for the OPA / app images (P-08)."
  value       = google_artifact_registry_repository.images.id
}

output "app_service_account" {
  description = "Least-privilege runtime identity for the validator app (P-09)."
  value       = google_service_account.app.email
}
