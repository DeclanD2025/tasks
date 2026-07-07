# Deploying ORION web

ORION web (`app/web`) is a **stateful Python server over a private SQLite
database** containing health and finance data. That shapes the deployment
options — read the trade-offs before putting it anywhere public.

## TL;DR — true phone + desktop mobility in ~15 minutes

The goal: one URL that works on the iPhone on 4G, the iPhone at home, and any
desktop browser, always showing the same data.

**Path 1 — Tailscale (data stays on the Mac, ~10 min, free):**

```bash
brew install --cask tailscale        # then sign in on the Mac
# install Tailscale from the App Store on the iPhone, same account
cd ~/orion && ORION_WEB_HOST=0.0.0.0 uv run orion-web
tailscale serve --bg 8321            # prints https://<your-mac>.<tailnet>.ts.net
```

Open that HTTPS URL on any of your devices, add to the iPhone home screen
(Share → Add to Home Screen). The Mac must be awake to serve; data never
leaves it. This is the recommended default.

**Path 2 — Fly.io (works even when the Mac is asleep, ~15 min, ~$3/mo):**

```bash
brew install flyctl && fly auth signup
cd ~/orion
fly launch --no-deploy               # accepts the Dockerfile; pick lhr (London)
fly volumes create orion_data --size 1 --region lhr
fly secrets set ORION_UNLOCK_PASSPHRASE='<strong passphrase>' \
                ORION_WEB_SECRET="$(openssl rand -hex 32)" \
                ORION_WEB_SECURE=1 \
                ORION_INGEST_TOKEN="$(openssl rand -hex 24)"   # enables HAE push ingest
# add the [mounts] + [http_service] blocks below to fly.toml, then:
fly deploy
# one-off: seed the cloud copy with a consistent local database snapshot
sqlite3 "$HOME/Library/Application Support/ORION/orion.db" \
  ".backup '/tmp/orion-deploy.db'"
fly ssh sftp shell
put /tmp/orion-deploy.db /data/orion.db
```

You get `https://<app>.fly.dev` from anywhere. Check-ins made on the phone
land in the cloud copy; the Mac desktop app keeps its local copy — see
"Keeping it fresh" below for how to reconcile.

## The Netlify question, answered honestly

Netlify (and Vercel static, GitHub Pages, Cloudflare Pages) host **static
files and short-lived serverless functions**. They cannot run a persistent
Python server with an SQLite file on disk, so ORION cannot ship there without
re-architecting it into a hosted-database SaaS — which would defeat its
local-first privacy model. The equivalents that *do* fit are container hosts:
Fly.io, Railway, Render. This repo is fully prepared for those (see below).

## Option A — stay local, reach it anywhere (recommended)

Your data never leaves the Mac; your phone reaches it from anywhere.

1. Run the server: double-click `~/start-orion-web.command` (LAN) or
   `uv run orion-web`.
2. Install [Tailscale](https://tailscale.com) on the Mac and your phone
   (free personal plan).
3. `tailscale serve --bg 8321` gives you a stable private HTTPS URL that
   works from any network, with TLS handled for you.

Zero hosting cost, zero data exposure, no volume management.

## Option B — container host (Fly.io / Railway / Render)

The repo ships a production `Dockerfile` (web layer only, no Qt — ~350 MB
image instead of >1 GB). What every platform needs:

| Concern | Setting |
|---|---|
| Persistent DB | volume mounted at `/data` (DB lives at `/data/orion.db`) |
| Auth | `ORION_UNLOCK_PASSPHRASE` = strong passphrase (**required**: `ORION_ENV=production` is set in the image and production refuses the demo passphrase) |
| Sessions | `ORION_WEB_SECRET` = long random string (`openssl rand -hex 32`) |
| TLS | platform provides HTTPS; set `ORION_WEB_SECURE=1` for secure cookies + HSTS |
| Port | 8321 |
| Health check | `GET /healthz` |
| HAE push | Either set `ORION_INGEST_TOKEN`, or log in and generate a token from Data Vault |

### Fly.io walkthrough

```bash
fly launch --no-deploy               # detects the Dockerfile; pick a region
fly volumes create orion_data --size 1
fly secrets set ORION_UNLOCK_PASSPHRASE='<strong passphrase>' \
                ORION_WEB_SECRET="$(openssl rand -hex 32)" \
                ORION_WEB_SECURE=1 \
                ORION_INGEST_TOKEN="$(openssl rand -hex 24)"   # enables HAE push ingest
fly deploy
```

`fly.toml` needs the mount and service:

```toml
[mounts]
  source = "orion_data"
  destination = "/data"

[http_service]
  internal_port = 8321
  force_https = true

[[http_service.checks]]
  path = "/healthz"
  interval = "30s"
```

Seed the remote DB with your local data (one-off). Use SQLite's backup command
instead of copying `orion.db` directly: ORION uses WAL mode, so recent writes
may still be in `orion.db-wal` until SQLite checkpoints them.

```bash
sqlite3 "$HOME/Library/Application Support/ORION/orion.db" \
  ".backup '/tmp/orion-deploy.db'"
fly ssh sftp shell
put /tmp/orion-deploy.db /data/orion.db
```

Keeping it fresh afterwards: either re-upload periodically, or keep the Mac
as the source of truth and treat the deployed copy as a read-mostly mirror.
There is deliberately no automatic cloud sync — that keeps the data path
auditable.

Health Auto Export can push directly into the web app. If you did not set
`ORION_INGEST_TOKEN` as a host secret, open Data Vault in the deployed app and
use **Generate HAE token**. Configure Health Auto Export's REST automation with:

```text
POST https://<app>.fly.dev/api/ingest/hae
Authorization: Bearer <generated token>
Content-Type: application/json
```

### Railway / Render

Both auto-detect the Dockerfile. Add a persistent volume mounted at `/data`,
set the same three environment variables, done.

## What you accept with Option B

- Your health and finance database sits on a cloud host's disk. The unlock
  passphrase gates the UI and the platform encrypts at rest, but the SQLite
  file itself is not application-encrypted (SQLCipher is still a TODO).
- Anyone who obtains the URL can attempt the passphrase (failed attempts are
  rate-limited, but choose a genuinely strong passphrase).

If either bothers you, use Option A — it is the design-intent deployment.
