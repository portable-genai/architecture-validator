# Synthetic .tf fixture for the regex fallback parser test. Clearly fictional.

resource "google_storage_bucket" "kyc" {
  name                     = "acme-kyc-sg"
  location                 = "asia-southeast1"
  public_access_prevention = "enforced"
  service_perimeter        = "accessPolicies/123/servicePerimeters/sg"
  kms_key_name             = "projects/p/locations/asia-southeast1/keyRings/r/cryptoKeys/k"
}

resource "google_storage_bucket" "export" {
  name                     = "acme-export-us"
  location                 = "us-central1"
  public_access_prevention = "enforced"
  service_perimeter        = "accessPolicies/123/servicePerimeters/us"
  kms_key_name             = "projects/p/locations/us-central1/keyRings/r/cryptoKeys/k"
}

resource "google_sql_database_instance" "public" {
  region       = "asia-southeast1"
  kms_key_name = "projects/p/locations/asia-southeast1/keyRings/r/cryptoKeys/k"
  ipv4_enabled = true
}
