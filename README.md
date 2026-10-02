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
| VAPID keys | Made by the server and kept in the database (`vapid_keys`): see below |
| Server-side send | `app/push.py` |
| Subscription storage | `supabase/migrations/20260509000001_push_subscriptions.sql` |
| API endpoints | `POST /v1/push-subscriptions`, `DELETE /v1/push-subscriptions`, `GET /vapid-public-key` |
| Service worker handler | `static/sw.js` — `push` event |
| Browser subscription | `static/script.js` — `subscribeToPush()` |

## The keys

The key pair that signs notifications lives in the database (`vapid_keys`, one row), so there are no secrets to set up. The first server that needs it makes it and saves it, and every later server uses the same pair (`get_keys()` in `app/push.py`). If the database can't be read, no notifications are sent and `/vapid-public-key` answers 503 until it can.

The keys used to be the Secret Manager secrets `vapid-public-key` and `vapid-private-key`, read as `VAPID_PUBLIC_KEY` and `VAPID_PRIVATE_KEY`. A server that finds no pair in the database saves those, if it has them, so devices that already had notifications keep getting them. After that the secrets can be removed from `terraform/bartenders.tf` in [mrkyle7/cheetahmoongames](https://github.com/mrkyle7/cheetahmoongames). This is the way ADDING_A_GAME.md there describes for every game's notifications.

## References

- [Web Push Protocol (RFC 8030)](https://datatracker.ietf.org/doc/html/rfc8030)
- [VAPID — Voluntary Application Server Identification (RFC 8292)](https://datatracker.ietf.org/doc/html/rfc8292)
- [MDN — Push API](https://developer.mozilla.org/en-US/docs/Web/API/Push_API)
- [MDN — Service Worker API](https://developer.mozilla.org/en-US/docs/Web/API/Service_Worker_API)
- [pywebpush library](https://github.com/web-push-libs/pywebpush)

# Infrastructure

Bartenders runs at **https://bartenders.cheetahmoongames.com**, one of the games on [cheetahmoongames.com](https://cheetahmoongames.com).

Its Google Cloud setup lives in **[mrkyle7/cheetahmoongames](https://github.com/mrkyle7/cheetahmoongames)**, next to the other games: `terraform/bartenders.tf` covers the Cloud Run service, secrets, subdomain and IAM. Change infrastructure there; its workflow applies Terraform when changes merge.

This repo's `.github/workflows/ci-cd.yml` still deploys the app itself: it pushes Supabase migrations, syncs the Supabase secrets and deploys a new image to the `bartenders` service.

With `COOKIE_DOMAIN=cheetahmoongames.com` (set in that Terraform), the login cookie is shared across every `cheetahmoongames.com` subdomain; see `app/auth_cookie.py`. Unset, as in local runs and tests, the cookie is host-only.

Bartenders' accounts are the Cheetah Moon accounts for every game on the site:

- Players sign in at `https://cheetahmoongames.com/login`. With `LOGIN_URL` set (also in that Terraform), `GET /login` here redirects there, with `next` pointing back to the page that sent the player. Unset, `/login` serves the page in `static/login.html` as before.
- The home page passes sign-in, sign-up and sign-out on to `/login`, `/register`, `/logout` and `/userDetails` here.
- `GET /v1/auth/keys/{kid}` returns the public key for a login token's `kid`, so other games can check the `userjwt` cookie themselves.
- Forgotten passwords: `POST /v1/auth/password-reset {email, next?}` emails a one-time link (valid for an hour, at most 3 an hour per account) through [Brevo](https://www.brevo.com), always answering 202 so it doesn't reveal which emails have accounts. `POST /v1/auth/password-reset/confirm {token, new_password}` sets the password, signs out every other session and signs the player in. The pages for it are on the home page. Emails need `BREVO_API_KEY` (the `BREVO_API_KEY` GitHub secret, synced to Secret Manager on deploy) and `EMAIL_FROM`, a sender Brevo has verified; without a key nothing is sent. Code: `app/password_reset.py`, `app/email_sender.py`.

# Testing

Run `uv run pytest`