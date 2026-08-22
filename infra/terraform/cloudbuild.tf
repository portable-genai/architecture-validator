# cloudbuild.tf — The intake-gate build trigger (eval-gated promotion of the OPA image).
#
# General Principle map:
#   P-08 (eval-gated promotion): the build runs `python eval/run_eval.py` (the A4 gate)
#         BEFORE building/pushing the OPA image, so a release that fails the eval gate is
#         never promoted. P-02: the rego bundle and the in-process evaluator are built from
#         one source tree, so the two paths cannot drift.
#
# The trigger is wired to the repo's main branch; the inline build runs lint+tests+eval,
# then builds and pushes the OPA image into the CMEK Artifact Registry repo.

resource "google_service_account" "cloudbuild" {
  account_id   = "arch-validator-build"
  display_name = "C3 Cloud Build (intake gate, least privilege)"
}

resource "google_artifact_registry_repository_iam_member" "build_push" {
  location   = google_artifact_registry_repository.images.location
  repository = google_artifact_registry_repository.images.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.cloudbuild.email}"
}

resource "google_cloudbuild_trigger" "intake_gate" {
  name            = "architecture-validator-intake-gate"
  location        = var.region # asia-southeast1 (P-03)
  description     = "Lint + tests + A4 eval gate, then build/push the OPA policy image."
  service_account = google_service_account.cloudbuild.id

  # Wire to your source repo connection; left as a manual/dispatch trigger by default.
  source_to_build {
    uri       = "https://github.com/portable-genai/architecture-validator"
    ref       = "refs/heads/main"
    repo_type = "GITHUB"
  }

  build {
    # 1) Lint + unit/contract tests on the onprem profile (no GCP SDK).
    step {
      id         = "test"
      name       = "python:3.12-slim"
      entrypoint = "bash"
      args = [
        "-c",
        "pip install -e '.[dev]' && ruff check src tests && pytest -m 'not integration' -q",
      ]
      env = ["ARCH_VALIDATOR_PROFILE=onprem"]
    }

    # 2) The A4 / P-08 eval gate — promotion blocked unless this passes.
    step {
      id         = "eval-gate"
      name       = "python:3.12-slim"
      entrypoint = "bash"
      args       = ["-c", "pip install -e '.[dev]' && python eval/run_eval.py"]
      env        = ["ARCH_VALIDATOR_PROFILE=onprem"]
    }

    # 3) Build + push the OPA image (rego bundle baked in) only after the gate is green.
    step {
      id   = "build-opa"
      name = "gcr.io/cloud-builders/docker"
      args = [
        "build",
        "-t",
        "${var.region}-docker.pkg.dev/${var.project_id}/architecture-validator/opa:latest",
        "-f",
        "infra/opa/Dockerfile",
        ".",
      ]
    }

    images = ["${var.region}-docker.pkg.dev/${var.project_id}/architecture-validator/opa:latest"]

    options {
      logging = "CLOUD_LOGGING_ONLY"
    }
  }

  depends_on = [google_project_service.required]
}

# --------------------------------------------------------------------------- #
# Residency CI gate for the in-repo residency scanner.
#
#   P-03 / P-01 (prevention at the pipeline): the trigger runs
#         `residency-validator scan --plan plan.json` on every pull request and FAILS the
#         build (non-zero exit) on a gating residency violation, so non-compliant infra
#         never reaches apply. The repo ships the `residency-validator` console script,
#         which is the command the trigger invokes.
#
# Reuses the existing arch-validator-build Cloud Build SA declared above; adds only the
# read roles the residency scan needs. Guarded by var.github_repo (empty => skip).
# --------------------------------------------------------------------------- #
resource "google_project_iam_member" "cloudbuild" {
  for_each = toset([
    "roles/cloudasset.viewer", # live --project scans read the asset inventory
    "roles/logging.logWriter", # write the scan audit event
    "roles/cloudtrace.agent",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.cloudbuild.email}"
}

resource "google_cloudbuild_trigger" "residency_gate" {
  count = var.github_repo == "" ? 0 : 1

  project         = var.project_id
  location        = var.region # asia-southeast1 (P-03)
  name            = "residency-gate"
  description     = "Fails the build on a data-residency violation."
  service_account = google_service_account.cloudbuild.id

  github {
    owner = split("/", var.github_repo)[0]
    name  = split("/", var.github_repo)[1]
    pull_request {
      branch = "^main$"
    }
  }

  build {
    step {
      id         = "residency-scan"
      name       = "python:3.12-slim"
      entrypoint = "bash"
      args = [
        "-c",
        join(" && ", [
          "pip install -e .",
          # The plan is produced by an earlier `terraform show -json > plan.json` step.
          "residency-validator scan --plan plan.json",
        ]),
      ]
    }
    options {
      logging = "CLOUD_LOGGING_ONLY"
    }
  }

  depends_on = [google_project_service.required]
}
