"""Expert mode routes — separate UI section for vibecoded apps."""

import asyncio
import logging
import secrets
import socket
import subprocess
from urllib.parse import urljoin, urlsplit, urlunsplit

import requests as http_requests
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from ..storage import store
from .. import config
from ..deps import get_current_user, templates
from lib.expert_git import (
    authenticated_clone_url,
    commit_and_push_staging_if_changed,
    extract_owner_repo_from_url,
    ensure_local_git_repo as ensure_project_local_git_repo,
    ensure_project_branches,
    promote_staging_to_production,
    run_git as _run_git,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# =============================================================================
# Helpers
# =============================================================================

def _authenticated_clone_url(repo_path: str) -> str:
    """Build an authenticated HTTP clone URL for Gitea using the configured token."""
    return authenticated_clone_url(repo_path)


def _extract_owner_repo_from_url(repo_url: str) -> tuple[str, str]:
    """Extract owner/repo from an HTTP(S) Gitea URL."""
    return extract_owner_repo_from_url(repo_url)


def _normalize_deploy_url(raw_domains) -> str | None:
    """Normalize Coolify 'domains' response into a usable URL."""
    if isinstance(raw_domains, list):
        domain = next((d for d in raw_domains if d), None)
    else:
        domain = raw_domains

    if not domain:
        return None

    domain = str(domain).strip()
    if not domain:
        return None

    if domain.startswith("http://") or domain.startswith("https://"):
        return domain

    return f"http://{domain}"


def _publicize_deploy_url(url: str | None, request: Request | None = None) -> str | None:
    """Return a browser-reachable URL for the current requester.

    Deploy URLs are stored as localhost in local Docker setups. When users access
    Matometa from another machine, localhost points to the wrong host for them.
    In that case, rewrite localhost URLs to the current request host (or explicit
    EXPERT_DEPLOY_PUBLIC_HOST when configured).
    """
    if not url:
        return url

    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if host not in {"localhost", "127.0.0.1"}:
        return url

    target_host = config.EXPERT_DEPLOY_PUBLIC_HOST or ""
    if not target_host and request is not None:
        req_host = (request.headers.get("host") or "").split(":", 1)[0].strip()
        if req_host and req_host not in {"localhost", "127.0.0.1", "testserver"}:
            target_host = req_host

    if not target_host:
        return url

    netloc = f"{target_host}:{parsed.port}" if parsed.port else target_host
    scheme = parsed.scheme or "http"
    return urlunsplit((scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _project_to_public_dict(project, request: Request | None = None) -> dict:
    """Serialize project and rewrite deploy URLs for current requester."""
    payload = project.to_dict()
    for field in ("deploy_url", "staging_deploy_url", "production_deploy_url"):
        value = _publicize_deploy_url(payload.get(field), request)
        payload[f"{field}_technical"] = value
        payload[field] = value
    payload["staging_preview_url"] = _preview_url(project.slug, "staging")
    payload["production_preview_url"] = _preview_url(project.slug, "production")
    return payload


def _preview_base_path(slug: str, environment: str) -> str:
    return f"/expert/{slug}/preview/{environment}"


def _preview_url(slug: str, environment: str) -> str:
    return f"{_preview_base_path(slug, environment)}/"


def _environment_deploy_url(project, environment: str) -> str | None:
    if environment == "staging":
        return project.staging_deploy_url or project.deploy_url
    if environment == "production":
        return project.production_deploy_url
    return None


def _internal_proxy_url(url: str) -> str:
    """Rewrite localhost URLs for container-side proxy access."""
    parsed = urlsplit(url)
    host = (parsed.hostname or "").lower()
    if host not in {"localhost", "127.0.0.1"}:
        return url

    netloc = "host.docker.internal"
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunsplit((parsed.scheme or "http", netloc, parsed.path, parsed.query, parsed.fragment))


def _rewrite_proxy_html(content: str, slug: str, environment: str) -> str:
    """Rewrite root-relative links in proxied HTML to stay under preview path."""
    base = _preview_base_path(slug, environment)
    content = content.replace('href="/', f'href="{base}/')
    content = content.replace("href='/", f"href='{base}/")
    content = content.replace('src="/', f'src="{base}/')
    content = content.replace("src='/", f"src='{base}/")
    content = content.replace('action="/', f'action="{base}/')
    content = content.replace("action='/", f"action='{base}/")
    if "<head" in content and "<base " not in content:
        head_close = content.find(">", content.find("<head"))
        if head_close != -1:
            injection = f'<base href="{_preview_url(slug, environment)}">'
            content = content[: head_close + 1] + injection + content[head_close + 1 :]
    # Inject a script to rewrite JS-assigned form.action with absolute paths
    # (e.g. form.action = '/orders/5/status' -> '/expert/slug/preview/env/orders/5/status')
    if "</body>" in content:
        patch_script = (
            f'<script>(function(){{'
            f'var B="{base}";'
            f'var _set=Object.getOwnPropertyDescriptor(HTMLFormElement.prototype,"action").set;'
            f'Object.defineProperty(HTMLFormElement.prototype,"action",{{'
            f'set:function(v){{if(typeof v==="string"&&v.startsWith("/")&&!v.startsWith(B))v=B+v;_set.call(this,v)}},'
            f'get:function(){{return this.getAttribute("action")||""}}}})'
            f'}})();</script>'
        )
        content = content.replace("</body>", patch_script + "</body>")
    return content


def _detect_exposed_port(workdir) -> int:
    """Read EXPOSE from Dockerfile to determine the container port. Defaults to 5000."""
    dockerfile = workdir / "Dockerfile"
    if dockerfile.exists():
        import re
        for line in dockerfile.read_text().splitlines():
            m = re.match(r"^\s*EXPOSE\s+(\d+)", line, re.IGNORECASE)
            if m:
                return int(m.group(1))
    return 5000


def _pick_host_port(start: int = 18080, end: int | None = 19999, reserved_ports: set[int] | None = None) -> int:
    """Pick a free host port for direct app exposure.

    Uses reserved_ports (from existing project deploy URLs) as the primary check.
    Falls back to socket bind on 0.0.0.0 when running outside containers.
    """
    reserved = reserved_ports or set()
    if end is None or end < start:
        end = start + 2000
    for port in range(start, end + 1):
        if port in reserved:
            continue
        return port
    raise RuntimeError("No free host port available for Coolify app mapping")


def _use_local_direct_port_mode() -> bool:
    """Use host port mappings when Coolify runs in local Docker dev mode."""
    host = (urlsplit(config.COOLIFY_URL).hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "host.docker.internal"}


def _local_deploy_url(port: int) -> str:
    """Build a browser URL for a direct host port mapping."""
    return f"http://localhost:{port}"


def _extract_host_port_mapping(ports_mappings: str | None) -> int | None:
    """Extract host port from Coolify ports_mappings format (e.g. 18080:5000)."""
    if not ports_mappings:
        return None

    first = str(ports_mappings).split(",", 1)[0].strip()
    if not first or ":" not in first:
        return None

    host_part = first.split(":", 1)[0].strip()
    if not host_part.isdigit():
        return None

    return int(host_part)


def _reserved_local_deploy_ports(exclude_project_id: str | None = None) -> set[int]:
    """Collect host ports already assigned in project deploy URLs."""
    used = set()
    for project in store.list_projects(limit=2000):
        if exclude_project_id and project.id == exclude_project_id:
            continue
        for candidate in (
            project.deploy_url,
            project.staging_deploy_url,
            project.production_deploy_url,
        ):
            if not candidate:
                continue
            parsed = urlsplit(candidate)
            if parsed.hostname != "localhost" or not parsed.port:
                continue
            used.add(parsed.port)
    return used


def _ensure_deployable_repo(project):
    """Ensure repo contains Dockerfile + docker-compose.yml for deployment.

    Returns True when files were added and pushed, False otherwise.
    """
    workdir = config.PROJECTS_DIR / project.id
    if not (workdir / ".git").exists():
        return False

    dockerfile = workdir / "Dockerfile"
    compose_file = workdir / "docker-compose.yml"

    # If both exist, nothing to do
    if dockerfile.exists() and compose_file.exists():
        return False

    # If neither exists, this is a brand new project — bootstrap both
    created_files = []

    if not dockerfile.exists():
        dockerfile.write_text(
            "FROM python:3.12-slim\n"
            "WORKDIR /app\n"
            "COPY . /app\n"
            "EXPOSE 5000\n"
            "CMD [\"python\", \"-m\", \"http.server\", \"5000\", \"--bind\", \"0.0.0.0\"]\n"
        )
        created_files.append("Dockerfile")

    if not compose_file.exists():
        # Generate compose from Dockerfile's EXPOSE port
        container_port = _detect_exposed_port(workdir)
        compose_file.write_text(
            "services:\n"
            "  app:\n"
            "    build: .\n"
            "    ports:\n"
            f'      - "${{HOST_PORT:-{container_port}}}:{container_port}"\n'
            "    healthcheck:\n"
            f'      test: ["CMD", "curl", "-f", "http://localhost:{container_port}/"]\n'
            "      interval: 10s\n"
            "      timeout: 5s\n"
            "      retries: 3\n"
            "    restart: unless-stopped\n"
        )
        created_files.append("docker-compose.yml")

    gitignore = workdir / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(
            "__pycache__/\n"
            "*.pyc\n"
            ".env\n"
            ".venv/\n"
            "node_modules/\n"
            ".DS_Store\n"
            "*.egg-info/\n"
            "dist/\n"
            "build/\n"
        )
        created_files.append(".gitignore")

    pyproject = workdir / "pyproject.toml"
    if not pyproject.exists():
        pyproject.write_text(
            "[tool.ruff]\n"
            "target-version = \"py312\"\n"
            "line-length = 120\n"
            "\n"
            "[tool.ruff.lint]\n"
            'select = ["E", "F", "W", "I", "UP", "S", "B"]\n'
            'ignore = ["S101"]\n'
        )
        created_files.append("pyproject.toml")

    index_html = workdir / "index.html"
    if not index_html.exists() and "Dockerfile" in created_files:
        safe_name = (project.name or project.slug or "Application").replace("<", "").replace(">", "")
        index_html.write_text(
            "<!doctype html>\n"
            "<html lang=\"fr\">\n"
            "<head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{safe_name}</title></head>\n"
            "<body style=\"font-family: sans-serif; margin: 2rem;\">\n"
            f"<h1>{safe_name}</h1>\n"
            "<p>L'application est deployee. Vous pouvez maintenant la faire evoluer dans cette conversation.</p>\n"
            "</body></html>\n"
        )
        created_files.append("index.html")

    if not created_files:
        return False

    try:
        _run_git(workdir, "config", "user.email", "matometa@localhost")
        _run_git(workdir, "config", "user.name", "Matometa")
        _run_git(workdir, "add", *created_files)
        diff = _run_git(workdir, "diff", "--cached", "--name-only")
        if not diff:
            return False

        _run_git(workdir, "commit", "-m", "chore: add deployment bootstrap")
        current_branch = _run_git(workdir, "rev-parse", "--abbrev-ref", "HEAD") or "main"
        _run_git(workdir, "push", "origin", current_branch)
        logger.info("Bootstrapped deploy files for project %s: %s", project.id, created_files)
        return True
    except Exception:
        logger.exception("Failed to bootstrap deploy files for project %s", project.id)
        return False


def _ensure_local_git_repo(project):
    """Ensure project working directory is a valid local git clone.

    For legacy projects created before auto-clone existed, this imports existing
    files into a fresh clone and pushes them to origin.
    """
    return ensure_project_local_git_repo(project)


def _try_create_gitea_repo(project):
    """Auto-create a Gitea repo and clone it into the project working directory.

    Non-blocking: logs errors but never raises.
    """
    if not config.GITEA_API_TOKEN:
        return
    try:
        from lib.gitea import GiteaClient
        import requests as _requests
        gitea = GiteaClient()
        try:
            repo = gitea.create_repo(
                name=project.slug,
                description=project.description or "",
            )
        except _requests.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 409:
                # Repo already exists — fetch it instead
                repo = gitea.get_repo(config.GITEA_ORG, project.slug)
            else:
                raise
        gitea_id = repo.get("id")
        gitea_url = repo.get("html_url", "")
        full_name = repo.get("full_name", "")  # e.g. "apps/nouveau-projet"

        # Clone repo into project working directory so the agent can commit/push
        workdir = config.PROJECTS_DIR / project.id
        if full_name and not (workdir / ".git").exists():
            clone_url = _authenticated_clone_url(full_name)
            workdir.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["git", "clone", clone_url, str(workdir)],
                check=True, capture_output=True, timeout=30,
            )
            # Configure git user for commits inside the container
            subprocess.run(
                ["git", "config", "user.email", "matometa@localhost"],
                cwd=workdir, check=True, capture_output=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Matometa"],
                cwd=workdir, check=True, capture_output=True,
            )
            logger.info("Cloned repo into %s", workdir)

        # Ensure dedicated expert workflow branches are present.
        ensure_project_branches(project)

        store.update_project(
            project.id,
            gitea_repo_id=gitea_id,
            gitea_url=gitea_url,
            staging_branch=project.staging_branch,
            production_branch=project.production_branch,
            status="active",
        )

        # Optionally bootstrap staging deployment right after repository creation.
        # This keeps staging permanently available for auto-redeploy on push.
        if config.COOLIFY_API_TOKEN:
            try:
                from lib.coolify import CoolifyClient

                refreshed = store.get_project(project.id) or project
                _ensure_local_git_repo(refreshed)
                ensure_project_branches(refreshed)
                _ensure_deployable_repo(refreshed)

                coolify = CoolifyClient()
                app_uuid, _ = _ensure_staging_application(refreshed, coolify)
                if app_uuid:
                    coolify.deploy(app_uuid)
            except Exception:
                logger.exception("Failed to bootstrap staging deploy for project %s", project.id)

        logger.info("Auto-created Gitea repo %s for project %s", gitea_url, project.id)
    except Exception:
        logger.exception("Failed to auto-create Gitea repo for project %s", project.id)


def _setup_gitea_webhook(project, app_uuid, coolify, branch_filter: str | None = None):
    """Set up Gitea->Coolify webhook for auto-redeploy on push.

    Non-blocking: logs errors but never raises.
    """
    try:
        from lib.gitea import GiteaClient

        # Get or generate webhook secret on the Coolify app
        secret = coolify.get_webhook_secret(app_uuid)
        if not secret:
            secret = secrets.token_hex(32)
            coolify.set_webhook_secret(app_uuid, secret)

        # Build webhook URL using internal (container-to-container) address
        webhook_url = f"{config.COOLIFY_INTERNAL_URL}/webhooks/source/gitea/events/manual"

        owner, repo = _extract_owner_repo_from_url(project.gitea_url)

        gitea = GiteaClient()
        gitea.create_webhook(owner, repo, webhook_url, secret, branch_filter=branch_filter)
        logger.info("Created Gitea webhook for %s/%s -> Coolify %s", owner, repo, app_uuid)
    except Exception:
        logger.exception("Failed to set up Gitea webhook for project %s", project.id)


def _sync_legacy_deploy_fields(project_id: str, *, app_uuid: str | None, deploy_url: str | None):
    """Keep legacy single-deploy fields populated for backwards compatibility."""
    updates = {}
    if app_uuid is not None:
        updates["coolify_app_uuid"] = app_uuid
    if deploy_url is not None:
        updates["deploy_url"] = deploy_url
    if updates:
        store.update_project(project_id, **updates)


def _create_coolify_application(
    *,
    coolify,
    project,
    app_name: str,
    git_branch: str,
    local_port_start: int,
) -> tuple[str | None, str | None]:
    """Create a Coolify app and return (app_uuid, deploy_url)."""
    servers = coolify.list_servers()
    if not servers:
        raise RuntimeError("No Coolify server available")
    server_uuid = servers[0]["uuid"]

    coolify_proj = coolify.create_project(
        name=app_name,
        description=project.description or "",
    )

    owner, repo = _extract_owner_repo_from_url(project.gitea_url)
    ssh_repo_url = f"git@matometa-gitea:{owner}/{repo}.git"
    deploy_key_uuid = coolify.get_deploy_key_uuid("gitea")

    ports_mappings = None
    deploy_url = None
    host_port = None
    if _use_local_direct_port_mode():
        reserved_ports = _reserved_local_deploy_ports(exclude_project_id=project.id)
        host_port = _pick_host_port(start=local_port_start, reserved_ports=reserved_ports)
        deploy_url = _local_deploy_url(host_port)

    # Use docker-compose if project has one, otherwise plain Dockerfile
    workdir = config.PROJECTS_DIR / project.id
    has_compose = (workdir / "docker-compose.yml").exists() or (workdir / "docker-compose.yaml").exists()
    build_pack = "dockercompose" if has_compose else "dockerfile"

    # For dockerfile build pack, Coolify uses ports_mappings directly.
    # For dockercompose, port mapping is in the compose file via HOST_PORT env var.
    if host_port and build_pack == "dockerfile":
        container_port = _detect_exposed_port(workdir)
        ports_mappings = f"{host_port}:{container_port}"

    result = coolify.create_application(
        name=app_name,
        git_repo_url=ssh_repo_url,
        git_branch=git_branch,
        server_uuid=server_uuid,
        project_uuid=coolify_proj["uuid"],
        ports_mappings=ports_mappings,
        private_key_uuid=deploy_key_uuid,
        build_pack=build_pack,
    )
    app_uuid = result.get("uuid", "")

    # For dockercompose apps, set HOST_PORT env var so compose file can use ${HOST_PORT}
    if host_port and build_pack == "dockercompose" and app_uuid:
        try:
            coolify.create_env_var(app_uuid, "HOST_PORT", str(host_port))
        except Exception as exc:
            logger.warning("Failed to set HOST_PORT env var on %s: %s", app_uuid, exc)

    if not deploy_url:
        deploy_url = _normalize_deploy_url(result.get("domains"))

    return app_uuid, deploy_url


def _reconcile_coolify_app(app_uuid: str, app_state: dict, project, coolify,
                           port_range_start: int, branch: str):
    """Fix common Coolify app misconfigurations in-place.

    - Upgrades dockerfile → dockercompose when project has a compose file
    - Sets HOST_PORT env var for dockercompose apps
    - Fixes stale branch names (e.g. stagging → staging)
    """
    workdir = config.PROJECTS_DIR / project.id
    has_compose = (workdir / "docker-compose.yml").exists() or (workdir / "docker-compose.yaml").exists()
    current_bp = app_state.get("build_pack", "dockerfile")
    current_branch = app_state.get("git_branch", "")

    patches = {}

    # Upgrade to dockercompose if project has a compose file
    if has_compose and current_bp != "dockercompose":
        patches["build_pack"] = "dockercompose"
        patches["docker_compose_location"] = "/docker-compose.yml"
        # Set HOST_PORT env var from existing port mapping
        mapped_port = _extract_host_port_mapping(app_state.get("ports_mappings"))
        if not mapped_port:
            reserved = _reserved_local_deploy_ports(exclude_project_id=project.id)
            mapped_port = _pick_host_port(start=port_range_start, reserved_ports=reserved)
        try:
            coolify.create_env_var(app_uuid, "HOST_PORT", str(mapped_port))
        except Exception:
            pass  # env var may already exist
        logger.info("Upgrading %s to dockercompose (HOST_PORT=%s)", app_uuid, mapped_port)

    # Fix branch name
    if branch and current_branch != branch:
        patches["git_branch"] = branch
        logger.info("Fixing branch for %s: %s → %s", app_uuid, current_branch, branch)

    # Fix wrong container port in port mapping (for dockerfile apps)
    if current_bp == "dockerfile" and not has_compose:
        expected_port = _detect_exposed_port(workdir)
        current_mapping = app_state.get("ports_mappings") or ""
        if ":" in current_mapping:
            host_p, container_p = current_mapping.split(",")[0].split(":")
            if int(container_p) != expected_port:
                patches["ports_mappings"] = f"{host_p}:{expected_port}"
                patches["ports_exposes"] = str(expected_port)
                logger.info("Fixing port for %s: %s → %s:%s", app_uuid, current_mapping, host_p, expected_port)

    if patches:
        try:
            coolify._session.patch(coolify._url(f"/applications/{app_uuid}"), json=patches)
        except Exception:
            logger.exception("Failed to reconcile Coolify app %s", app_uuid)


def _ensure_staging_application(project, coolify):
    """Ensure staging app exists, is reachable, and webhook is configured."""
    staging_branch = project.staging_branch or config.EXPERT_STAGING_BRANCH

    app_uuid = project.staging_coolify_app_uuid
    deploy_url = project.staging_deploy_url

    if app_uuid:
        if _use_local_direct_port_mode():
            app_state = coolify.get_status(app_uuid)
            build_pack = app_state.get("build_pack", "dockerfile")
            _reconcile_coolify_app(app_uuid, app_state, project, coolify,
                                   port_range_start=18080, branch=staging_branch)
            if build_pack == "dockercompose":
                # Port managed by compose via HOST_PORT env var
                mapped_port = _extract_host_port_mapping(app_state.get("ports_mappings"))
                if mapped_port:
                    deploy_url = _local_deploy_url(mapped_port)
            else:
                mapped_port = _extract_host_port_mapping(app_state.get("ports_mappings"))
                reserved_ports = _reserved_local_deploy_ports(exclude_project_id=project.id)
                if not mapped_port or mapped_port in reserved_ports:
                    workdir = config.PROJECTS_DIR / project.id
                    container_port = _detect_exposed_port(workdir)
                    mapped_port = _pick_host_port(start=18080, reserved_ports=reserved_ports)
                    coolify.set_ports_mapping(app_uuid, f"{mapped_port}:{container_port}")
                deploy_url = _local_deploy_url(mapped_port)
    else:
        app_uuid, deploy_url = _create_coolify_application(
            coolify=coolify,
            project=project,
            app_name=f"{project.slug}-staging",
            git_branch=staging_branch,
            local_port_start=18080,
        )

    store.update_project(
        project.id,
        staging_coolify_app_uuid=app_uuid,
        staging_deploy_url=deploy_url,
        status="deployed" if deploy_url else project.status,
    )
    _sync_legacy_deploy_fields(project.id, app_uuid=app_uuid, deploy_url=deploy_url)

    if app_uuid:
        _setup_gitea_webhook(project, app_uuid, coolify, branch_filter=staging_branch)

    return app_uuid, deploy_url


def _ensure_production_application(project, coolify):
    """Ensure production app exists and URL mapping is valid."""
    production_branch = project.production_branch or config.EXPERT_PRODUCTION_BRANCH

    app_uuid = project.production_coolify_app_uuid
    deploy_url = project.production_deploy_url

    if app_uuid:
        if _use_local_direct_port_mode():
            app_state = coolify.get_status(app_uuid)
            build_pack = app_state.get("build_pack", "dockerfile")
            _reconcile_coolify_app(app_uuid, app_state, project, coolify,
                                   port_range_start=28080, branch=production_branch)
            if build_pack == "dockercompose":
                mapped_port = _extract_host_port_mapping(app_state.get("ports_mappings"))
                if mapped_port:
                    deploy_url = _local_deploy_url(mapped_port)
            else:
                mapped_port = _extract_host_port_mapping(app_state.get("ports_mappings"))
                reserved_ports = _reserved_local_deploy_ports(exclude_project_id=project.id)
                if not mapped_port or mapped_port in reserved_ports:
                    workdir = config.PROJECTS_DIR / project.id
                    container_port = _detect_exposed_port(workdir)
                    mapped_port = _pick_host_port(start=28080, reserved_ports=reserved_ports)
                    coolify.set_ports_mapping(app_uuid, f"{mapped_port}:{container_port}")
                deploy_url = _local_deploy_url(mapped_port)
    else:
        app_uuid, deploy_url = _create_coolify_application(
            coolify=coolify,
            project=project,
            app_name=f"{project.slug}-prod",
            git_branch=production_branch,
            local_port_start=28080,
        )

    store.update_project(
        project.id,
        production_coolify_app_uuid=app_uuid,
        production_deploy_url=deploy_url,
        status="deployed" if deploy_url else project.status,
    )
    _sync_legacy_deploy_fields(project.id, app_uuid=app_uuid, deploy_url=deploy_url)

    if app_uuid:
        _setup_gitea_webhook(project, app_uuid, coolify, branch_filter=production_branch)

    return app_uuid, deploy_url


def _get_expert_sidebar_data(user_email=None):
    """Get sidebar data for expert mode pages."""
    from .html import get_sidebar_data
    return get_sidebar_data(user_email)


# =============================================================================
# HTML pages
# =============================================================================

@router.get("/expert")
def expert_home(request: Request, user_email: str = Depends(get_current_user)):
    """Expert mode landing: list of user's projects + new project button."""
    if not config.EXPERT_MODE_ENABLED:
        raise HTTPException(status_code=404)

    projects = store.list_projects(user_id=user_email)

    data = _get_expert_sidebar_data(user_email)
    return templates.TemplateResponse(request, "expert/home.html", {
        "section": "expert",
        "current_conv": None,
        "projects": projects,
        **data,
    })


@router.get("/expert/nouveau")
def expert_new(user_email: str = Depends(get_current_user)):
    """Create new expert app -> redirects to conversation in plan mode."""
    if not config.EXPERT_MODE_ENABLED:
        raise HTTPException(status_code=404)

    project = store.create_project(name="Nouveau projet", user_id=user_email)

    # Initialize .specify/ structure for spec-driven workflow
    workdir = config.PROJECTS_DIR / project.id
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        from skills.speckit_init.scripts.init_project import init_specify
        init_specify(str(workdir))
    except Exception:
        logger.exception("Failed to init .specify/ for project %s", project.id)

    conv = store.create_conversation(
        conv_type="project", project_id=project.id, user_id=user_email
    )

    # Run Gitea repo creation in background (frontend triggers /welcome for speckit)
    import threading
    def _background_setup():
        try:
            _try_create_gitea_repo(project)
        except Exception:
            logger.exception("Background Gitea setup failed for %s", project.id)
    threading.Thread(target=_background_setup, daemon=True).start()

    return RedirectResponse(f"/expert/{project.slug}/{conv.id}", status_code=302)


@router.get("/expert/{slug}")
def expert_project(slug: str, user_email: str = Depends(get_current_user)):
    """Project detail: redirect to latest conversation (workspace view)."""
    if not config.EXPERT_MODE_ENABLED:
        raise HTTPException(status_code=404)

    project = store.get_project_by_slug(slug)
    if not project:
        return RedirectResponse("/expert", status_code=302)

    # Redirect to the latest conversation's workspace view
    project_conversations = store.list_project_conversations(project.id)
    if project_conversations:
        return RedirectResponse(f"/expert/{slug}/{project_conversations[0].id}", status_code=302)

    # No conversations yet -- create one and redirect
    conv = store.create_conversation(
        conv_type="project", project_id=project.id, user_id=user_email
    )
    return RedirectResponse(f"/expert/{slug}/{conv.id}", status_code=302)


@router.get("/expert/{slug}/settings")
def expert_settings(slug: str, request: Request, user_email: str = Depends(get_current_user)):
    """Project settings: deploy status, deploy actions, project config."""
    if not config.EXPERT_MODE_ENABLED:
        raise HTTPException(status_code=404)

    project = store.get_project_by_slug(slug)
    if not project:
        return RedirectResponse("/expert", status_code=302)

    return templates.TemplateResponse(request, "expert/settings.html", {
        "project": project,
        "section": "expert",
    })


@router.api_route("/expert/{slug}/preview/{environment}/", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
@router.api_route("/expert/{slug}/preview/{environment}/{subpath:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"])
async def expert_project_preview(slug: str, environment: str, request: Request, subpath: str = ""):
    """Proxy project preview through Matometa host so localhost ports are not required client-side."""
    if not config.EXPERT_MODE_ENABLED:
        raise HTTPException(status_code=404)

    if environment not in {"staging", "production"}:
        raise HTTPException(status_code=404)

    project = store.get_project_by_slug(slug)
    if not project:
        raise HTTPException(status_code=404)

    upstream_base = _environment_deploy_url(project, environment)
    if not upstream_base:
        return Response(content="Application non deployee pour cet environnement.", status_code=404)

    parsed_subpath = urlsplit(subpath)
    if parsed_subpath.scheme or parsed_subpath.netloc:
        raise HTTPException(status_code=400)

    safe_subpath = parsed_subpath.path.lstrip("/")
    target_url = urljoin(upstream_base.rstrip("/") + "/", safe_subpath)
    target_url = _internal_proxy_url(target_url)

    allowed_targets = {
        urlsplit(upstream_base).netloc,
        urlsplit(_internal_proxy_url(upstream_base)).netloc,
    }
    if urlsplit(target_url).netloc not in allowed_targets:
        raise HTTPException(status_code=400)

    hop_by_hop = {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailers",
        "transfer-encoding",
        "upgrade",
        "host",
    }
    upstream_headers = {
        key: value
        for key, value in request.headers.items()
        if key.lower() not in hop_by_hop
    }

    request_body = await request.body()
    request_method = request.method
    request_params = dict(request.query_params)

    try:
        upstream_resp = await asyncio.to_thread(
            http_requests.request,
            method=request_method,
            url=target_url,
            params=request_params,
            headers=upstream_headers,
            data=request_body,
            allow_redirects=False,
            timeout=30,
        )
    except http_requests.RequestException as exc:
        logger.warning("Preview proxy error for %s/%s: %s", slug, environment, exc)

        # Try auto-restart via Docker before returning error
        container_status = "inconnu"
        if _use_docker_deploy():
            try:
                from lib import docker_deploy
                st = docker_deploy.status(project.id, environment)
                container_status = st.get("status", "unknown")
                if container_status in ("exited", "stopped", "error"):
                    docker_deploy.restart(project.id, environment)
                    container_status = "redemarrage..."
            except Exception:
                container_status = "erreur Docker"

        deploy_endpoint = (f"/api/expert/projects/{project.id}/deploy-staging"
                           if environment == "staging"
                           else f"/api/expert/projects/{project.id}/deploy")

        return HTMLResponse(
            f"""<!doctype html><html><head><meta charset="utf-8"><title>Preview indisponible</title>
            <style>body{{font-family:system-ui;max-width:600px;margin:80px auto;text-align:center;color:#333}}
            .status{{background:#f8d7da;padding:12px 20px;border-radius:8px;margin:20px 0;font-size:14px}}
            .actions{{display:flex;gap:8px;justify-content:center;flex-wrap:wrap}}
            button{{background:#0d6efd;color:#fff;border:none;padding:10px 24px;border-radius:6px;cursor:pointer;font-size:14px}}
            button:hover{{background:#0b5ed7}}
            .btn-secondary{{background:#6c757d}}
            .btn-secondary:hover{{background:#5c636a}}
            a{{color:#0d6efd}}</style></head>
            <body><h2>Application indisponible</h2>
            <p>L'application <b>{slug}</b> ({environment}) ne repond pas.</p>
            <div class="status">Statut conteneur : <b>{container_status}</b></div>
            <div class="actions">
            <button class="btn-secondary" onclick="fetch('/api/expert/projects/{project.id}/restart/{environment}',{{method:'POST'}}).then(()=>setTimeout(()=>location.reload(),3000))">
            <i class="ri-restart-line"></i> Redemarrer</button>
            <button onclick="fetch('{deploy_endpoint}',{{method:'POST'}}).then(()=>setTimeout(()=>location.reload(),5000))">
            <i class="ri-upload-cloud-line"></i> Redéployer</button>
            </div>
            <p style="margin-top:20px"><a href="/expert/{slug}">← Retour au projet</a></p></body></html>""",
            status_code=502,
        )

    response_headers = {}
    location = upstream_resp.headers.get("Location")
    if location:
        parsed_loc = urlsplit(location)
        parsed_target = urlsplit(upstream_base)
        parsed_internal_target = urlsplit(_internal_proxy_url(upstream_base))
        if location.startswith("/"):
            rewritten = _preview_base_path(slug, environment) + location
            response_headers["Location"] = rewritten
        elif parsed_loc.netloc in {parsed_target.netloc, parsed_internal_target.netloc}:
            rewritten = _preview_base_path(slug, environment) + (parsed_loc.path or "/")
            if parsed_loc.query:
                rewritten = f"{rewritten}?{parsed_loc.query}"
            response_headers["Location"] = rewritten
        else:
            response_headers["Location"] = location

    for key, value in upstream_resp.headers.items():
        key_lower = key.lower()
        if key_lower in hop_by_hop or key_lower in {"content-length", "location"}:
            continue
        response_headers[key] = value

    body = upstream_resp.content
    content_type = (upstream_resp.headers.get("Content-Type") or "").lower()
    if "text/html" in content_type and body:
        charset = upstream_resp.encoding or "utf-8"
        try:
            html = body.decode(charset, errors="replace")
            body = _rewrite_proxy_html(html, slug, environment).encode(charset, errors="replace")
        except Exception:
            logger.exception("Failed to rewrite preview HTML for %s/%s", slug, environment)

    return Response(content=body, status_code=upstream_resp.status_code, headers=response_headers)


@router.get("/expert/{slug}/{conv_id}")
def expert_conversation(slug: str, conv_id: str, request: Request, user_email: str = Depends(get_current_user)):
    """Expert workspace: spec panel + chat + deploy bar."""
    if not config.EXPERT_MODE_ENABLED:
        raise HTTPException(status_code=404)

    project = store.get_project_by_slug(slug)
    if not project:
        return RedirectResponse("/expert", status_code=302)

    conv = store.get_conversation(conv_id, include_messages=False)
    if not conv:
        return RedirectResponse(f"/expert/{slug}", status_code=302)

    project_conversations = store.list_project_conversations(project.id)

    data = _get_expert_sidebar_data(user_email)
    return templates.TemplateResponse(request, "expert/workspace.html", {
        "section": "expert",
        "current_conv": conv,
        "project": project,
        "project_conversations": project_conversations,
        **data,
    })


# =============================================================================
# API endpoints
# =============================================================================


@router.post("/api/expert/projects")
async def api_create_project(request: Request, user_email: str = Depends(get_current_user)):
    """Create project + first conversation."""
    if not config.EXPERT_MODE_ENABLED:
        return JSONResponse({"error": "Expert mode not enabled"}, status_code=403)

    data = await request.json()
    if not data:
        data = {}
    name = data.get("name", "Nouveau projet")
    description = data.get("description")

    project = store.create_project(name=name, user_id=user_email, description=description)

    # Initialize .specify/ structure
    workdir = config.PROJECTS_DIR / project.id
    workdir.mkdir(parents=True, exist_ok=True)
    try:
        from skills.speckit_init.scripts.init_project import init_specify
        init_specify(str(workdir))
    except Exception:
        logger.exception("Failed to init .specify/ for project %s", project.id)

    conv = store.create_conversation(
        conv_type="project", project_id=project.id, user_id=user_email
    )

    # Run Gitea repo creation in background (frontend triggers /welcome for speckit)
    import threading
    def _background_setup():
        try:
            _try_create_gitea_repo(project)
        except Exception:
            logger.exception("Background Gitea setup failed for %s", project.id)
    threading.Thread(target=_background_setup, daemon=True).start()

    return JSONResponse({
        "project": _project_to_public_dict(project, request),
        "conversation_id": conv.id,
        "redirect": f"/expert/{project.slug}/{conv.id}",
    }, status_code=201)


@router.patch("/api/expert/projects/{project_id}")
async def api_update_project(project_id: str, request: Request):
    """Update project fields (name, spec, status)."""
    if not config.EXPERT_MODE_ENABLED:
        return JSONResponse({"error": "Expert mode not enabled"}, status_code=403)

    project = store.get_project(project_id)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    data = await request.json()
    if not data:
        data = {}
    allowed_fields = {
        "name",
        "description",
        "spec",
        "status",
        "staging_branch",
        "production_branch",
    }
    updates = {k: v for k, v in data.items() if k in allowed_fields}

    if not updates:
        return JSONResponse({"error": "No valid fields to update"}, status_code=400)

    store.update_project(project_id, **updates)
    updated = store.get_project(project_id)
    return JSONResponse(_project_to_public_dict(updated, request))


@router.post("/api/expert/projects/{project_id}/conversations")
async def api_new_conversation(project_id: str, user_email: str = Depends(get_current_user)):
    """Start a new conversation within an existing project."""
    if not config.EXPERT_MODE_ENABLED:
        return JSONResponse({"error": "Expert mode not enabled"}, status_code=403)

    project = store.get_project(project_id)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    conv = store.create_conversation(
        conv_type="project", project_id=project.id, user_id=user_email
    )

    return JSONResponse({
        "conversation_id": conv.id,
        "redirect": f"/expert/{project.slug}/{conv.id}",
    }, status_code=201)


def _use_docker_deploy() -> bool:
    """Use direct Docker deploy when Docker socket is available."""
    from lib.docker_deploy import docker_available
    return docker_available()


def _docker_deploy_staging(project_id: str, project, request: Request):
    """Deploy staging via direct Docker Compose."""
    from lib import docker_deploy

    _ensure_local_git_repo(project)
    ensure_project_branches(project)
    _ensure_deployable_repo(project)
    commit_and_push_staging_if_changed(project)

    result = docker_deploy.deploy(project_id, "staging")
    updated = store.get_project(project_id)
    return JSONResponse({
        "status": "staging_deploying" if result["status"] == "running" else result["status"],
        "staging": {
            "deploy_url": result.get("deploy_url"),
            "detail": result,
        },
        "project": _project_to_public_dict(updated or project, request),
    }, status_code=200 if result["status"] == "running" else 500)


def _docker_deploy_production(project_id: str, project, request: Request):
    """Deploy staging + production via direct Docker Compose."""
    from lib import docker_deploy

    _ensure_local_git_repo(project)
    ensure_project_branches(project)
    _ensure_deployable_repo(project)
    commit_and_push_staging_if_changed(project)

    # Deploy staging first
    staging_result = docker_deploy.deploy(project_id, "staging")

    refreshed = store.get_project(project_id) or project

    # Promote staging to production branch
    promotion = promote_staging_to_production(refreshed)

    # Deploy production
    prod_result = docker_deploy.deploy(project_id, "production")

    updated = store.get_project(project_id)
    return JSONResponse({
        "status": "production_deploying" if prod_result["status"] == "running" else prod_result["status"],
        "promotion": promotion,
        "staging": {
            "deploy_url": staging_result.get("deploy_url"),
            "detail": staging_result,
        },
        "production": {
            "deploy_url": prod_result.get("deploy_url"),
            "detail": prod_result,
        },
        "project": _project_to_public_dict(updated or refreshed, request),
    }, status_code=200 if prod_result["status"] == "running" else 500)


@router.post("/api/expert/projects/{project_id}/deploy")
def api_deploy_project(project_id: str, request: Request):
    """Promote staging to production and trigger production deployment."""
    if not config.EXPERT_MODE_ENABLED:
        return JSONResponse({"error": "Expert mode not enabled"}, status_code=403)

    project = store.get_project(project_id)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    if not project.gitea_url:
        return JSONResponse({"error": "Project has no Gitea repo yet"}, status_code=400)

    try:
        # Prefer direct Docker deploy when socket is available
        if _use_docker_deploy():
            return _docker_deploy_production(project_id, project, request)

        # Fallback to Coolify
        if not config.COOLIFY_API_TOKEN:
            return JSONResponse({"error": "Neither Docker socket nor Coolify available"}, status_code=503)

        from lib.coolify import CoolifyClient
        coolify = CoolifyClient()

        _ensure_local_git_repo(project)
        ensure_project_branches(project)
        _ensure_deployable_repo(project)
        commit_and_push_staging_if_changed(project)

        staging_app_uuid, staging_url = _ensure_staging_application(project, coolify)
        if staging_app_uuid and not project.staging_coolify_app_uuid:
            coolify.deploy(staging_app_uuid)

        refreshed = store.get_project(project_id) or project
        promotion = promote_staging_to_production(refreshed)

        refreshed = store.get_project(project_id) or refreshed
        production_app_uuid, production_url = _ensure_production_application(refreshed, coolify)

        deploy_result = None
        if production_app_uuid:
            deploy_result = coolify.deploy(production_app_uuid)

        updated = store.get_project(project_id)
        return JSONResponse({
            "status": "production_deploying",
            "promotion": promotion,
            "staging": {"app_uuid": staging_app_uuid, "deploy_url": staging_url},
            "production": {"app_uuid": production_app_uuid, "deploy_url": production_url, "detail": deploy_result},
            "project": _project_to_public_dict(updated, request) if updated else _project_to_public_dict(refreshed, request),
        })
    except Exception as e:
        logger.exception("Production deploy failed")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.post("/api/expert/projects/{project_id}/deploy-staging")
def api_deploy_staging_project(project_id: str, request: Request):
    """Create/redeploy staging app (auto path used by expert workflow)."""
    if not config.EXPERT_MODE_ENABLED:
        return JSONResponse({"error": "Expert mode not enabled"}, status_code=403)

    project = store.get_project(project_id)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    if not project.gitea_url:
        return JSONResponse({"error": "Project has no Gitea repo yet"}, status_code=400)

    try:
        if _use_docker_deploy():
            return _docker_deploy_staging(project_id, project, request)

        if not config.COOLIFY_API_TOKEN:
            return JSONResponse({"error": "Neither Docker socket nor Coolify available"}, status_code=503)

        from lib.coolify import CoolifyClient
        coolify = CoolifyClient()

        _ensure_local_git_repo(project)
        ensure_project_branches(project)
        _ensure_deployable_repo(project)

        staging_app_uuid, staging_url = _ensure_staging_application(project, coolify)
        detail = coolify.deploy(staging_app_uuid) if staging_app_uuid else None

        updated = store.get_project(project_id)
        return JSONResponse({
            "status": "staging_deploying",
            "staging": {"app_uuid": staging_app_uuid, "deploy_url": staging_url, "detail": detail},
            "project": _project_to_public_dict(updated, request) if updated else _project_to_public_dict(project, request),
        })
    except Exception as e:
        logger.exception("Staging deploy failed")
        return JSONResponse({"error": str(e)}, status_code=500)


@router.get("/api/expert/projects/{project_id}/spec-files")
def api_spec_files(project_id: str):
    """Return .specify/ artifact contents as JSON for the spec panel."""
    if not config.EXPERT_MODE_ENABLED:
        return JSONResponse({"error": "Expert mode not enabled"}, status_code=403)

    project = store.get_project(project_id)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    workdir = config.PROJECTS_DIR / project.id
    specify_dir = workdir / ".specify"

    result = {}

    def _read_file(path):
        if path.exists():
            return path.read_text()
        return None

    # Read constitution
    result["constitution"] = _read_file(specify_dir / "memory" / "constitution.md")

    # Find latest spec version
    specs_dir = specify_dir / "specs"
    version = None
    if specs_dir.exists():
        versions = sorted(
            [d for d in specs_dir.iterdir() if d.is_dir()],
            key=lambda d: d.name,
            reverse=True,
        )
        if versions:
            version = versions[0].name
            latest = versions[0]
            result["spec"] = _read_file(latest / "spec.md")
            result["plan"] = _read_file(latest / "plan.md")
            result["tasks"] = _read_file(latest / "tasks.md")
            result["checklist"] = _read_file(latest / "checklist.md")

    result["version"] = version

    # Fallback: if no .specify/, return project.spec from DB
    if not specify_dir.exists() and project.spec:
        result["spec"] = project.spec

    return JSONResponse(result)


@router.get("/api/expert/projects/{project_id}/deploy-status")
def api_deploy_status(project_id: str, request: Request):
    """Poll deployment status (AJAX from project detail page)."""
    if not config.EXPERT_MODE_ENABLED:
        return JSONResponse({"error": "Expert mode not enabled"}, status_code=403)

    project = store.get_project(project_id)
    if not project:
        return JSONResponse({"error": "Project not found"}, status_code=404)

    staging_preview_url = _preview_url(project.slug, "staging") if project.staging_deploy_url else None
    production_preview_url = _preview_url(project.slug, "production") if project.production_deploy_url else None

    # Try direct Docker status first
    if _use_docker_deploy():
        from lib import docker_deploy
        staging_st = docker_deploy.status(project_id, "staging") if project.staging_deploy_url else {"status": "not_deployed"}
        prod_st = docker_deploy.status(project_id, "production") if project.production_deploy_url else {"status": "not_deployed"}

        overall = prod_st.get("status", "not_deployed")
        if overall == "not_deployed":
            overall = staging_st.get("status", "not_deployed")

        primary_url = production_preview_url or staging_preview_url
        return JSONResponse({
            "status": overall,
            "deploy_url": primary_url,
            "staging": {
                "status": staging_st.get("status", "not_deployed"),
                "deploy_url": staging_preview_url,
                "technical_deploy_url": _publicize_deploy_url(project.staging_deploy_url, request),
                "detail": staging_st,
            },
            "production": {
                "status": prod_st.get("status", "not_deployed"),
                "deploy_url": production_preview_url,
                "technical_deploy_url": _publicize_deploy_url(project.production_deploy_url, request),
                "detail": prod_st,
            },
        })

    # Fallback: Coolify status
    if not project.staging_coolify_app_uuid and not project.production_coolify_app_uuid:
        return JSONResponse({"status": "not_deployed"})

    if not config.COOLIFY_API_TOKEN:
        return JSONResponse({"status": "unknown", "error": "Coolify not configured"})

    try:
        from lib.coolify import CoolifyClient
        coolify = CoolifyClient()
        staging_detail = None
        production_detail = None
        if project.staging_coolify_app_uuid:
            staging_detail = coolify.get_status(project.staging_coolify_app_uuid)
        if project.production_coolify_app_uuid:
            production_detail = coolify.get_status(project.production_coolify_app_uuid)

        overall_status = "not_deployed"
        if production_detail:
            overall_status = production_detail.get("status", "unknown")
        elif staging_detail:
            overall_status = staging_detail.get("status", "unknown")

        primary_url = production_preview_url or staging_preview_url or _publicize_deploy_url(
            project.production_deploy_url or project.staging_deploy_url or project.deploy_url, request
        )

        return JSONResponse({
            "status": overall_status,
            "deploy_url": primary_url,
            "staging": {
                "status": staging_detail.get("status", "unknown") if staging_detail else "not_deployed",
                "deploy_url": staging_preview_url,
                "technical_deploy_url": _publicize_deploy_url(project.staging_deploy_url, request),
                "app_uuid": project.staging_coolify_app_uuid,
                "detail": staging_detail,
            },
            "production": {
                "status": production_detail.get("status", "unknown") if production_detail else "not_deployed",
                "deploy_url": production_preview_url,
                "technical_deploy_url": _publicize_deploy_url(project.production_deploy_url, request),
                "app_uuid": project.production_coolify_app_uuid,
                "detail": production_detail,
            },
        })
    except Exception as e:
        logger.exception("Deploy status check failed")
        return JSONResponse({"status": "error", "error": str(e)}, status_code=500)


@router.get("/api/expert/projects/{project_id}/logs/{environment}")
def api_project_logs(project_id: str, environment: str):
    """Get container logs for a project environment."""
    if not config.EXPERT_MODE_ENABLED:
        return JSONResponse({"error": "Expert mode not enabled"}, status_code=403)
    if environment not in ("staging", "production"):
        return JSONResponse({"error": "Invalid environment"}, status_code=400)
    if not _use_docker_deploy():
        return JSONResponse({"error": "Direct Docker not available"}, status_code=503)

    from lib import docker_deploy
    log_text = docker_deploy.logs(project_id, environment)
    return JSONResponse({"logs": log_text})


@router.post("/api/expert/projects/{project_id}/restart/{environment}")
def api_project_restart(project_id: str, environment: str):
    """Restart project containers without rebuild."""
    if not config.EXPERT_MODE_ENABLED:
        return JSONResponse({"error": "Expert mode not enabled"}, status_code=403)
    if environment not in ("staging", "production"):
        return JSONResponse({"error": "Invalid environment"}, status_code=400)
    if not _use_docker_deploy():
        return JSONResponse({"error": "Direct Docker not available"}, status_code=503)

    from lib import docker_deploy
    result = docker_deploy.restart(project_id, environment)
    status_code = 200 if result.get("status") == "running" else 500
    return JSONResponse(result, status_code=status_code)


@router.post("/api/expert/projects/{project_id}/stop/{environment}")
def api_project_stop(project_id: str, environment: str):
    """Stop project containers."""
    if not config.EXPERT_MODE_ENABLED:
        return JSONResponse({"error": "Expert mode not enabled"}, status_code=403)
    if environment not in ("staging", "production"):
        return JSONResponse({"error": "Invalid environment"}, status_code=400)
    if not _use_docker_deploy():
        return JSONResponse({"error": "Direct Docker not available"}, status_code=503)

    from lib import docker_deploy
    result = docker_deploy.stop(project_id, environment)
    return JSONResponse(result)
