# cloud_asset_inventory.tf — the live scan source for the IaCScannerPort.
#
# Backs the in-repo residency scanner: names carry the architecture-validator prefix.
#
# General Principle map:
#   P-03 (residency monitoring): a Cloud Asset Inventory feed streams resource changes so
#         the validator can scan the live estate (scan --project) for residency violations,
#         not just pre-apply plans. The feed is the data source the gcp scanner adapter reads.
#   P-01 (least surface): the feed watches only the data-bearing asset types graded.
#
# verify: https://cloud.google.com/asset-inventory/docs/monitoring-asset-changes

resource "google_pubsub_topic" "asset_feed" {
  name    = "architecture-validator-asset-feed"
  project = var.project_id

  # CMEK on the feed topic (P-09) — explicit, does not cascade.
  kms_key_name = google_kms_crypto_key.validator.id

  depends_on = [
    google_project_service.required,
    google_kms_crypto_key_iam_member.pubsub,
  ]
}

resource "google_cloud_asset_project_feed" "residency" {
  project      = var.project_id
  feed_id      = "architecture-validator-residency-feed"
  content_type = "RESOURCE"

  # The data-bearing asset types whose region / residency the validator checks.
  asset_types = [
    "storage.googleapis.com/Bucket",
    "bigquery.googleapis.com/Dataset",
    "sqladmin.googleapis.com/Instance",
    "alloydb.googleapis.com/Cluster",
    "spanner.googleapis.com/Instance",
    "pubsub.googleapis.com/Topic",
  ]

  feed_output_config {
    pubsub_destination {
      topic = google_pubsub_topic.asset_feed.id
    }
  }

  depends_on = [google_project_service.required]
}
