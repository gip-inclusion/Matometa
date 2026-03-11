#!/usr/bin/env python3
"""Deploy skill script — full pipeline: commit, validate, deploy, verify.

Usage:
    python -m skills.speckit_deploy.scripts.deploy --project-id <slug-or-uuid> --env staging
    python -m skills.speckit_deploy.scripts.deploy --project-id <slug-or-uuid> --validate-only
"""

import argparse
import sys
import time
from pathlib import Path
from urllib.request import urlopen
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent))

from lib import docker_deploy
from lib.expert_git import commit_and_push_staging_if_changed
from web.database import ConversationStore


def resolve_project(store, identifier: str):
    """Resolve project by slug or UUID."""
    project = store.get_project_by_slug(identifier)
    if project:
        return project
    return store.get_project(identifier)


def health_check(url: str, timeout: int = 30) -> bool:
    """Wait for app to respond at URL."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = urlopen(url, timeout=5)
            if resp.status < 500:
                return True
        except (URLError, OSError, Exception):
            pass
        time.sleep(2)
    return False


def main():
    parser = argparse.ArgumentParser(description="Deploy project (full pipeline)")
    parser.add_argument("--project-id", required=True, help="Project slug or UUID")
    parser.add_argument("--env", default="staging", choices=["staging", "production"])
    parser.add_argument("--validate-only", action="store_true", help="Only validate, don't deploy")
    args = parser.parse_args()

    store = ConversationStore()
    project = resolve_project(store, args.project_id)
    if not project:
        print(f"ERROR: Project not found: {args.project_id}")
        print("Available projects:")
        for p in store.list_projects(limit=100):
            print(f"  {p.slug:20s} {p.id}")
        return 1

    print(f"Project: {project.slug} ({project.id})")
    env = args.env

    # Step 1: Commit and push
    print("\n--- Step 1: Commit & Push ---")
    try:
        result = commit_and_push_staging_if_changed(project)
        if result:
            print(f"Committed: {result['commit']} on {result['branch']} ({len(result['files'])} files)")
        else:
            print("No changes to commit")
    except Exception as e:
        print(f"WARNING: Git commit/push failed: {e}")
        print("Continuing with deploy (code may already be pushed)...")

    # Step 2: Validate compose
    print("\n--- Step 2: Validate ---")
    warnings = docker_deploy.validate_compose(project.id)
    context_warnings = docker_deploy.validate_build_context(project.id)
    all_warnings = warnings + context_warnings

    if all_warnings:
        for w in all_warnings:
            print(f"  WARNING: {w}")
    else:
        print("  OK: compose and build context look good")

    if args.validate_only:
        return 1 if all_warnings else 0

    # Step 3: Check Docker
    if not docker_deploy.docker_available():
        print("\nERROR: Docker is not available")
        return 1

    # Step 4: Deploy
    print(f"\n--- Step 3: Deploy {env} ---")
    result = docker_deploy.deploy(project.id, env)
    print(f"Status: {result['status']}")

    if result["status"] not in ("running",):
        print(f"ERROR: {result.get('error', 'unknown')}")
        if result.get("warnings"):
            print("\nValidation warnings:")
            for w in result["warnings"]:
                print(f"  - {w}")
        if result.get("logs"):
            print(f"\n--- Container logs ---")
            print(result["logs"][-2000:])
        print("\nFix the issue above before retrying.")
        return 1

    deploy_url = result.get("deploy_url", f"http://localhost:{result.get('port')}")
    print(f"Deploy URL: {deploy_url}")

    # Step 5: Health check
    print(f"\n--- Step 4: Health Check ---")
    print(f"Waiting for {deploy_url} to respond...")
    if health_check(deploy_url, timeout=30):
        print(f"OK: App is healthy at {deploy_url}")
    else:
        print(f"WARNING: App did not respond within 30s at {deploy_url}")
        log_text = docker_deploy.logs(project.id, env, lines=50)
        if log_text and log_text != "No logs available":
            print(f"\n--- Container logs ---")
            print(log_text[-2000:])
        print("\nCheck logs above. The container may still be starting.")
        return 1

    print(f"\nDone: {project.slug}/{env} deployed at {deploy_url}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
