# Bartenders of Corfu

[![Test](https://github.com/mrkyle7/bartenders-of-corfu/actions/workflows/test.yml/badge.svg)](https://github.com/mrkyle7/bartenders-of-corfu/actions/workflows/test.yml)

[![Build and Push to Artifact Registry](https://github.com/mrkyle7/bartenders-of-corfu/actions/workflows/build-and-push.yml/badge.svg)](https://github.com/mrkyle7/bartenders-of-corfu/actions/workflows/build-and-push.yml)

[![Cloud Run Deploy](https://github.com/mrkyle7/bartenders-of-corfu/actions/workflows/cloud-run-deploy.yml/badge.svg)](https://github.com/mrkyle7/bartenders-of-corfu/actions/workflows/cloud-run-deploy.yml)

Python implementation of the best game ever made (about making cocktails and getting drunk and also winning through spectacular kareoke).

# Start it up

Note you'll need uv and supabase installed. [supabase cli](https://supabase.com/docs/guides/local-development/cli/getting-started)

```
supabase start --network-id k3s-net
./run-local.sh
```

access on http://localhost:8080

# Supabase

```
supabase start --network-id k3s-net
```

To add migrations: `supabase migration new ...`

Apply migrations: `supabase migration up`

Reset all data: `supabase db reset --network-id k3s-net`

# Infrastructure

All GCP resources are managed in `terraform/`. This includes the Cloud Run service, Artifact Registry, Secret Manager, DNS, Workload Identity Federation, and all IAM bindings.

```
cd terraform
terraform init
terraform plan
terraform apply
```

The only manual prerequisite is creating the `github-terraform` service account itself and verifying domain ownership (`gcloud domains verify cheetahmoongames.com`). Everything else is declared in terraform.

# Testing

Run `./run-tests.sh`