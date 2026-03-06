#!/usr/bin/env python3
"""One-time migration: assign random 2-word slugs to existing projects.

Only renames projects that still have generic 'nouveau-projet-*' slugs.
Also renames the Gitea repo to match the new slug.

Usage:
    python -m scripts.migrate_slugs              # dry run
    python -m scripts.migrate_slugs --apply      # apply changes
"""

import argparse
import logging
import re
import sys
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib.slugs import generate_slug
from web.database import ConversationStore, get_db
from web import config

logging.basicConfig(level=logging.INFO, format="%(message)s")
log = logging.getLogger(__name__)

GENERIC_SLUG_RE = re.compile(r"^nouveau-projet(-\d+)?$")


def migrate(apply: bool = False):
    store = ConversationStore()
    projects = store.list_projects(limit=500)

    # Collect existing slugs to avoid collisions
    existing_slugs = {p.slug for p in projects}
    to_rename = [p for p in projects if GENERIC_SLUG_RE.match(p.slug)]

    if not to_rename:
        log.info("No projects with generic slugs found. Nothing to do.")
        return

    log.info("Found %d projects to rename:", len(to_rename))

    gitea = None
    if apply and config.GITEA_URL and config.GITEA_API_TOKEN:
        from lib.gitea import GiteaClient
        gitea = GiteaClient()

    for project in to_rename:
        new_slug = generate_slug(existing_slugs)
        existing_slugs.add(new_slug)

        log.info("  %s -> %s  (name: %s)", project.slug, new_slug, project.name)

        if not apply:
            continue

        # Update DB
        store.update_project(project.id, slug=new_slug)

        # Rename Gitea repo if it exists
        if gitea and project.gitea_url:
            try:
                old_slug = project.slug
                resp = gitea._session.patch(
                    gitea._url(f"/repos/{config.GITEA_ORG}/{old_slug}"),
                    json={"name": new_slug},
                )
                if resp.status_code == 200:
                    new_url = project.gitea_url.replace(old_slug, new_slug)
                    store.update_project(project.id, gitea_url=new_url)
                    log.info("    Gitea repo renamed: %s -> %s", old_slug, new_slug)
                elif resp.status_code == 404:
                    log.info("    Gitea repo %s not found, skipping rename", old_slug)
                else:
                    log.warning("    Gitea rename failed (%d): %s", resp.status_code, resp.text[:200])
            except Exception as e:
                log.warning("    Gitea rename error: %s", e)

    if apply:
        log.info("Done. %d projects renamed.", len(to_rename))
    else:
        log.info("\nDry run. Use --apply to apply changes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Apply changes (default is dry run)")
    args = parser.parse_args()
    migrate(apply=args.apply)
