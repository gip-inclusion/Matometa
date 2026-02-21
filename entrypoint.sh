#!/bin/bash
set -e

# Remove stale SQLite WAL/SHM files if not writable by current user.
# These can be left by other host users (e.g. meduse-agent running sqlite3 directly)
# with a different UID. The data dir is owned by matometa, so we can always delete
# files in it. SQLite will recreate them with correct ownership on next open.
for f in /app/data/*.db-wal /app/data/*.db-shm; do
    [ -f "$f" ] && [ ! -w "$f" ] && rm -f "$f" && echo "Removed stale $f"
done

exec "$@"
