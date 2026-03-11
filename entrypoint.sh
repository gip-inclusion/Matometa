#!/bin/sh
# Start the process manager in background, then run uvicorn
python -m web.pm &
PM_PID=$!

# Keep OAuth token alive (check every 10 minutes, refresh if < 1h remaining)
(sleep 10; while true; do
  python -c "
from web.claude_credentials import ensure_valid_token
ensure_valid_token()
" 2>&1 | head -5
  sleep 600
done) &
REFRESH_PID=$!

# Health check: restart crashed project containers every 60s
(sleep 30; while true; do
  python -c "
from lib.docker_deploy import health_check_all, docker_available
if docker_available():
    health_check_all()
" 2>/dev/null
  sleep 60
done) &
HEALTH_PID=$!

trap "kill $PM_PID $REFRESH_PID $HEALTH_PID" EXIT
exec uvicorn web.app:app --host 0.0.0.0 --port "${WEB_PORT:-5000}"
