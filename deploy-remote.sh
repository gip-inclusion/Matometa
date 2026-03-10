#!/usr/bin/env bash
# Deploy matometa to a remote server via SSH + Docker Compose.
# Usage: ./deploy-remote.sh [ssh-host] [--quick]
#   --quick: hot-patch code into running container (no rebuild)
# Default host: scaleway-app (defined in ~/.ssh/config)
#
# Prerequisites: SSH key loaded in agent (see ~/.ssh/config.d/project-keys.conf)
set -euo pipefail

HOST="${1:-scaleway-app}"
QUICK=false
[[ "${2:-}" == "--quick" || "${1:-}" == "--quick" ]] && QUICK=true
[[ "${1:-}" == "--quick" ]] && HOST="scaleway-app"

REMOTE_DIR="/opt/matometa"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"
CONTAINER="matometa-matometa-1"

echo "==> Deploying matometa to $HOST:$REMOTE_DIR"

# --- Quick deploy: sync files + hot-patch into running container ---
if $QUICK; then
    echo "==> Quick deploy (no rebuild)..."
    rsync -az --delete \
        --exclude='.venv/' --exclude='__pycache__/' --exclude='.git/' \
        --exclude='data/' --exclude='claude-credentials/' --exclude='*.pyc' \
        --exclude='.env' --exclude='node_modules/' \
        --exclude='.mypy_cache/' --exclude='.pytest_cache/' \
        "$PROJECT_DIR/" "$HOST:$REMOTE_DIR/"

    echo "==> Patching running container..."
    ssh "$HOST" "docker cp $REMOTE_DIR/web $CONTAINER:/app/web && \
                 docker cp $REMOTE_DIR/skills $CONTAINER:/app/skills && \
                 docker cp $REMOTE_DIR/lib $CONTAINER:/app/lib 2>/dev/null; true"

    echo "==> Restarting processes inside container..."
    ssh "$HOST" "docker exec $CONTAINER kill -TERM 7 2>/dev/null; true"
    sleep 3
    ssh "$HOST" "curl -sf http://localhost:5002/ >/dev/null && echo 'OK: matometa responding' || echo 'WARN: not responding yet'"
    echo "==> Quick deploy done."
    exit 0
fi

# --- Full deploy below ---

# --- Step 1: Install Docker on remote if missing ---
echo "==> Checking Docker on remote..."
ssh "$HOST" 'command -v docker >/dev/null 2>&1' || {
    echo "==> Installing Docker..."
    ssh "$HOST" 'apt-get update -qq && apt-get install -y -qq ca-certificates curl && install -m 0755 -d /etc/apt/keyrings && curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc && chmod a+r /etc/apt/keyrings/docker.asc && echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo $VERSION_CODENAME) stable" > /etc/apt/sources.list.d/docker.list && apt-get update -qq && apt-get install -y -qq docker-ce docker-ce-cli containerd.io docker-compose-plugin'
}

# --- Step 2: Create remote directory structure ---
echo "==> Preparing remote directories..."
ssh "$HOST" "mkdir -p $REMOTE_DIR/data $REMOTE_DIR/claude-credentials"

# --- Step 3: Sync project files (excludes data, credentials, venv, git) ---
echo "==> Syncing project files..."
rsync -az --delete \
    --exclude='.venv/' \
    --exclude='__pycache__/' \
    --exclude='.git/' \
    --exclude='data/' \
    --exclude='claude-credentials/' \
    --exclude='*.pyc' \
    --exclude='.env' \
    --exclude='node_modules/' \
    --exclude='.mypy_cache/' \
    --exclude='.pytest_cache/' \
    "$PROJECT_DIR/" "$HOST:$REMOTE_DIR/"

# --- Step 4: Sync Claude credentials (best-effort) ---
# Copy from host's ~/.claude if local credentials dir is empty
echo "==> Syncing Claude credentials..."
if [ -d "$PROJECT_DIR/claude-credentials" ] && [ -f "$PROJECT_DIR/claude-credentials/.credentials.json" ]; then
    rsync -az --ignore-errors "$PROJECT_DIR/claude-credentials/" "$HOST:$REMOTE_DIR/claude-credentials/" 2>/dev/null || true
else
    # Populate from host's own Claude login
    ssh "$HOST" "cp -f /root/.claude/.credentials.json $REMOTE_DIR/claude-credentials/.credentials.json 2>/dev/null; chown 1004:1004 $REMOTE_DIR/claude-credentials/.credentials.json 2>/dev/null" || true
fi

# --- Step 5: Write production .env (only if missing) ---
ssh "$HOST" "test -f $REMOTE_DIR/.env" || {
    echo "==> Writing default production .env..."
    ssh "$HOST" "cat > $REMOTE_DIR/.env" << 'ENVEOF'
# Production config — matometa on scaleway-app
AGENT_BACKEND=cli
SKIP_CLI_AUTH_CHECK=true

WEB_HOST=0.0.0.0
WEB_PORT=5000
WEB_DEBUG=false

ADMIN_USERS=admin@localhost
DEFAULT_USER=admin@localhost

# Ollama (remote GPU server) — set OLLAMA_HOST before running deploy
OLLAMA_BASE_URL=http://\${OLLAMA_HOST:?Set OLLAMA_HOST in env}:11434
OLLAMA_MODEL=qwen2.5-coder:14b-32k
OLLAMA_TITLE_MODEL=qwen2.5-coder:14b
OLLAMA_TAG_MODEL=qwen2.5-coder:14b

# Expert mode
GITEA_URL=http://host.docker.internal:3300
GITEA_ORG=apps
COOLIFY_URL=http://host.docker.internal:8001

# Not using PG/MinIO (SQLite mode)
POSTGRES_PASSWORD=not-used
MINIO_ROOT_PASSWORD=not-used
ENVEOF
}

# --- Step 6: Fix volume ownership (UID 1004 = matometa in container) ---
echo "==> Fixing data directory permissions..."
ssh "$HOST" "chown -R 1004:1004 $REMOTE_DIR/data $REMOTE_DIR/claude-credentials"

# --- Step 6b: Ensure Coolify deploy key + SSH config for Gitea ---
echo "==> Setting up Coolify-Gitea SSH bridge..."
ssh "$HOST" bash -s << 'SSHEOF'
  # Extract Coolify's private key and derive the public key
  COOLIFY_KEY_FILE=$(docker exec coolify find /var/www/html/storage/app/ssh/ -type f -name 'ssh_key@*' 2>/dev/null | head -1)
  if [ -n "$COOLIFY_KEY_FILE" ]; then
    docker cp "coolify:$COOLIFY_KEY_FILE" /root/.ssh/coolify_deploy_key 2>/dev/null
    chmod 600 /root/.ssh/coolify_deploy_key

    # Ensure SSH config for matometa-gitea
    if ! grep -q 'Host matometa-gitea' /root/.ssh/config 2>/dev/null; then
      cat >> /root/.ssh/config << 'SSHCFG'

Host matometa-gitea
  HostName matometa-gitea
  User git
  IdentityFile /root/.ssh/coolify_deploy_key
  StrictHostKeyChecking no
SSHCFG
      chmod 600 /root/.ssh/config
    fi

    # Register public key in Gitea (idempotent)
    GITEA_TOKEN=$(docker exec matometa-matometa-1 printenv GITEA_API_TOKEN 2>/dev/null || true)
    if [ -n "$GITEA_TOKEN" ]; then
      PUBKEY=$(ssh-keygen -y -f /root/.ssh/coolify_deploy_key 2>/dev/null)
      EXISTING=$(curl -sf http://localhost:3300/api/v1/user/keys -H "Authorization: token $GITEA_TOKEN" | grep -c coolify-deploy 2>/dev/null || echo 0)
      if [ "$EXISTING" = "0" ] && [ -n "$PUBKEY" ]; then
        curl -sf -X POST http://localhost:3300/api/v1/user/keys \
          -H "Authorization: token $GITEA_TOKEN" \
          -H "Content-Type: application/json" \
          -d "{\"title\":\"coolify-deploy\",\"key\":\"$PUBKEY coolify-deploy\"}" >/dev/null 2>&1 || true
      fi
    fi
  fi

  # Install/refresh gitea hosts timer
  if [ -f /opt/matometa/deploy/update-gitea-hosts.sh ]; then
    chmod +x /opt/matometa/deploy/update-gitea-hosts.sh
    cp /opt/matometa/deploy/update-gitea-hosts.service /etc/systemd/system/ 2>/dev/null || true
    cp /opt/matometa/deploy/update-gitea-hosts.timer /etc/systemd/system/ 2>/dev/null || true
    systemctl daemon-reload
    systemctl enable --now update-gitea-hosts.timer 2>/dev/null || true
    /opt/matometa/deploy/update-gitea-hosts.sh
  fi
SSHEOF

# --- Step 6c: Set Docker GID for socket access ---
echo "==> Detecting Docker GID..."
ssh "$HOST" "grep -q '^DOCKER_GID=' $REMOTE_DIR/.env 2>/dev/null || echo \"DOCKER_GID=\$(stat -c '%g' /var/run/docker.sock)\" >> $REMOTE_DIR/.env"

# --- Step 7: Build and start (slim Dockerfile, public port) ---
echo "==> Building image..."
ssh "$HOST" "cd $REMOTE_DIR && $COMPOSE build"

echo "==> Starting containers..."
ssh "$HOST" "cd $REMOTE_DIR && $COMPOSE up -d"

# --- Step 8: Clean up build cache (tight disk) ---
echo "==> Cleaning build cache..."
ssh "$HOST" "docker builder prune -af >/dev/null 2>&1" || true

# --- Step 9: Verify ---
echo "==> Waiting for startup..."
sleep 5
ssh "$HOST" "cd $REMOTE_DIR && $COMPOSE ps && curl -sf http://localhost:5002/ >/dev/null && echo 'OK: matometa responding on :5002' || echo 'WARN: not responding yet'"

REMOTE_IP=$(ssh -G "$HOST" | awk '/^hostname / {print $2}')
echo "==> Done. Access at http://${REMOTE_IP}:5002/"
