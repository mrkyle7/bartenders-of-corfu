# Bartenders of Corfu — GCP infrastructure.
# Cloud Run service with Supabase (external), Artifact Registry, Secret Manager.

variable "env" {
  type        = string
  default     = "prod"
  description = "Environment"
}

variable "region" {
  type        = string
  default     = "us-east1"
  description = "GCP Region"
}

variable "app_name" {
  type        = string
  default     = "bartenders"
  description = "Application name"
}

variable "project_name" {
  type        = string
  default     = "bartenders-464918"
  description = "GCP Project name"
}

variable "bucket_name" {
  type        = string
  default     = "bartenders-data"
  description = "Bucket name"
}

variable "domain_name" {
  type        = string
  default     = "cheetahmoongames.com"
  description = "Custom domain served by the app"
}

variable "ci_service_account" {
  type        = string
  default     = "github-terraform@bartenders-464918.iam.gserviceaccount.com"
  description = "GitHub Actions service account used by CI. Granted permission to add Secret Manager versions and deploy Cloud Run."
}

variable "github_repo" {
  type        = string
  default     = "mrkyle7/bartenders-of-corfu"
  description = "GitHub repository (owner/repo) allowed to authenticate via Workload Identity Federation."
}

# ---------------------------------------------------------------------------
# APIs
# ---------------------------------------------------------------------------

resource "google_project_service" "secretmanager" {
  project            = var.project_name
  service            = "secretmanager.googleapis.com"
  disable_on_destroy = false
}

resource "google_project_service" "cloudrun" {
  project            = var.project_name
  service            = "run.googleapis.com"
  disable_on_destroy = false
}

# ---------------------------------------------------------------------------
# Workload Identity Federation — lets GitHub Actions authenticate as the
# CI service account via OIDC (no long-lived keys).
# ---------------------------------------------------------------------------

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.project_name
  workload_identity_pool_id = "github-pool"
  display_name              = "GitHub Actions Pool"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.project_name
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-provider"
  display_name                       = "GitHub Actions OIDC Provider"
  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
  }
  attribute_condition = "attribute.repository == '${var.github_repo}'"
  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

# Let GitHub Actions assume the CI service account via WIF
resource "google_service_account_iam_member" "wif_github_terraform" {
  service_account_id = "projects/${var.project_name}/serviceAccounts/${var.ci_service_account}"
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}

# ---------------------------------------------------------------------------
# CI service account permissions
# ---------------------------------------------------------------------------

resource "google_project_iam_member" "ci_run_developer" {
  project = var.project_name
  role    = "roles/run.developer"
  member  = "serviceAccount:${var.ci_service_account}"
}

resource "google_project_iam_member" "ci_storage_admin" {
  project = var.project_name
  role    = "roles/storage.admin"
  member  = "serviceAccount:${var.ci_service_account}"
}

resource "google_artifact_registry_repository_iam_member" "ci_pushes_images" {
  project    = var.project_name
  location   = google_artifact_registry_repository.docker_us.location
  repository = google_artifact_registry_repository.docker_us.name
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${var.ci_service_account}"
}

# ---------------------------------------------------------------------------
# Shared infrastructure
# ---------------------------------------------------------------------------

resource "google_artifact_registry_repository" "docker_us" {
  project       = var.project_name
  location      = var.region
  repository_id = "docker-us"
  description   = "Docker images for bartenders"
  format        = "DOCKER"

  labels = {
    env    = var.env
    region = var.region
    app    = var.app_name
  }

  cleanup_policies {
    id     = "delete-untagged"
    action = "DELETE"
    condition {
      tag_state  = "UNTAGGED"
      older_than = "604800s" # 7 days
    }
  }

  cleanup_policies {
    id     = "delete-old-tagged"
    action = "DELETE"
    condition {
      tag_state  = "TAGGED"
      older_than = "2592000s" # 30 days
    }
  }

  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 10
    }
  }
}

resource "google_storage_bucket" "data" {
  name     = var.bucket_name
  location = var.region
  project  = var.project_name

  labels = {
    env       = var.env
    region    = var.region
    app       = var.app_name
    sensitive = "false"
  }
}

# ---------------------------------------------------------------------------
# Cloud Run
# ---------------------------------------------------------------------------

resource "google_service_account" "bartenders_run" {
  project      = var.project_name
  account_id   = "bartenders-run"
  display_name = "Cloud Run service account for bartenders"
}

resource "google_service_account_iam_member" "ci_impersonates_run_sa" {
  service_account_id = google_service_account.bartenders_run.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.ci_service_account}"
}

# --- Secrets ------------------------------------------------------------------

resource "google_secret_manager_secret" "supabase_url" {
  project   = var.project_name
  secret_id = "supabase-url"
  replication {
    auto {}
  }
  depends_on = [google_project_service.secretmanager]
}

resource "google_secret_manager_secret" "supabase_key" {
  project   = var.project_name
  secret_id = "supabase-key"
  replication {
    auto {}
  }
  depends_on = [google_project_service.secretmanager]
}

# Cloud Run reads secrets at container start
resource "google_secret_manager_secret_iam_member" "run_reads_url" {
  project   = var.project_name
  secret_id = google_secret_manager_secret.supabase_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.bartenders_run.email}"
}

resource "google_secret_manager_secret_iam_member" "run_reads_key" {
  project   = var.project_name
  secret_id = google_secret_manager_secret.supabase_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.bartenders_run.email}"
}

# CI reads current value (to diff) and adds new versions on deploy
resource "google_secret_manager_secret_iam_member" "ci_reads_url" {
  project   = var.project_name
  secret_id = google_secret_manager_secret.supabase_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.ci_service_account}"
}

resource "google_secret_manager_secret_iam_member" "ci_reads_key" {
  project   = var.project_name
  secret_id = google_secret_manager_secret.supabase_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.ci_service_account}"
}

resource "google_secret_manager_secret_iam_member" "ci_writes_url" {
  project   = var.project_name
  secret_id = google_secret_manager_secret.supabase_url.secret_id
  role      = "roles/secretmanager.secretVersionAdder"
  member    = "serviceAccount:${var.ci_service_account}"
}

resource "google_secret_manager_secret_iam_member" "ci_writes_key" {
  project   = var.project_name
  secret_id = google_secret_manager_secret.supabase_key.secret_id
  role      = "roles/secretmanager.secretVersionAdder"
  member    = "serviceAccount:${var.ci_service_account}"
}

# --- Service ------------------------------------------------------------------

resource "google_artifact_registry_repository_iam_member" "run_pulls_images" {
  project    = var.project_name
  location   = google_artifact_registry_repository.docker_us.location
  repository = google_artifact_registry_repository.docker_us.name
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:${google_service_account.bartenders_run.email}"
}

resource "google_cloud_run_v2_service" "bartenders" {
  project             = var.project_name
  name                = "bartenders"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  scaling {
    min_instance_count = 0
  }

  template {
    service_account = google_service_account.bartenders_run.email

    scaling {
      min_instance_count = 0
      max_instance_count = 3
    }

    containers {
      image = "us-docker.pkg.dev/cloudrun/container/hello"

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        cpu_idle = true
      }

      env {
        name = "SUPABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.supabase_url.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "SUPABASE_KEY"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.supabase_key.secret_id
            version = "latest"
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].containers[0].image,
      scaling,
      client,
      client_version,
    ]
  }

  depends_on = [
    google_project_service.cloudrun,
    google_secret_manager_secret_iam_member.run_reads_url,
    google_secret_manager_secret_iam_member.run_reads_key,
    google_artifact_registry_repository_iam_member.run_pulls_images,
  ]
}

resource "google_cloud_run_service_iam_member" "public" {
  project  = google_cloud_run_v2_service.bartenders.project
  location = google_cloud_run_v2_service.bartenders.location
  service  = google_cloud_run_v2_service.bartenders.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# --- Domain + DNS -------------------------------------------------------------

resource "google_cloud_run_domain_mapping" "cheetahmoongames" {
  project  = var.project_name
  location = var.region
  name     = var.domain_name

  metadata {
    namespace = var.project_name
  }

  spec {
    route_name = google_cloud_run_v2_service.bartenders.name
  }
}

resource "google_dns_record_set" "cheetahmoongames_a" {
  project      = var.project_name
  name         = "${var.domain_name}."
  type         = "A"
  ttl          = 300
  managed_zone = "cheetahmoongames-com"

  rrdatas = distinct([
    for r in google_cloud_run_domain_mapping.cheetahmoongames.status[0].resource_records :
    r.rrdata if r.type == "A"
  ])
}

resource "google_dns_record_set" "cheetahmoongames_aaaa" {
  project      = var.project_name
  name         = "${var.domain_name}."
  type         = "AAAA"
  ttl          = 300
  managed_zone = "cheetahmoongames-com"

  rrdatas = distinct([
    for r in google_cloud_run_domain_mapping.cheetahmoongames.status[0].resource_records :
    r.rrdata if r.type == "AAAA"
  ])
}

# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------

output "cloud_run_url" {
  value       = google_cloud_run_v2_service.bartenders.uri
  description = "Direct Cloud Run URL"
}

output "cloud_run_service_account" {
  value       = google_service_account.bartenders_run.email
  description = "Service account used by the Cloud Run service"
}
