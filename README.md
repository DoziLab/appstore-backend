# App Store Backend

A FastAPI-based backend for managing deployments on Openstack.

## Quick Start 

### Prerequisites

- Docker & Docker Compose
- Python 3.11+ (for local development)

### 1. Clone and Setup

```bash
git clone <repository-url>
cd appstore-backend
```

### 2. Environment Configuration

Copy the example environment file:

```bash
cp .env.example .env
```

### 3. Start with Docker (Recommended)

```bash
docker compose up -d
```

This starts:
- **API** at http://localhost:8000
- **PostgreSQL** at localhost:5432
- **Redis** at localhost:6379
- **Celery Worker** for async tasks
- **Prometheus** at http://localhost:9090 (metrics)
- **Loki** at localhost:3100 (log aggregation)
- **Grafana** at http://localhost:8888 (monitoring dashboards)
- **Promtail** (log collection)

### 4. Verify Installation

```bash
# Health check
curl http://localhost:8000/health

# API documentation
open http://localhost:8000/docs
```

## Local Development (without Docker)

### 1. Create Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate  #On Windows: .venv\Scripts\activate
```

### 2. Install Dependencies

```bash
pip install -e ".[dev]"
```

### 3. Start Services

Make sure PostgreSQL and Redis are running locally, then:

```bash
uvicorn src.main:app --reload
```

## Useful Commands

```bash
# View logs
docker compose logs -f api

# Rebuild after code changes
docker compose up -d --build

# Stop all services
docker compose down

# Reset database (deletes all data!)
docker compose down -v
```

## Monitoring & Observability

Access Grafana at http://localhost:8888

## GitHub App Setup (template imports)

The `import-from-github` template feature requires a registered GitHub App.
Without it the API stays online but `/api/v1/auth/github/*` and
`/api/v1/templates/import-from-github` return *"GitHub App is not configured"*.

You only need to run this **once per environment** (Staging, Production).
Local development can leave the variables empty.

### 1. Create the GitHub App

Go to **https://github.com/organizations/DoziLab/settings/apps/new**
(or `https://github.com/settings/apps/new` for a personal account).

| Field | Value |
|---|---|
| GitHub App name | `DoziLab AppStore Staging` (or `… Production`) |
| Homepage URL | `https://<your-host>` (e.g. `https://141.72.13.2`) |
| Identifying and authorizing users → Callback URL | *leave blank* |
| Post installation → Setup URL | `https://<your-host>/api/v1/auth/github/install-callback` |
| Post installation → Redirect on update | ✅ **enabled** |
| Webhook → Active | ❌ **disabled** (no webhooks used) |
| Repository permissions → **Contents** | **Read-only** |
| Repository permissions → **Metadata** | Read-only (auto) |
| Where can this GitHub App be installed? | "Any account" if external lecturers should connect their repos, otherwise "Only on this account" |

Leave all three "Identifying and authorizing users" / "Device Flow" toggles
**unchecked** — the backend uses installation tokens (server-to-server) and
does not need user OAuth tokens.

After **Create GitHub App**, collect on the App settings page:

- **App ID** — numeric, e.g. `123456`
- **Public link** / slug — the part after `/apps/` in the public URL,
  e.g. `dozilab-appstore-staging`
- **Private key** — scroll to *Private keys* → *Generate a private key* →
  GitHub downloads a `.pem` file. **Store it securely** — GitHub never shows
  it again. To rotate, generate a new one and delete the old.

Then generate a state-secret locally (used by the backend to HMAC-sign the
install round-trip; **not** the GitHub App's "Client secret"):

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

You now have **five values** per environment:

| Variable | Source |
|---|---|
| `GITHUB_APP_ID` | numeric App ID from the App settings page |
| `GITHUB_APP_SLUG` | URL slug from the App's public link |
| `GITHUB_APP_PRIVATE_KEY` | full PEM contents of the downloaded `.pem` (multi-line, including the `-----BEGIN/END-----` lines) |
| `GITHUB_APP_STATE_SECRET` | output of the `secrets.token_urlsafe(32)` command above |
| `FRONTEND_BASE_URL` | where users are redirected after install, e.g. `https://141.72.13.2` |

### 2. Add the values as GitHub Actions secrets

The CI deploy job (`deploy-staging` / `deploy-production` in
[.github/workflows/ci-cd.yml](.github/workflows/ci-cd.yml)) reads these
secrets and writes them into `/opt/appstore/.env` on the target server
before `docker compose pull/up`.

Open the org-level secrets page —
**https://github.com/organizations/DoziLab/settings/secrets/actions** —
and add the following (use *Repository access → All repositories* or
explicitly grant access to `appstore-backend`, matching how
`STAGING_SERVER_HOST` etc. are scoped):

For **Staging**:

- `STAGING_GITHUB_APP_ID`
- `STAGING_GITHUB_APP_SLUG`
- `STAGING_GITHUB_APP_PRIVATE_KEY` — paste the full PEM contents directly,
  GitHub preserves newlines
- `STAGING_GITHUB_APP_STATE_SECRET`
- `STAGING_FRONTEND_BASE_URL`

For **Production** (same names with `PROD_` prefix), once a separate
production GitHub App is registered. Use a **different** state secret per
environment so a leaked staging value cannot forge production installs.

### 3. Deploy

A push to `staging` (or `main` for production once the prod block is
added to `ci-cd.yml`) triggers the pipeline. The new
*Sync GitHub App env vars* step writes a marker-delimited block into
`/opt/appstore/.env`:

```
# >>> github-app (managed by ci-cd.yml) >>>
GITHUB_APP_ID=…
GITHUB_APP_SLUG=…
GITHUB_APP_STATE_SECRET=…
FRONTEND_BASE_URL=…
GITHUB_APP_PRIVATE_KEY="-----BEGIN …-----
…
-----END …-----"
# <<< github-app <<<
```

Re-runs of the workflow are idempotent — the previous block is removed
before the new one is appended, so values can be rotated by editing the
GitHub secret and re-running the deploy.

### 4. Verify

After the workflow finishes, on the target server:

```bash
ssh ubuntu@<host>
cd /opt/appstore

# Block exists, file is 600
ls -la .env
sed -n '/>>> github-app/,/<<< github-app/p' .env | head -3

# Variables reach the running container
docker compose -f docker-compose.yml -f docker-compose.staging.yml exec api \
  sh -c 'echo "ID=$GITHUB_APP_ID SLUG=$GITHUB_APP_SLUG"; \
         echo "STATE_SECRET set: $([ -n "$GITHUB_APP_STATE_SECRET" ] && echo yes || echo no)"; \
         echo "PRIVATE_KEY first line: $(echo "$GITHUB_APP_PRIVATE_KEY" | head -1)"'
```

Then hit the install endpoint as a logged-in lecturer/admin:

```bash
curl -k -H "Authorization: Bearer $KC_ACCESS_TOKEN" \
  -X POST https://<host>/api/v1/auth/github/install
# → {"data":{"install_url":"https://github.com/apps/<slug>/installations/new?state=…"}, ...}
```

If the response is *"GitHub App is not configured. Set GITHUB_APP_SLUG…"*,
the `.env` sync did not take effect — check the
*Sync GitHub App env vars to Staging* step in the Actions log.

### Local development

Leave the five variables empty (or unset) in your local `.env`. The API
boots normally; only the GitHub-related endpoints fail with a clear
configuration error. To exercise the import flow locally, register a
second GitHub App (Callback URL `http://localhost:8000/api/v1/auth/github/install-callback`)
and set the same five variables in `.env`.

