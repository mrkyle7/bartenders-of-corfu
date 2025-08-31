# Bartenders of Corfu

[![Build and Push to Artifact Registry](https://github.com/mrkyle7/bartenders-of-corfu/actions/workflows/build-and-push.yml/badge.svg)](https://github.com/mrkyle7/bartenders-of-corfu/actions/workflows/build-and-push.yml)

Python implementation of the best game ever made (about making cocktails and getting drunk and also winning through spectacular kareoke)

# Start it up

Get Docker.

Run 

```
docker compose watch
```

# local k3s

`docker network create k3s-net`

```
docker run --privileged --name k3s-server -d \
  -p 6443:6443 -p 80:80 -p 443:443 -p 30800:30800 \
  -v k3s-data:/var/lib/rancher/k3s \
  --hostname k3s-server \
  --network k3s-net \
  rancher/k3s:v1.29.1-k3s1 server \
  --node-name k3s-server 
```

`docker cp k3s-registries.yaml k3s-server:/etc/rancher/k3s/registries.yaml`

`docker cp k3s-server:/etc/rancher/k3s/k3s.yaml k3s.yaml`

`export KUBECONFIG=k3s.yaml`

`docker run --name registry -d -p 5000:5000 --network k3s-net --hostname docker-registry --restart=always registry:latest`

`docker build . -t localhost:5000/bartenders`

`docker push localhost:5000/bartenders`

`kubectl create -f k3s/bartenders.yml`

`kubectl create -f k3s/nodeport.yml`


`kubectl get pods`

access on http://localhost:30800


# restart nginx

`kubectl scale deployment my-nginx --replicas=0; kubectl scale deployment my-nginx --replicas=2;`


# Testing

Coming soon...

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
```