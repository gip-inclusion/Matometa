#!/usr/bin/env bash
# First-time setup for expert mode test infrastructure.
# Run after: make expert-up
#
# This script:
# 1. Waits for Gitea to be ready (usually a few seconds)
# 2. Creates admin user and API token
# 3. Creates 'matometa' organization
# 4. Waits for Coolify, enables API, creates admin + token
# 5. Writes tokens to .env
set -euo pipefail

GITEA_URL="${GITEA_URL:-http://localhost:3300}"
COOLIFY_URL="${COOLIFY_URL:-http://localhost:8001}"
GITEA_CONTAINER="${GITEA_CONTAINER:-matometa-gitea}"
COOLIFY_CONTAINER="${COOLIFY_CONTAINER:-coolify}"
ENV_FILE=".env"

EXPERT_ADMIN_USER="${EXPERT_ADMIN_USER:-matometa}"
EXPERT_ADMIN_EMAIL="${EXPERT_ADMIN_EMAIL:-admin@matometa.dev}"
EXPERT_ADMIN_PASS="${EXPERT_ADMIN_PASS:-$(openssl rand -hex 18)}"

echo "=== Expert mode test setup ==="
echo "Gitea URL:   $GITEA_URL"
echo "Coolify URL: $COOLIFY_URL"
echo "Admin email: $EXPERT_ADMIN_EMAIL"
echo ""

# ── 1. Wait for Gitea ──────────────────────────────────────────────
echo "Waiting for Gitea to be ready..."
for i in $(seq 1 60); do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$GITEA_URL/api/v1/version" --max-time 5 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        echo "Gitea is ready!"
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "ERROR: Gitea did not become ready in 5 minutes"
        exit 1
    fi
    printf "."
    sleep 5
done
echo ""

# ── 2. Create Gitea admin user ─────────────────────────────────────
echo "Creating Gitea admin user..."
docker exec -u git "$GITEA_CONTAINER" gitea admin user create \
    --username "$EXPERT_ADMIN_USER" \
    --password "$EXPERT_ADMIN_PASS" \
    --email "$EXPERT_ADMIN_EMAIL" \
    --admin \
    --must-change-password=false 2>/dev/null || echo "(user may already exist)"

# Enforce expected password so reruns stay deterministic.
docker exec -u git "$GITEA_CONTAINER" gitea admin user change-password \
    --username "$EXPERT_ADMIN_USER" \
    --password "$EXPERT_ADMIN_PASS" \
    --must-change-password=false >/dev/null 2>&1 || true

# ── 3. Create API token ────────────────────────────────────────────
echo "Creating API token..."
# Delete existing token with same name if any
curl -s -X DELETE "$GITEA_URL/api/v1/users/$EXPERT_ADMIN_USER/tokens/matometa-api" \
    -u "$EXPERT_ADMIN_USER:$EXPERT_ADMIN_PASS" 2>/dev/null || true

TOKEN_RESPONSE=$(curl -s -X POST "$GITEA_URL/api/v1/users/$EXPERT_ADMIN_USER/tokens" \
    -u "$EXPERT_ADMIN_USER:$EXPERT_ADMIN_PASS" \
    -H "Content-Type: application/json" \
    -d '{"name": "matometa-api", "scopes": ["all"]}')

GITEA_API_TOKEN=$(echo "$TOKEN_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('sha1', ''))" 2>/dev/null || echo "")

if [ -z "$GITEA_API_TOKEN" ]; then
    echo "ERROR: Failed to create Gitea API token"
    echo "Response: $TOKEN_RESPONSE"
    exit 1
fi
echo "Token created: ${GITEA_API_TOKEN:0:10}..."

# ── 4. Create 'matometa' organization ──────────────────────────────
GITEA_ORG_NAME="apps"
echo "Creating '$GITEA_ORG_NAME' organization..."
ORG_RESPONSE=$(curl -s -X POST "$GITEA_URL/api/v1/orgs" \
    -H "Authorization: token $GITEA_API_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"username\": \"$GITEA_ORG_NAME\", \"visibility\": \"private\"}")

ORG_NAME=$(echo "$ORG_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('username', ''))" 2>/dev/null || echo "")
if [ -z "$ORG_NAME" ]; then
    # Org might already exist, check
    ORG_CHECK=$(curl -s "$GITEA_URL/api/v1/orgs/$GITEA_ORG_NAME" \
        -H "Authorization: token $GITEA_API_TOKEN" 2>/dev/null)
    ORG_NAME=$(echo "$ORG_CHECK" | python3 -c "import sys,json; print(json.load(sys.stdin).get('username', ''))" 2>/dev/null || echo "")
fi
echo "Organization: $ORG_NAME"

# ── 5. Wait for Coolify ─────────────────────────────────────────────
echo ""
echo "Waiting for Coolify..."
COOLIFY_API_TOKEN=""
for i in $(seq 1 60); do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$COOLIFY_URL/" --max-time 5 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ] || [ "$HTTP_CODE" = "302" ]; then
        echo "Coolify is ready!"
        break
    fi
    if [ "$i" -eq 60 ]; then
        echo "WARNING: Coolify not ready after 5 minutes, skipping Coolify setup"
        break
    fi
    printf "."
    sleep 5
done
echo ""

# ── 6. Setup Coolify (admin user + API token) ───────────────────────
if curl -s -o /dev/null -w "%{http_code}" "$COOLIFY_URL/" --max-time 5 2>/dev/null | grep -qE "200|302"; then
    echo "Setting up Coolify..."

    # Create admin user via artisan
    docker exec "$COOLIFY_CONTAINER" php artisan tinker --execute="
        \$user = \App\Models\User::firstWhere('email', '${EXPERT_ADMIN_EMAIL}');
        if (!\$user) {
            \$user = \App\Models\User::create([
                'name' => 'Matometa Dev',
                'email' => '${EXPERT_ADMIN_EMAIL}',
                'password' => bcrypt('${EXPERT_ADMIN_PASS}'),
            ]);
            echo 'User created';
        } else {
            \$user->password = bcrypt('${EXPERT_ADMIN_PASS}');
            \$user->save();
            echo 'User exists';
        }
    " 2>/dev/null

    # Enable API
    docker exec "$COOLIFY_CONTAINER" php artisan tinker --execute="
        \$s = \App\Models\InstanceSettings::find(0);
        if (\$s) { \$s->is_api_enabled = true; \$s->save(); echo 'API enabled'; }
    " 2>/dev/null

    # Create API token (need team_id)
    COOLIFY_API_TOKEN=$(docker exec "$COOLIFY_CONTAINER" php artisan tinker --execute="
        \$user = \App\Models\User::first();
        \$team = \$user->teams()->first();
        if (\$team) {
            \$plain = \Illuminate\Support\Str::random(40);
            \$t = \$user->tokens()->create([
                'name' => 'matometa-api',
                'token' => hash('sha256', \$plain),
                'abilities' => ['*'],
                'team_id' => \$team->id,
            ]);
            echo \$t->id . '|' . \$plain;
        } else {
            echo 'NO_TEAM';
        }
    " 2>/dev/null | grep -v "Restricted Mode" | tail -1)

    if [ -z "$COOLIFY_API_TOKEN" ] || [ "$COOLIFY_API_TOKEN" = "NO_TEAM" ]; then
        echo "WARNING: Could not create Coolify API token"
        COOLIFY_API_TOKEN=""
    else
        echo "Coolify token created: ${COOLIFY_API_TOKEN:0:10}..."
    fi
fi

# ── 7. Write to .env ────────────────────────────────────────────────
echo ""
echo "Updating $ENV_FILE..."

# Remove old expert mode vars if present
if [ -f "$ENV_FILE" ]; then
    sed -i '/^GITEA_API_TOKEN=/d' "$ENV_FILE"
    sed -i '/^GITEA_URL=/d' "$ENV_FILE"
    sed -i '/^GITEA_ORG=/d' "$ENV_FILE"
    sed -i '/^COOLIFY_API_TOKEN=/d' "$ENV_FILE"
    sed -i '/^COOLIFY_URL=/d' "$ENV_FILE"
    # Also clean up old GitLab vars
    sed -i '/^GITLAB_API_TOKEN=/d' "$ENV_FILE"
    sed -i '/^GITLAB_NAMESPACE_ID=/d' "$ENV_FILE"
    sed -i '/^GITLAB_URL=/d' "$ENV_FILE"
fi

# Use host.docker.internal for Docker containers to reach services on host
DOCKER_GITEA_URL=$(echo "$GITEA_URL" | sed 's|localhost|host.docker.internal|')
DOCKER_COOLIFY_URL=$(echo "$COOLIFY_URL" | sed 's|localhost|host.docker.internal|')

cat >> "$ENV_FILE" << EOF

# Expert mode (auto-generated by setup_expert_test.sh)
GITEA_URL=$DOCKER_GITEA_URL
GITEA_API_TOKEN=$GITEA_API_TOKEN
GITEA_ORG=apps
COOLIFY_URL=$DOCKER_COOLIFY_URL
COOLIFY_API_TOKEN=$COOLIFY_API_TOKEN
EXPERT_ADMIN_USER=$EXPERT_ADMIN_USER
EXPERT_ADMIN_EMAIL=$EXPERT_ADMIN_EMAIL
EXPERT_ADMIN_PASS=$EXPERT_ADMIN_PASS
EOF

echo ""
echo "=== Setup complete ==="
echo "Gitea:   $GITEA_URL (user: $EXPERT_ADMIN_USER)"
echo "  Token: ${GITEA_API_TOKEN:0:10}..."
echo "  Org:   matometa"
if [ -n "$COOLIFY_API_TOKEN" ]; then
    echo "Coolify: $COOLIFY_URL (user: $EXPERT_ADMIN_EMAIL)"
    echo "  Token: ${COOLIFY_API_TOKEN:0:10}..."
else
    echo "Coolify: not configured (setup manually at $COOLIFY_URL)"
fi
echo "Admin password saved to $ENV_FILE as EXPERT_ADMIN_PASS"
echo ""
echo "Restart Matometa to pick up the new config:"
echo "  docker compose up -d --build matometa"
