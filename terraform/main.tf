# Bartenders of Corfu infrastructure.
#
# This config supports a phased migration from a single-VM k3s setup to
# Cloud Run. Two flags control the rollout:
#
#   enable_legacy_k3s = true   -> VM, k3s, ops-agent policy, firewall are created
#   dns_target        = "k3s"  -> apex DNS points to the VM
#                     = "cloudrun" -> apex DNS points to Cloud Run's managed IPs
#
# Recommended migration sequence:
#   1. Apply with defaults (legacy k3s on, DNS on k3s). Creates Cloud Run
#      resources alongside the existing VM. No user-visible change.
#   2. Add secret versions (gcloud secrets versions add ...) and deploy an
#      image (push + gcloud run deploy). Test via the *.run.app URL.
#   3. Set dns_target = "cloudrun" and apply. DNS switches to Cloud Run.
#      Managed cert provisions in 15-60 min. VM still running as fallback.
#   4. Once verified, set enable_legacy_k3s = false and apply. VM is
#      destroyed. Cloud Run is now the only backend.

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

variable "zone" {
  type        = string
  default     = "us-east1-d"
  description = "GCP Zone"
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

variable "enable_legacy_k3s" {
  type        = bool
  default     = true
  description = "When true, create and manage the legacy k3s VM infrastructure. Set to false after Cloud Run has been verified to tear down the VM."
}

variable "dns_target" {
  type        = string
  default     = "k3s"
  description = "Which backend the apex DNS A record should point at. 'k3s' = VM (legacy), 'cloudrun' = Cloud Run domain mapping."
  validation {
    condition     = contains(["k3s", "cloudrun"], var.dns_target)
    error_message = "dns_target must be either 'k3s' or 'cloudrun'."
  }
}

# ---------------------------------------------------------------------------
# APIs — enable before creating dependent resources.
# disable_on_destroy = false so `terraform destroy` doesn't tear down APIs
# (which could break other unrelated resources in the project).
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
# CI service account — project-level roles needed to run the deploy workflow.
# Scoped roles (e.g. secret version add, SA impersonation) are declared
# alongside the resources they apply to.
# ---------------------------------------------------------------------------

# Allows `gcloud run deploy` to update the Cloud Run service and traffic.
# run.developer is sufficient because terraform (not CI) creates the service;
# CI only updates revisions and traffic splits.
resource "google_project_iam_member" "ci_run_developer" {
  project = var.project_name
  role    = "roles/run.developer"
  member  = "serviceAccount:${var.ci_service_account}"
}

# ---------------------------------------------------------------------------
# Shared infrastructure (always managed)
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

resource "google_storage_bucket" "k3s-storage" {
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
# Cloud Run (new target)
# ---------------------------------------------------------------------------

# Dedicated service account for the Cloud Run service. Gets only the
# permissions it needs — secret access + artifact registry reads.
resource "google_service_account" "bartenders_run" {
  project      = var.project_name
  account_id   = "bartenders-run"
  display_name = "Cloud Run service account for bartenders"
}

# `gcloud run deploy` needs to "act as" the runtime service account to create
# a new revision that runs as it. Grant CI the serviceAccountUser role on
# the bartenders-run SA (scoped — not project-wide).
resource "google_service_account_iam_member" "ci_impersonates_run_sa" {
  service_account_id = google_service_account.bartenders_run.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${var.ci_service_account}"
}

# Secrets for Supabase credentials. Values are NOT stored in terraform —
# add versions manually with:
#   echo -n "$SUPABASE_URL" | gcloud secrets versions add supabase-url --data-file=-
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

# CI needs to both read (to diff before adding) and add new versions.
# secretVersionManager covers both; secretAccessor lets us read values.
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

# Let the Cloud Run SA pull images from Artifact Registry
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

  template {
    service_account = google_service_account.bartenders_run.email

    scaling {
      min_instance_count = 0 # scale to zero
      max_instance_count = 3
    }

    containers {
      # Initial placeholder — real image tag is rolled out by the deploy
      # workflow via `gcloud run deploy`. Terraform ignores changes to this
      # field (see lifecycle below).
      image = "us-docker.pkg.dev/cloudrun/container/hello"

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
        # Only bill for CPU while a request is in-flight (request-based billing)
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
    # The deploy workflow updates the image tag — don't let terraform fight it.
    ignore_changes = [
      template[0].containers[0].image,
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

# Public access
resource "google_cloud_run_v2_service_iam_member" "public" {
  project  = google_cloud_run_v2_service.bartenders.project
  location = google_cloud_run_v2_service.bartenders.location
  name     = google_cloud_run_v2_service.bartenders.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}

# Custom domain mapping — Google-managed certificate, replaces cert-manager.
# Uses the v1 API (the only one terraform supports at time of writing).
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

# ---------------------------------------------------------------------------
# DNS (switches based on dns_target)
# ---------------------------------------------------------------------------

resource "google_dns_record_set" "cheetahmoongames_a" {
  project      = var.project_name
  name         = "${var.domain_name}."
  type         = "A"
  ttl          = 300
  managed_zone = "cheetahmoongames-com"

  rrdatas = var.dns_target == "k3s" ? (
    [google_compute_instance.k3s[0].network_interface[0].access_config[0].nat_ip]
    ) : (
    distinct([
      for r in google_cloud_run_domain_mapping.cheetahmoongames.status[0].resource_records :
      r.rrdata if r.type == "A"
    ])
  )
}

# Cloud Run domain mapping for an apex also returns AAAA records. Add them
# when serving via Cloud Run so IPv6 clients work too.
resource "google_dns_record_set" "cheetahmoongames_aaaa" {
  count = var.dns_target == "cloudrun" ? 1 : 0

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
# Legacy k3s (kept during migration, torn down by setting enable_legacy_k3s = false)
# ---------------------------------------------------------------------------

resource "google_compute_disk" "k3s_disk" {
  count = var.enable_legacy_k3s ? 1 : 0

  name    = "k3s-disk"
  project = var.project_name
  size    = 15
  type    = "pd-standard"
  zone    = var.zone
}

resource "google_compute_instance" "k3s" {
  count = var.enable_legacy_k3s ? 1 : 0

  project = var.project_name

  boot_disk {
    auto_delete = true
    device_name = "k3s"

    initialize_params {
      image = "projects/debian-cloud/global/images/debian-12-bookworm-v20250812"
      size  = 10
      type  = "pd-balanced"
    }

    mode = "READ_WRITE"
  }

  attached_disk {
    source      = google_compute_disk.k3s_disk[0].id
    device_name = "k3s-disk"
  }

  can_ip_forward      = false
  deletion_protection = false
  enable_display      = false

  labels = {
    goog-ec-src           = "vm_add-tf"
    goog-ops-agent-policy = "v2-x86-template-1-4-0"
    env                   = var.env
    region                = var.region
    app                   = var.app_name
    sensitive             = "false"
  }

  machine_type = "e2-small"

  metadata = {
    enable-osconfig = "TRUE"
  }

  name = "k3s-vm-1"

  network_interface {
    access_config {
      network_tier = "PREMIUM"
    }

    queue_count = 0
    stack_type  = "IPV4_ONLY"
    subnetwork  = "projects/bartenders-464918/regions/us-east1/subnetworks/default"
  }

  scheduling {
    automatic_restart   = true
    on_host_maintenance = "MIGRATE"
    preemptible         = false
    provisioning_model  = "STANDARD"
  }

  service_account {
    email  = "987774112216-compute@developer.gserviceaccount.com"
    scopes = ["https://www.googleapis.com/auth/devstorage.read_only", "https://www.googleapis.com/auth/logging.write", "https://www.googleapis.com/auth/monitoring.write", "https://www.googleapis.com/auth/service.management.readonly", "https://www.googleapis.com/auth/servicecontrol", "https://www.googleapis.com/auth/trace.append"]
  }

  shielded_instance_config {
    enable_integrity_monitoring = true
    enable_secure_boot          = false
    enable_vtpm                 = true
  }

  tags = ["http-server", "https-server", "web"]

  zone = var.zone

  metadata_startup_script   = file("scripts/install-k3s.sh")
  allow_stopping_for_update = true
}

resource "google_compute_firewall" "allow_http" {
  count = var.enable_legacy_k3s ? 1 : 0

  project = var.project_name
  name    = "allow-http"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["80", "443", "30080"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["web"]
}

resource "google_os_config_os_policy_assignment" "ops_agent_config" {
  count = var.enable_legacy_k3s ? 1 : 0

  project  = var.project_name
  location = var.zone
  name     = "ops-agent-k3s-config"

  instance_filter {
    all = false
    inclusion_labels {
      labels = {
        app = var.app_name
      }
    }
  }

  os_policies {
    id   = "ops-agent-k3s-config"
    mode = "ENFORCEMENT"

    resource_groups {
      resources {
        id = "ops-agent-config-file"
        file {
          path    = "/etc/google-cloud-ops-agent/config.yaml"
          state   = "CONTENTS_MATCH"
          content = file("${path.module}/files/ops-agent-config.yaml")
        }
      }

      resources {
        id = "restart-ops-agent-on-change"
        exec {
          validate {
            interpreter = "SHELL"
            script      = <<-EOT
              MARKER=/var/lib/google/ops-agent-config-applied
              CONFIG=/etc/google-cloud-ops-agent/config.yaml
              if [ ! -f "$MARKER" ] || [ "$CONFIG" -nt "$MARKER" ]; then
                exit 100
              fi
              exit 101
            EOT
          }
          enforce {
            interpreter = "SHELL"
            script      = <<-EOT
              mkdir -p /var/lib/google
              systemctl restart google-cloud-ops-agent && \
                touch /var/lib/google/ops-agent-config-applied && \
                exit 100
              exit 1
            EOT
          }
        }
      }
    }
  }

  rollout {
    disruption_budget {
      fixed = 1
    }
    min_wait_duration = "60s"
  }
}

module "ops_agent_policy" {
  count = var.enable_legacy_k3s ? 1 : 0

  source        = "github.com/terraform-google-modules/terraform-google-cloud-operations/modules/ops-agent-policy"
  project       = var.project_name
  zone          = var.zone
  assignment_id = "goog-ops-agent-v2-x86-template-1-4-0-us-east1-d"
  agents_rule = {
    package_state = "installed"
    version       = "latest"
  }
  instance_filter = {
    all = false
    inclusion_labels = [{
      labels = {
        goog-ops-agent-policy = "v2-x86-template-1-4-0"
      }
    }]
  }
}

# ---------------------------------------------------------------------------
# Outputs — useful for review and for the deploy workflow
# ---------------------------------------------------------------------------

output "cloud_run_url" {
  value       = google_cloud_run_v2_service.bartenders.uri
  description = "Direct Cloud Run URL (use this to test before switching DNS)"
}

output "cloud_run_service_account" {
  value       = google_service_account.bartenders_run.email
  description = "Service account used by the Cloud Run service"
}

output "domain_mapping_records" {
  value       = google_cloud_run_domain_mapping.cheetahmoongames.status[0].resource_records
  description = "DNS records returned by the Cloud Run domain mapping"
}
