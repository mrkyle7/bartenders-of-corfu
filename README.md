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

# Push Notifications

The installed PWA uses [Web Push](https://developer.mozilla.org/en-US/docs/Web/API/Push_API) ([VAPID](https://datatracker.ietf.org/doc/html/rfc8292)) to notify players when it's their turn or a game ends — even when the app is fully closed.

## How it works

```
Your Server (Cloud Run)          Browser Vendor             Player's Device
        │                        Push Service                      │
        │   1. Player grants                                       │
        │      notification permission ◄───────────────────────── │
        │                                                          │
        │   2. Browser subscribes to push service, gets endpoint  │
        │ ◄──────────────────────────────────────────────────────  │
        │                                                          │
        │   3. Browser POSTs subscription {endpoint, p256dh, auth}│
        │ ◄──────────────────────────────────────────────────────  │
        │   (stored in Supabase push_subscriptions table)         │
        │                                                          │
        │   ── later, when a turn changes ──                      │
        │                                                          │
        │   4. Server encrypts payload with p256dh/auth,          │
        │      signs with VAPID private key,                       │
        │      POSTs to endpoint URL ──────────────────────────►  │
        │                             5. Push service delivers ──► │
        │                                                          │
        │                             6. Browser wakes service    │
        │                                worker via `push` event ► │
        │                                                          │
        │                             7. Service worker shows     │
        │                                OS notification ────────► │
```

## Key pieces

| What | Where |
|---|---|
| VAPID key generation | `scripts/generate_vapid_keys.py` |
| Server-side send | `app/push.py` |
| Subscription storage | `supabase/migrations/20260509000001_push_subscriptions.sql` |
| API endpoints | `POST /v1/push-subscriptions`, `DELETE /v1/push-subscriptions`, `GET /vapid-public-key` |
| Service worker handler | `static/sw.js` — `push` event |
| Browser subscription | `static/script.js` + `static/game.js` — `subscribeToPush()` |
| Infrastructure | `terraform/main.tf` — `vapid-private-key` and `vapid-public-key` secrets |

## References

- [Web Push Protocol (RFC 8030)](https://datatracker.ietf.org/doc/html/rfc8030)
- [VAPID — Voluntary Application Server Identification (RFC 8292)](https://datatracker.ietf.org/doc/html/rfc8292)
- [MDN — Push API](https://developer.mozilla.org/en-US/docs/Web/API/Push_API)
- [MDN — Service Worker API](https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API)
- [pywebpush library](https://github.com/web-push-libs/pywebpush)

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