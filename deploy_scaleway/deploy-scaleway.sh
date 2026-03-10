#!/usr/bin/env bash
# Deploy matometa + expert mode stack to Scaleway server.
# Run from your laptop:  bash deploy/deploy-scaleway.sh
set -euo pipefail

SERVER="scaleway"              # SSH alias (defined in ~/.ssh/config)
REMOTE_DIR="~/matometa"
COMPOSE="docker compose -f deploy/docker-compose.scaleway.yml --project-directory ."
PUBLIC_IP=$(ssh -G "$SERVER" | awk '/^hostname / {print $2}')

echo "=== Deploying matometa to Scaleway ($PUBLIC_IP) ==="
echo ""

# ── 1. Sync repo ────────────────────────────────────────────────────
echo "[1/4] Syncing repo to $SERVER:$REMOTE_DIR ..."
rsync -az --delete \
    --exclude '.venv' \
    --exclude '__pycache__' \
    --exclude '.env' \
    --exclude 'data/' \
    --exclude 'claude-credentials/' \
    --exclude '.pytest_cache' \
    --exclude '.git' \
    --exclude 'node_modules' \
    ./ "$SERVER:$REMOTE_DIR/"
echo "  Sync complete."

# ── 2. Copy env template if no .env exists ──────────────────────────
echo "[2/4] Ensuring .env exists on server..."
ssh "$SERVER" "cd $REMOTE_DIR && [ -f .env ] || cp deploy/env.scaleway .env && echo '  Copied env.scaleway -> .env' || echo '  .env already exists'"

# ── 3. Build and start the stack ────────────────────────────────────
echo "[3/4] Building and starting Docker stack..."
ssh "$SERVER" "cd $REMOTE_DIR && $COMPOSE build && $COMPOSE up -d"
echo "  Stack is starting."

# ── 4. First-time setup (Gitea admin, tokens, Coolify admin) ───────
echo "[4/4] Running expert mode setup..."
ssh "$SERVER" "cd $REMOTE_DIR && bash scripts/setup_expert_test.sh"

# ── 5. Rebuild matometa to pick up new .env tokens ─────────────────
echo ""
echo "Rebuilding matometa with new tokens..."
ssh "$SERVER" "cd $REMOTE_DIR && $COMPOSE up -d --build matometa"

echo ""
echo "=== Deploy complete ==="
echo ""
echo "Access URLs:"
echo "  Matometa:  http://$PUBLIC_IP:5002/"
echo "  Gitea:     http://$PUBLIC_IP:3300/"
echo "  Coolify:   http://$PUBLIC_IP:8001/"
echo ""
echo "Verify:"
echo "  curl http://$PUBLIC_IP:5002/"
echo "  curl http://$PUBLIC_IP:3300/api/v1/version"
echo "  curl http://$PUBLIC_IP:8001/"
