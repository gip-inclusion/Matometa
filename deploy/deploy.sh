#!/bin/bash
# Deploy Matometa to ljt.cc
# Usage: ./deploy/deploy.sh

set -e

SERVER="matometa@ljt.cc"
REMOTE_DIR="/srv/matometa"
LOCAL_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== Deploying Matometa to $SERVER ==="

# Files to sync (excludes data, .env, __pycache__, etc.)
RSYNC_OPTS=(
    -avz
    --delete
    --exclude='.git'
    --exclude='__pycache__'
    --exclude='*.pyc'
    --exclude='.pytest_cache'
    --exclude='.DS_Store'
    --exclude='data/'
    --exclude='.env'
    --exclude='.venv'
    --exclude='/scripts/'
    --exclude='reports/'
    --exclude='claude-credentials/'
    --exclude='.claude/skills'
)

echo "Syncing files..."
rsync "${RSYNC_OPTS[@]}" "$LOCAL_DIR/" "$SERVER:$REMOTE_DIR/"

echo "Ensuring symlinks..."
ssh "$SERVER" "cd $REMOTE_DIR/.claude && ln -sf ../skills skills 2>/dev/null || true"

echo "Rebuilding container..."
ssh "$SERVER" "cd $REMOTE_DIR && docker compose up -d --build"

echo "Verifying deployment..."
ssh "$SERVER" "docker exec matometa-matometa-1 cat /app/.claude/settings.json 2>/dev/null || echo 'Warning: Could not verify .claude/settings.json'"

echo "=== Deployment complete ==="
echo "App available at: https://matometa.ljt.cc"
