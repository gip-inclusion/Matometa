#!/usr/bin/env python3
"""Standalone deploy CLI for expert-mode projects.

Independent of the agent — can be run manually, by cron, or via webhook.
The agent can also call this via Bash tool for troubleshooting.

Usage:
    python -m scripts.deploy status                     # All projects
    python -m scripts.deploy status <slug>              # One project
    python -m scripts.deploy staging <slug>             # Deploy staging
    python -m scripts.deploy production <slug>          # Deploy production
    python -m scripts.deploy logs <slug> [--env ENV]    # View logs
    python -m scripts.deploy restart <slug> [--env ENV] # Restart
    python -m scripts.deploy stop <slug> [--env ENV]    # Stop
    python -m scripts.deploy validate <slug>            # Check compose file
    python -m scripts.deploy health                     # Health check all
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from lib import docker_deploy
from web.database import ConversationStore


def cmd_status(args):
    store = ConversationStore()
    if args.slug:
        project = store.get_project_by_slug(args.slug)
        if not project:
            print(f"Project not found: {args.slug}")
            return 1
        for env in ("staging", "production"):
            st = docker_deploy.status(project.id, env)
            if st["status"] != "not_deployed":
                print(f"{args.slug}/{env}: {st['status']}")
                for c in st.get("containers", []):
                    print(f"  {c['name']}: {c['state']} ({c['status_text']})")
    else:
        projects = store.list_projects(limit=500)
        for project in projects:
            for env in ("staging", "production"):
                deploy_url = (project.staging_deploy_url if env == "staging"
                              else project.production_deploy_url)
                if not deploy_url:
                    continue
                st = docker_deploy.status(project.id, env)
                status = st.get("status", "unknown")
                print(f"{project.slug:20s} {env:12s} {status:15s} {deploy_url}")
    return 0


def cmd_deploy(args, environment):
    store = ConversationStore()
    project = store.get_project_by_slug(args.slug)
    if not project:
        print(f"Project not found: {args.slug}")
        return 1

    print(f"Deploying {args.slug}/{environment}...")
    result = docker_deploy.deploy(project.id, environment)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "running" else 1


def cmd_logs(args):
    store = ConversationStore()
    project = store.get_project_by_slug(args.slug)
    if not project:
        print(f"Project not found: {args.slug}")
        return 1

    log_text = docker_deploy.logs(project.id, args.env, lines=args.lines)
    print(log_text)
    return 0


def cmd_restart(args):
    store = ConversationStore()
    project = store.get_project_by_slug(args.slug)
    if not project:
        print(f"Project not found: {args.slug}")
        return 1

    result = docker_deploy.restart(project.id, args.env)
    print(json.dumps(result, indent=2))
    return 0 if result.get("status") == "running" else 1


def cmd_stop(args):
    store = ConversationStore()
    project = store.get_project_by_slug(args.slug)
    if not project:
        print(f"Project not found: {args.slug}")
        return 1

    result = docker_deploy.stop(project.id, args.env)
    print(json.dumps(result, indent=2))
    return 0


def cmd_validate(args):
    store = ConversationStore()
    project = store.get_project_by_slug(args.slug)
    if not project:
        print(f"Project not found: {args.slug}")
        return 1

    warnings = docker_deploy.validate_compose(project.id)
    if warnings:
        for w in warnings:
            print(f"WARNING: {w}")
        return 1
    print("OK: compose file looks good")
    return 0


def cmd_health(args):
    results = docker_deploy.health_check_all()
    for key, status in sorted(results.items()):
        print(f"{key:30s} {status}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Deploy CLI for expert-mode projects")
    sub = parser.add_subparsers(dest="command")

    p_status = sub.add_parser("status", help="Show deployment status")
    p_status.add_argument("slug", nargs="?", help="Project slug (omit for all)")

    p_staging = sub.add_parser("staging", help="Deploy staging")
    p_staging.add_argument("slug", help="Project slug")

    p_prod = sub.add_parser("production", help="Deploy production")
    p_prod.add_argument("slug", help="Project slug")

    p_logs = sub.add_parser("logs", help="View container logs")
    p_logs.add_argument("slug", help="Project slug")
    p_logs.add_argument("--env", default="staging", choices=["staging", "production"])
    p_logs.add_argument("--lines", type=int, default=100)

    p_restart = sub.add_parser("restart", help="Restart containers")
    p_restart.add_argument("slug", help="Project slug")
    p_restart.add_argument("--env", default="staging", choices=["staging", "production"])

    p_stop = sub.add_parser("stop", help="Stop containers")
    p_stop.add_argument("slug", help="Project slug")
    p_stop.add_argument("--env", default="staging", choices=["staging", "production"])

    p_validate = sub.add_parser("validate", help="Validate compose file")
    p_validate.add_argument("slug", help="Project slug")

    sub.add_parser("health", help="Health check all projects")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if not docker_deploy.docker_available():
        print("ERROR: Docker is not available")
        return 1

    handlers = {
        "status": cmd_status,
        "staging": lambda a: cmd_deploy(a, "staging"),
        "production": lambda a: cmd_deploy(a, "production"),
        "logs": cmd_logs,
        "restart": cmd_restart,
        "stop": cmd_stop,
        "validate": cmd_validate,
        "health": cmd_health,
    }

    return handlers[args.command](args)


if __name__ == "__main__":
    sys.exit(main() or 0)
