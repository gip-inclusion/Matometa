# Deploying Matometa on Scalingo

This guide covers deploying Matometa on Scalingo from scratch.

## Architecture

```
Internet
  │
  ▼
Scalingo router (:443)
  │
  ▼
oauth2-proxy (:$PORT)          ← handles Google OAuth, sets X-Forwarded-Email
  │
  ▼
gunicorn + Flask (:8080)       ← reads X-Forwarded-Email, serves the app
  │
  ├──▶ PostgreSQL (addon)      ← conversations, reports, schema
  └──▶ S3 storage (optional)   ← interactive files, exports
```

The `betagouv/oauth2-proxy-buildpack` runs oauth2-proxy as a sidecar in the same
dyno. It listens on `$PORT` (Scalingo's public port), authenticates users via
Google OAuth, then proxies requests to gunicorn on port 8080 with the user's
email injected in the `X-Forwarded-Email` header.

The Flask app reads this header exactly as it does behind any reverse proxy —
no application-level OAuth code needed.

## Prerequisites

- A Scalingo account with CLI installed (`scalingo login`)
- A Google Cloud project with OAuth 2.0 credentials (see [Google OAuth setup](#google-oauth-setup))
- API keys for external services (Matomo, Metabase, etc.)

## Step 1: Create the Scalingo app

```bash
scalingo create matometa
```

## Step 2: Add the PostgreSQL addon

```bash
scalingo --app matometa addons-add postgresql postgresql-starter-512
```

Scalingo automatically sets `DATABASE_URL` in the app's environment. The app
detects this and uses PostgreSQL instead of SQLite. Schema migrations run
automatically on startup.

## Step 3: Configure environment variables

### Required variables

```bash
# --- App core ---
scalingo --app matometa env-set \
  AGENT_BACKEND=sdk \
  ANTHROPIC_API_KEY=<your-anthropic-api-key> \
  WEB_DEBUG=false \
  ADMIN_USERS=you@inclusion.gouv.fr

# --- OAuth2 (see "Google OAuth setup" section below) ---
scalingo --app matometa env-set \
  OAUTH2_PROXY_PROVIDER=google \
  OAUTH2_PROXY_CLIENT_ID=<your-google-client-id>.apps.googleusercontent.com \
  OAUTH2_PROXY_CLIENT_SECRET=<your-google-client-secret> \
  OAUTH2_PROXY_COOKIE_SECRET=$(python3 -c 'from secrets import token_urlsafe; print(token_urlsafe(32)[:32])') \
  OAUTH2_PROXY_EMAIL_DOMAINS=inclusion.gouv.fr \
  OAUTH2_PROXY_REDIRECT_URL=https://matometa.osc-fr1.scalingo.io/oauth2/callback \
  OAUTH2_PROXY_UPSTREAMS=http://127.0.0.1:8080 \
  OAUTH2_PROXY_SET_XAUTHREQUEST=true \
  OAUTH2_PROXY_COOKIE_SECURE=true
```

### External API keys

These are needed for querying Matomo and Metabase instances. The app works
without them, but query features will fail for the corresponding sources.

```bash
scalingo --app matometa env-set \
  MATOMO_API_KEY=<your-matomo-token> \
  METABASE_STATS_API_KEY=<your-metabase-stats-key> \
  METABASE_DATALAKE_API_KEY=<your-metabase-datalake-key> \
  METABASE_DORA_API_KEY=<your-metabase-dora-key> \
  METABASE_RDVI_API_KEY=<your-metabase-rdvi-key>
```

### Optional integrations

```bash
# Notion (report publishing, wishlist, research corpus sync)
scalingo --app matometa env-set \
  NOTION_TOKEN=<your-notion-token> \
  NOTION_REPORTS_DB=<your-notion-reports-db-id> \
  NOTION_WISHLIST_DB=<your-notion-wishlist-db-id>

# GitHub (knowledge file PRs)
scalingo --app matometa env-set \
  GITHUB_PR_TOKEN=<your-github-pat> \
  GITHUB_REPO=gip-inclusion/Matometa

# Livestorm + Grist (webinaire sync)
scalingo --app matometa env-set \
  LIVESTORM_API_KEY=<your-livestorm-key> \
  GRIST_API_KEY=<your-grist-key> \
  GRIST_WEBINAIRES_DOC_ID=<your-grist-doc-id>

# DeepInfra (research corpus embeddings)
scalingo --app matometa env-set \
  DEEPINFRA_API_KEY=<your-deepinfra-key>
```

### S3 storage (optional)

If configured, interactive files (dashboards, CSV exports) are stored in S3
instead of the dyno's ephemeral filesystem. Recommended for production since
Scalingo dynos lose local files on restart.

```bash
scalingo --app matometa env-set \
  S3_BUCKET=<your-bucket-name> \
  S3_ENDPOINT=https://s3.fr-par.scw.cloud \
  S3_ACCESS_KEY=<your-s3-access-key> \
  S3_SECRET_KEY=<your-s3-secret-key> \
  S3_REGION=fr-par
```

Works with any S3-compatible provider: AWS S3, Scaleway Object Storage, etc.

## Step 4: Deploy

```bash
# Add Scalingo as a git remote (if not done)
scalingo --app matometa git-setup

# Deploy
git push scalingo main
```

Scalingo runs two buildpacks in order (defined in `.buildpacks`):

1. **Python buildpack** — installs Python 3.11 and `requirements.txt`
2. **oauth2-proxy buildpack** — downloads the oauth2-proxy binary into `/app/bin/`

Then the `Procfile` starts the wrapper script:

```
web: /app/bin/start_with_oauth2_proxy.sh gunicorn --worker-class gevent --workers 2 --bind 0.0.0.0:$PORT web.app:app
```

The wrapper script starts both oauth2-proxy (on `$PORT`) and gunicorn (on port 8080).

## Step 5: Verify

1. Open `https://matometa.osc-fr1.scalingo.io`
2. You should be redirected to Google sign-in
3. After login, you should land on the Matometa home page
4. Check the sidebar shows your email and conversations

If something is wrong:

```bash
scalingo --app matometa logs --lines 100
```

## Google OAuth setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/apis/credentials)
2. Create a project (or select existing)
3. Go to **APIs & Services > Credentials**
4. Click **Create Credentials > OAuth 2.0 Client IDs**
5. Application type: **Web application**
6. Add authorized redirect URI: `https://matometa.osc-fr1.scalingo.io/oauth2/callback`
7. Copy the **Client ID** and **Client Secret**

The `/oauth2/callback` path is handled by oauth2-proxy, not by the Flask app.

### Restricting access

- **By domain**: `OAUTH2_PROXY_EMAIL_DOMAINS=inclusion.gouv.fr` — only allows
  Google accounts with that domain
- **Multiple domains**: `OAUTH2_PROXY_EMAIL_DOMAINS=inclusion.gouv.fr,beta.gouv.fr`
- **Specific emails**: Set `OAUTH2_PROXY_AUTHENTICATED_EMAILS_FILE=/app/allowed_emails.txt`
  and create the file in the repo with one email per line
- **Anyone with a Google account**: `OAUTH2_PROXY_EMAIL_DOMAINS=*` (not recommended)

### Using a custom domain

If you add a custom domain (e.g., `matometa.inclusion.gouv.fr`):

1. Update `OAUTH2_PROXY_REDIRECT_URL` to use the new domain
2. Update the redirect URI in Google Cloud Console
3. Set `OAUTH2_PROXY_COOKIE_DOMAINS=matometa.inclusion.gouv.fr`

## Environment variable reference

### App configuration

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `AGENT_BACKEND` | yes | `ollama` | Agent runtime: `sdk`, `ollama`, `cli`, `cli-ollama` |
| `ANTHROPIC_API_KEY` | if sdk | — | Anthropic API key (for `sdk` backend) |
| `CLAUDE_MODEL` | no | `claude-sonnet-4-20250514` | Claude model to use |
| `WEB_DEBUG` | no | `true` | Set to `false` for production |
| `BASE_URL` | no | — | Absolute URL for shared links |
| `DEFAULT_USER` | no | `admin@localhost` | Fallback user (local dev only) |
| `ADMIN_USERS` | yes | — | Comma-separated admin emails |

### Database

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `DATABASE_URL` | auto | — | PostgreSQL URL (set by Scalingo addon) |

### S3 storage

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `S3_BUCKET` | no | — | Bucket name |
| `S3_ENDPOINT` | no | — | S3 endpoint URL |
| `S3_ACCESS_KEY` | no | — | Access key |
| `S3_SECRET_KEY` | no | — | Secret key |
| `S3_REGION` | no | `fr-par` | Region |
| `S3_PREFIX` | no | `interactive/` | Key prefix |

### OAuth2 proxy

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `OAUTH2_PROXY_PROVIDER` | yes | — | `google`, `github`, `oidc`, etc. |
| `OAUTH2_PROXY_CLIENT_ID` | yes | — | OAuth client ID |
| `OAUTH2_PROXY_CLIENT_SECRET` | yes | — | OAuth client secret |
| `OAUTH2_PROXY_COOKIE_SECRET` | yes | — | 32-char random string |
| `OAUTH2_PROXY_EMAIL_DOMAINS` | yes | — | Allowed email domains |
| `OAUTH2_PROXY_REDIRECT_URL` | yes | — | `https://<your-app>/oauth2/callback` |
| `OAUTH2_PROXY_UPSTREAMS` | yes | — | `http://127.0.0.1:8080` |
| `OAUTH2_PROXY_SET_XAUTHREQUEST` | no | `false` | Pass email in headers |
| `OAUTH2_PROXY_COOKIE_SECURE` | no | `false` | HTTPS-only cookies |
| `OAUTH2_PROXY_SKIP_PROVIDER_BUTTON` | no | `false` | Skip "Sign in" page, redirect directly |

Full oauth2-proxy config reference:
https://oauth2-proxy.github.io/oauth2-proxy/configuration/overview

### External APIs

| Variable | Required | Description |
|----------|----------|-------------|
| `MATOMO_API_KEY` | no | Matomo analytics token |
| `METABASE_STATS_API_KEY` | no | Stats Metabase instance |
| `METABASE_DATALAKE_API_KEY` | no | Datalake Metabase instance |
| `METABASE_DORA_API_KEY` | no | Dora Metabase instance |
| `METABASE_RDVI_API_KEY` | no | RDV-Insertion Metabase instance |
| `NOTION_TOKEN` | no | Notion API token |
| `NOTION_REPORTS_DB` | no | Notion database ID for reports |
| `NOTION_WISHLIST_DB` | no | Notion database ID for wishlist |
| `GITHUB_PR_TOKEN` | no | GitHub PAT for knowledge PRs |
| `GITHUB_REPO` | no | Target repo (e.g., `gip-inclusion/Matometa`) |
| `GITHUB_BRANCH` | no | Target branch for knowledge PRs (default: `main`) |
| `LIVESTORM_API_KEY` | no | Livestorm API key |
| `GRIST_API_KEY` | no | Grist API key |
| `GRIST_WEBINAIRES_DOC_ID` | no | Grist document ID for webinaires |
| `DEEPINFRA_API_KEY` | no | DeepInfra API key for embeddings |

## Scaling

The default `Procfile` starts 2 gunicorn workers with gevent (async). This is
suitable for low-to-moderate traffic. To increase capacity:

```bash
# More workers (in Procfile, or override via env var)
scalingo --app matometa env-set WEB_CONCURRENCY=4

# Larger dyno
scalingo --app matometa scale web:1:L
```

Each conversation uses an SSE (Server-Sent Events) connection for streaming,
which gevent handles efficiently without blocking a whole worker.

## Troubleshooting

### "Application error" on first visit

Check logs:

```bash
scalingo --app matometa logs --lines 200
```

Common causes:
- Missing `OAUTH2_PROXY_*` env vars → oauth2-proxy fails to start
- Wrong `OAUTH2_PROXY_REDIRECT_URL` → OAuth callback fails
- Missing `ANTHROPIC_API_KEY` with `AGENT_BACKEND=sdk` → agent queries fail (but app loads)

### OAuth callback error

- Verify `OAUTH2_PROXY_REDIRECT_URL` matches the redirect URI in Google Cloud Console exactly
- Verify `OAUTH2_PROXY_COOKIE_SECRET` is exactly 32 characters

### Database issues

The app auto-migrates the schema on startup. If you suspect corruption:

```bash
scalingo --app matometa run bash
python -c "from web.database import get_db; next(get_db()); print('DB OK')"
```

### Local files lost on restart

Scalingo dynos have ephemeral filesystems. Files in `data/interactive/` are
lost on restart unless S3 is configured. The SQLite database is not affected
because `DATABASE_URL` points to the PostgreSQL addon.

### Using a different OAuth provider

The buildpack supports any provider supported by oauth2-proxy. Example for
ProConnect (French government SSO):

```bash
scalingo --app matometa env-set \
  OAUTH2_PROXY_PROVIDER=oidc \
  OAUTH2_PROXY_OIDC_ISSUER_URL=<proconnect-issuer-url> \
  OAUTH2_PROXY_SCOPE="openid given_name usual_name email profile" \
  OAUTH2_PROXY_EMAIL_DOMAINS=beta.gouv.fr
```
