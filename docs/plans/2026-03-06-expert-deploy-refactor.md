# Expert Mode Deploy Pipeline — Refactor Plan

**Date**: 2026-03-06
**Status**: Proposed
**Problem**: The current Coolify-based auto-deploy pipeline is brittle and has accumulated band-aids. Every project deployment requires manual intervention.

## Root Causes

### 1. Coolify API is not designed for programmatic app management
- Creating apps via API leads to misconfigured build packs, wrong ports, missing SSH keys, stale branches
- The `dockercompose` vs `dockerfile` build pack choice happens at creation time and is hard to fix later
- Port mappings, env vars, and branch names get out of sync between matometa DB and Coolify DB
- Coolify's helper container approach for git clone adds complexity (SSH key injection, DNS resolution)
- Error feedback is opaque — Coolify returns "deployment failed" with buried logs

### 2. Too many moving parts for port management
- Host ports must be unique across all apps (18080-19999 for staging, 28080-29999 for production)
- `dockerfile` apps use `ports_mappings` in Coolify; `dockercompose` apps use `HOST_PORT` env var
- Port detection from Dockerfile `EXPOSE` is unreliable (runs before files exist, defaults to 5000)
- Port conflicts with Coolify's own services (Traefik on 8080, PostgreSQL on 5432)

### 3. Generic slug naming
- All projects start as "Nouveau projet" → `nouveau-projet-N`
- Gitea repos, Coolify apps, and Docker containers all use these generic names
- Hard to identify which project is which in Docker, Coolify UI, or Gitea

### 4. No health checks or self-healing
- If a Coolify app crashes, preview returns a cryptic "Impossible de joindre" forever
- No automatic redeploy on failure
- Stuck conversations from crashed CLI processes
- OAuth token expiry breaks the entire agent backend

## Proposed Architecture

### Option A: Simplify — Docker Compose directly (no Coolify)

**Drop Coolify entirely.** Matometa manages Docker directly.

```
matometa container
  → creates project workdir with Dockerfile + docker-compose.yml
  → runs `docker compose -f /projects/{id}/docker-compose.yml up -d`
  → reverse-proxies via existing preview route
```

**Pros:**
- No Coolify API, no SSH key dance, no helper containers
- Direct control: `docker compose up/down/logs/ps`
- Port management in one place (matometa assigns, writes to compose)
- Git push to Gitea still works for versioning, but deploy is decoupled
- Health checks via `docker inspect` directly

**Cons:**
- Need Docker socket access in matometa container (already have it for some operations)
- No Coolify UI for manual inspection (but we rarely use it)
- Need to implement log viewing, restart, and basic lifecycle management

### Option B: Keep Coolify but with guardrails

**Keep Coolify but add a reconciliation layer.**

- On every deploy request, fully reconcile Coolify app state before triggering
- Single build pack: always `dockercompose` (agent always generates a compose file)
- Template-based compose generation with `${HOST_PORT}` baked in
- Idempotent Coolify app creation (check-or-create pattern)

**Cons:**
- Still fighting Coolify's assumptions
- Two sources of truth (matometa DB + Coolify DB)

### Option C: Hybrid — Coolify for routing, Docker for build

Use Coolify only for Traefik routing (subdomain → container), manage builds ourselves.

---

## Recommendation: Option A

Coolify adds more complexity than value for this use case. The expert mode needs:
1. Build a Docker image from project code
2. Run it with the right ports
3. Proxy HTTP to it
4. Show logs and status

All of this can be done with `docker compose` + the existing preview proxy.

## Implementation Plan (Option A)

### Phase 1: Slug & naming (quick win)
- Generate slugs as 2 random words (e.g. `brave-falcon`, `quiet-river`) using a wordlist
- Use slug for: Gitea repo name, Docker project name, preview URL
- Add rename support that updates Gitea repo name

### Phase 2: Direct Docker management
- New `lib/docker_deploy.py` replacing `lib/coolify.py`
  - `deploy(project_id)` → builds image, starts compose, returns port
  - `status(project_id)` → container health, port, uptime
  - `logs(project_id, lines=50)` → container logs
  - `stop(project_id)` / `restart(project_id)`
- Compose template with `${HOST_PORT}` injected by matometa
- Port allocation: simple counter in DB, no scanning
- Mount Docker socket in matometa container (`/var/run/docker.sock`)

### Phase 3: Agent-generated compose files
- Agent MUST produce a `docker-compose.yml` (enforce in system prompt)
- Template includes: app service, optional db service, healthcheck
- `HOST_PORT` is the only external variable
- DB services use named volumes (persist across redeploys)

### Phase 4: Health & self-healing
- Startup: check all project containers, restart crashed ones
- Preview proxy: if container is stopped, auto-restart before returning 502
- Background health poll every 60s, auto-restart exited containers
- Token refresh loop (already implemented)

### Phase 5: Cleanup
- Remove `lib/coolify.py`
- Remove Coolify from `docker-compose.yml` (or keep for other uses)
- Remove all port reconciliation, branch fixing, build pack detection code
- Simplify `_ensure_staging_application` to just `deploy_project()`

## CI/CD: Automated git-push-to-deploy

### Current state (Coolify)
Coolify registers a webhook on the Gitea repo. On `git push`, Gitea POSTs to Coolify, which clones the repo via SSH (helper container), builds, and deploys. This is fragile: SSH key injection fails, DNS resolution inside Coolify's helper container is unreliable, and error feedback is opaque.

### Proposed: Gitea webhook → matometa API

```
git push → Gitea webhook POST → matometa /api/webhooks/gitea/{project_id}
  → matometa pulls code (git clone/pull in project workdir)
  → docker compose build && docker compose up -d
  → updates deploy status in DB
  → returns result to webhook response
```

**Implementation:**
1. New API endpoint: `POST /api/webhooks/gitea/<project_id>` (secret-authenticated)
2. On receive: validate HMAC signature, extract branch from payload
3. `git pull` in `/projects/{slug}/` workdir (or `git clone` on first deploy)
4. Run `docker compose -f /projects/{slug}/docker-compose.yml build --no-cache`
5. Run `docker compose up -d`
6. Store deploy result (success/fail, timestamp, commit SHA) in DB
7. Register webhook on Gitea repo at project creation time via Gitea API

**Webhook payload contains:** branch, commit SHA, pusher — enough to decide whether to deploy staging or production.

**Branch strategy:**
- Push to `main` → deploy staging
- Push to `production` or tag → deploy production
- Other branches → ignore

**No external CI runner needed.** Matometa itself is the CI/CD engine. Builds happen on the same Docker host.

### Agent-triggered deploys (no git push)

The agent can also trigger deploys directly after writing code:
```
agent writes files → git add/commit/push to Gitea → webhook fires → auto-deploy
```
Or skip git entirely for draft deploys:
```
agent writes files → matometa calls docker compose up -d directly
```

Both paths converge on the same `deploy(project_id)` function.

---

## Domains & Routing

### Current state
- Coolify's Traefik handles subdomain routing (e.g., `nouveau-projet-10.matometa.dev`)
- Preview proxy in matometa rewrites `host.docker.internal:{port}` — works but fragile
- No real domain setup for project apps; users access via matometa's preview route

### Proposed: Three routing tiers

#### Tier 1: Port-based preview (default, no DNS needed)
Keep the existing preview proxy route:
```
GET /expert/{slug}/preview/staging/  → proxy to localhost:{staging_port}
GET /expert/{slug}/preview/production/ → proxy to localhost:{prod_port}
```
This works today. No DNS, no TLS, no Traefik config. Suitable for development and internal review.

#### Tier 2: Subdomain routing via Traefik (optional)
For projects that need a real URL (e.g., demos, user testing):
```
{slug}-staging.projects.{DOMAIN} → localhost:{staging_port}
{slug}.projects.{DOMAIN}         → localhost:{prod_port}
```

**Implementation:**
- Deploy a standalone Traefik instance (not Coolify's) in the matometa stack
- Use Docker labels on project containers for dynamic routing:
  ```yaml
  labels:
    - "traefik.enable=true"
    - "traefik.http.routers.${SLUG}-staging.rule=Host(`${SLUG}-staging.projects.${DOMAIN}`)"
    - "traefik.http.services.${SLUG}-staging.loadbalancer.server.port=${CONTAINER_PORT}"
  ```
- Traefik auto-discovers containers via Docker socket — zero config per app
- Wildcard DNS: `*.projects.{DOMAIN}` → server IP (single DNS record)
- Wildcard TLS via Let's Encrypt DNS challenge (Cloudflare/OVH API)

#### Tier 3: Custom domains (future)
For production apps that need their own domain:
- Add `custom_domain` field to project DB
- Generate Traefik router rule with `Host(custom_domain)`
- User points their DNS to server IP
- Let's Encrypt issues per-domain cert automatically

### Traefik config (standalone)

```yaml
# In matometa's docker-compose.yml
traefik:
  image: traefik:v3
  command:
    - "--providers.docker=true"
    - "--providers.docker.exposedbydefault=false"
    - "--providers.docker.network=matometa-projects"
    - "--entrypoints.web.address=:80"
    - "--entrypoints.websecure.address=:443"
    - "--certificatesresolvers.letsencrypt.acme.dnschallenge=true"
    - "--certificatesresolvers.letsencrypt.acme.dnschallenge.provider=cloudflare"
  ports:
    - "80:80"
    - "443:443"
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock:ro
    - traefik-certs:/letsencrypt
  networks:
    - matometa-projects
```

All project containers join the `matometa-projects` Docker network so Traefik can route to them.

---

## Reverse Proxy Details

### Dropping Coolify's Traefik
Coolify runs its own Traefik on ports 80/443. When we drop Coolify:
- Those ports become available for our standalone Traefik
- No conflict between Coolify's routing rules and ours
- Coolify can remain installed for other uses (just stop its Traefik)

### Preview proxy improvements
The existing `/expert/{slug}/preview/{env}/` route currently does:
```python
resp = requests.get(f"http://host.docker.internal:{port}{path}")
```

Improvements for the refactor:
1. **WebSocket support** — proxy `Upgrade: websocket` headers for hot-reload
2. **Streaming** — use `stream=True` for large responses (file downloads)
3. **Error pages** — if container is stopped, show status page with "Restart" button (already partially implemented)
4. **Auto-restart** — if container exited, restart it before returning 502

---

## Slug System Design (Phase 1)

### 2-random-word slugs

Generate human-readable, unique slugs like `brave-falcon`, `quiet-river`.

**Implementation:**
```python
# lib/slugs.py
import random

ADJECTIVES = [
    "bold", "brave", "calm", "cool", "dark", "deep", "fast", "fine",
    "glad", "gold", "good", "gray", "keen", "kind", "lean", "long",
    "loud", "mild", "neat", "nice", "pale", "pure", "rare", "rich",
    "safe", "slim", "soft", "sure", "tall", "tidy", "vast", "warm",
    "wide", "wild", "wise", "young", "quick", "quiet", "sharp", "sweet",
    # ~50 adjectives
]

NOUNS = [
    "atlas", "badge", "bloom", "cedar", "cloud", "coral", "crane", "delta",
    "dune", "ember", "fern", "flame", "forge", "frost", "grove", "haven",
    "heron", "ivory", "jewel", "lake", "lark", "maple", "marsh", "mist",
    "moon", "oasis", "olive", "pearl", "pine", "plume", "prism", "quail",
    "ridge", "river", "sage", "shell", "shore", "spark", "stone", "storm",
    "swift", "thorn", "tide", "vale", "wave", "wren", "zephyr", "falcon",
    # ~50 nouns
]

def generate_slug(existing_slugs: set[str] | None = None) -> str:
    """Generate a unique 2-word slug."""
    for _ in range(100):
        slug = f"{random.choice(ADJECTIVES)}-{random.choice(NOUNS)}"
        if existing_slugs is None or slug not in existing_slugs:
            return slug
    raise RuntimeError("Could not generate unique slug after 100 attempts")
```

~50 adjectives × ~50 nouns = ~2500 unique combinations. More than enough for the expected project count (<100).

**Usage:**
- On project creation: `project.slug = generate_slug(existing_slugs)`
- Slug used for: Gitea repo name, Docker project name, container name prefix, preview URL path
- User can rename project → slug stays the same (or optionally regenerate)

### Migration for existing projects
- Existing `nouveau-projet-N` projects: assign random slugs
- Update Gitea repo names via API (`PATCH /repos/{owner}/{old_name}`)
- Update Docker container names on next deploy
- DB migration: ensure `slug` column is unique, not null

---

## Migration

### Step-by-step migration path
1. **Implement slug system** (Phase 1) — can be done independently
2. **Build `lib/docker_deploy.py`** — test alongside Coolify (both can run)
3. **Add webhook endpoint** — register on new projects only
4. **Migrate existing projects one by one:**
   - Stop Coolify app via API
   - Clone repo to `/projects/{slug}/`
   - `docker compose up -d` with assigned port
   - Verify preview works
   - Remove Coolify app
5. **Deploy standalone Traefik** (Tier 2) — optional, only if subdomain routing needed
6. **Remove Coolify** — stop Coolify containers, remove from matometa's compose file
7. **DB cleanup** — drop `coolify_app_uuid`, `coolify_project_uuid` columns

### Rollback
Each phase is independently reversible. Coolify apps can be recreated from Gitea repos at any time.

### Timeline estimate
- Phase 1 (slugs): standalone, no dependencies
- Phase 2 (docker_deploy): core change, enables everything else
- Phase 3 (compose templates): depends on Phase 2
- Phase 4 (health): depends on Phase 2
- Phase 5 (cleanup): after all projects migrated
- Traefik (Tier 2): independent, can happen anytime after Phase 2
