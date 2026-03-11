# speckit_deploy — Deploy project to staging or production

## When to use

Use this skill after implementing changes to deploy the project. It handles the full pipeline: commit, push, validate, build, deploy, and verify.

## Available commands

```bash
# Deploy staging (most common)
python -m skills.speckit_deploy.scripts.deploy --project-id <uuid> --env staging

# Deploy production
python -m skills.speckit_deploy.scripts.deploy --project-id <uuid> --env production

# Validate only (dry-run)
python -m skills.speckit_deploy.scripts.deploy --project-id <uuid> --validate-only
```

## What it does

1. **Commit & push** — calls `commit_and_push_staging_if_changed()` to ensure code is in Gitea
2. **Validate compose** — checks `docker-compose.yml` for port issues, exposed DB ports
3. **Validate build context** — checks that Dockerfile and volume-mounted files exist
4. **Deploy** — builds Docker image and starts containers
5. **Health check** — waits up to 30s for the app to respond on its assigned port
6. **Report** — shows deploy URL, status, and container logs if something failed

## On failure

If deployment fails, the script automatically:
- Shows the last 50 lines of container logs
- Lists any validation warnings (missing files, bad ports)
- Suggests concrete next steps

**Do NOT retry blindly.** Read the logs first and fix the root cause.

## Prerequisites

- `docker-compose.yml` must exist in the project root
- Port mapping must use `${HOST_PORT}` (never hardcode)
- Dockerfile must exist if `build:` is used in compose

## Notes

- Accepts both project slug and UUID as `--project-id`
- The staging environment uses ports 18080–19999
- The production environment uses ports 28080–29999
