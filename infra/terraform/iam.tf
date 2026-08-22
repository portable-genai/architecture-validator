# iam.tf — Least-privilege service identities for C3 (P-09, defense in depth / zero trust).
#
# General Principle map:
#   P-09 (least privilege + distinct identities): the validator app, the OPA policy service
#         and Cloud Build each run as their OWN service account with only the roles they
#         need — no shared, broad identity.
#   P-07 (auditability): the app SA can write the audit log and emit traces, nothing more.

# The validator application's runtime identity (Cloud Run / Agent Runtime).
resource "google_service_account" "app" {
  account_id   = "arch-validator-app"
  display_name = "C3 Architecture Validator app (least privilege)"
}

# Write audit logs to the WORM bucket (P-07).
resource "google_project_iam_member" "app_log_writer" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.app.email}"
}

# Emit Cloud Trace spans (content capture OFF; P-07).
resource "google_project_iam_member" "app_trace_agent" {
  project = var.project_id
  role    = "roles/cloudtrace.agent"
  member  = "serviceAccount:${google_service_account.app.email}"
}

# Call Gemini on the Agent Platform (remediation drafting) — user, not admin.
resource "google_project_iam_member" "app_aiplatform_user" {
  project = var.project_id
  role    = "roles/aiplatform.user"
  member  = "serviceAccount:${google_service_account.app.email}"
}

# Query File Search for grounding context — viewer only.
resource "google_project_iam_member" "app_discoveryengine_viewer" {
  project = var.project_id
  role    = "roles/discoveryengine.viewer"
  member  = "serviceAccount:${google_service_account.app.email}"
}

# Allow the app to invoke the internal OPA Cloud Run service (and nothing more).
resource "google_cloud_run_v2_service_iam_member" "app_invokes_opa" {
  name     = google_cloud_run_v2_service.opa.name
  location = google_cloud_run_v2_service.opa.location
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.app.email}"
}

# ------------------------------ Agent Runtime ------------------------------- #
# A distinct identity for the Agent Runtime (reasoningEngine), separate from the
# serving app SA (P-09).
resource "google_service_account" "agent_runtime" {
  account_id   = "arch-validator-agent-runtime"
  display_name = "C3 Architecture Validator Agent Runtime (reasoningEngine)"
}

resource "google_project_iam_member" "agent_runtime" {
  for_each = toset([
    "roles/aiplatform.user",   # Gemini reasoning
    "roles/cloudasset.viewer", # read the live estate for --project scans
    "roles/logging.logWriter", # write audit events to the WORM sink
    "roles/cloudtrace.agent",  # OpenTelemetry spans (content OFF)
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.agent_runtime.email}"
}
