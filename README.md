# Bartenders of Corfu

[![Test](https://github.com/mrkyle7/bartenders-of-corfu/actions/workflows/test.yml/badge.svg)](https://github.com/mrkyle7/bartenders-of-corfu/actions/workflows/test.yml)

[![Build and Push to Artifact Registry](https://github.com/mrkyle7/bartenders-of-corfu/actions/workflows/build-and-push.yml/badge.svg)](https://github.com/mrkyle7/bartenders-of-corfu/actions/workflows/build-and-push.yml)

[![Kubernetes Deployment](https://github.com/mrkyle7/bartenders-of-corfu/actions/workflows/kubectl-deploy.yml/badge.svg)](https://github.com/mrkyle7/bartenders-of-corfu/actions/workflows/kubectl-deploy.yml)

Python implementation of the best game ever made (about making cocktails and getting drunk and also winning through spectacular kareoke)

# Start it up

If you want a pure python experience (note this may not work now since supabase...)

First get venv working:

```
python -m venv venv .
source .venv/bin/activate
pip install -r requirements.txt
```

Then you can 

```
source .venv/bin/activate
uvicorn app.api:app --reload --log-config=log_conf.yaml
```

access on http://localhost:8000

# local k3s

To test locally how this is run on GCP...

First run supabase locally using the [supabase cli](https://supabase.com/docs/guides/local-development/cli/getting-started)

```
supabase start --network-id k3s-net
```

Apply Migrations 

`supabase migration new ...`

Apply migrations

`supabase migration up`

reset all data

```
supabase db reset --network-id k3s-net
```

Copy .env_example to .env with the supabase secret key

Run `k-apply.sh` to build and push changes to local k3s

Note: you need docker installed first. 

Note2: only tested on Mac, YMMV.

access on https://localhost

# creating the GCP stuff with terraform

```
cd terraform
terraform init
terraform plan
terraform apply
```

# Testing

Run `python -m unittest discover tests`

# manual setup commands

Set up github auth

```
gcloud iam workload-identity-pools create "github-pool" \
  --location="global" \
  --display-name="GitHub Actions Pool"

gcloud iam workload-identity-pools providers create-oidc github-provider \
  --location="global" \
  --workload-identity-pool="github-pool" \
  --display-name="GitHub Actions OIDC Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="attribute.repository == 'mrkyle7/bartenders-of-corfu'" \
  --issuer-uri="https://token.actions.githubusercontent.com"

gcloud iam service-accounts add-iam-policy-binding github-terraform@bartenders-464918.iam.gserviceaccount.com \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/987774112216/locations/global/workloadIdentityPools/github-pool/attribute.repository/mrkyle7/bartenders-of-corfu"

gcloud projects add-iam-policy-binding bartenders-464918 \                                                                                  
  --member="serviceAccount:github-terraform@bartenders-464918.iam.gserviceaccount.com" \
  --role="roles/storage.admin"

gcloud artifacts repositories add-iam-policy-binding docker \
  --location=us-east1 \
  --member="serviceAccount:github-terraform@bartenders-464918.iam.gserviceaccount.com" \
  --role="roles/artifactregistry.writer"

gcloud projects add-iam-policy-binding bartenders-464918 \     
  --member="serviceAccount:github-terraform@bartenders-464918.iam.gserviceaccount.com" \
  --role="roles/compute.instanceAdmin.v1"

gcloud projects add-iam-policy-binding bartenders-464918 \
  --member="serviceAccount:github-terraform@bartenders-464918.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"

gcloud iam service-accounts add-iam-policy-binding k3s-server@bartenders-464918.iam.gserviceaccount.com \
  --project=bartenders-464918 \
  --member="serviceAccount:github-terraform@bartenders-464918.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"

gcloud projects add-iam-policy-binding bartenders-464918 \
  --member="serviceAccount:github-terraform@bartenders-464918.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountKeyAdmin"
```


# Useful docker/k3s stuff

Shell in k3s for testing stuff

`kubectl run dns-test --image=busybox --restart=Never --rm -it -- sh`