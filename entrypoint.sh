#!/bin/sh
# PM runs in-process via FastAPI lifespan (web/app.py) — no separate subprocess needed.
exec /app/.venv/bin/python -m uvicorn web.app:app --host 0.0.0.0 --port "${WEB_PORT:-5000}"
