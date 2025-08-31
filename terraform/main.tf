# This code is compatible with Terraform 4.25.0 and versions that are backwards compatible to 4.25.0.
# For information about validating this Terraform code, see https://developer.hashicorp.com/terraform/tutorials/gcp-get-started/google-cloud-platform-build#format-and-validate-the-configuration

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

resource "google_compute_disk" "k3s_disk" {
  name = "k3s-disk"
  project = var.project_name
  size = 15
  type = "pd-standard"
  zone = var.zone
}

resource "google_compute_instance" "k3s" {
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
    source      = google_compute_disk.k3s_disk.id
    device_name = "k3s-disk"
  }

  can_ip_forward      = false
  deletion_protection = false
  enable_display      = false

  labels = {
    goog-ec-src           = "vm_add-tf"
    goog-ops-agent-policy = "v2-x86-template-1-4-0"
    env       = var.env
    region    = var.region
    app       = var.app_name
    sensitive = "false"
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
  project = var.project_name
  name    = "allow-http"
  network = "default"

  allow {
    protocol = "tcp"
    ports    = ["80", "443", "30080", "6443"]
  }

  source_ranges = ["0.0.0.0/0"]
  target_tags   = ["web"]
}

resource "google_storage_bucket" "k3s-storage" {
  name     = var.bucket_name
  location = var.region

  project = var.project_name

  labels = {
    env       = var.env
    region    = var.region
    app       = var.app_name
    sensitive = "false"
  }
}

module "ops_agent_policy" {
  source          = "github.com/terraform-google-modules/terraform-google-cloud-operations/modules/ops-agent-policy"
  project         = var.project_name
  zone            = var.zone
  assignment_id   = "goog-ops-agent-v2-x86-template-1-4-0-us-east1-d"
  agents_rule = {
    package_state = "installed"
    version = "latest"
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
