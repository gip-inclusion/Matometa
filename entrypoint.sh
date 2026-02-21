#!/bin/bash
set -e

# Fix ownership of data directory — handles files created by other host users
# (e.g. meduse-agent running sqlite3 directly, leaving WAL/SHM owned by UID 1003)
chown -R matometa:matometa /app/data 2>/dev/null || true

exec gosu matometa "$@"
