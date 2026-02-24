"""Expert mode routes — separate UI section for vibecoded apps."""

import copy
import logging
import secrets
import socket
import subprocess
from urllib.parse import urljoin, urlsplit, urlunsplit
from pathlib import Path

import requests
from flask import Blueprint, render_template, request, g, redirect, jsonify, abort, Response

from ..storage import store
from .. import config
from lib.expert_git import (
    authenticated_clone_url,
    commit_and_push_staging_if_changed,
    extract_owner_repo_from_url,
    ensure_local_git_repo as ensure_project_local_git_repo,
    ensure_project_branches,
    promote_staging_to_production,
)

logger = logging.getLogger(__name__)

bp = Blueprint("expert", __name__)


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


def _publicize_deploy_url(url: str | None) -> str | None:
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
    if not target_host:
        req_host = (request.host or "").split(":", 1)[0].strip()
        if req_host and req_host not in {"localhost", "127.0.0.1", "testserver"}:
            target_host = req_host

    if not target_host:
        return url

    netloc = f"{target_host}:{parsed.port}" if parsed.port else target_host
    scheme = parsed.scheme or "http"
    return urlunsplit((scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def _project_to_public_dict(project) -> dict:
    """Serialize project and rewrite deploy URLs for current requester."""
    payload = project.to_dict()
    for field in ("deploy_url", "staging_deploy_url", "production_deploy_url"):
        value = _publicize_deploy_url(payload.get(field))
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
    return content


def _run_git(workdir, *args, timeout=30):
    """Run a git command in a project workdir and return stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=workdir,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.stdout.strip()


def _is_port_free(port: int) -> bool:
    """Check whether a local TCP port is available."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _pick_host_port(start: int = 18080, end: int | None = 19999, reserved_ports: set[int] | None = None) -> int:
    """Pick a free host port for direct app exposure."""
    reserved = reserved_ports or set()
    if end is None or end < start:
        end = start + 2000
    for port in range(start, end + 1):
        if port in reserved:
            continue
        if _is_port_free(port):
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
    """Ensure repo contains a minimal Dockerfile so first deploy can boot.

    Returns True when files were added and pushed, False otherwise.
    """
    workdir = config.PROJECTS_DIR / project.id
    if not (workdir / ".git").exists():
        return False

    dockerfile = workdir / "Dockerfile"
    if dockerfile.exists():
        return False

    created_files = []
    dockerfile.write_text(
        "FROM python:3.12-slim\n"
        "WORKDIR /app\n"
        "COPY . /app\n"
        "EXPOSE 5000\n"
        "CMD [\"python\", \"-m\", \"http.server\", \"5000\", \"--bind\", \"0.0.0.0\"]\n"
    )
    created_files.append("Dockerfile")

    index_html = workdir / "index.html"
    if not index_html.exists():
        safe_name = (project.name or project.slug or "Application").replace("<", "").replace(">", "")
        index_html.write_text(
            "<!doctype html>\n"
            "<html lang=\"fr\">\n"
            "<head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
            f"<title>{safe_name}</title></head>\n"
            "<body style=\"font-family: sans-serif; margin: 2rem;\">\n"
            f"<h1>{safe_name}</h1>\n"
            "<p>L'application est déployée. Vous pouvez maintenant la faire évoluer dans cette conversation.</p>\n"
            "</body></html>\n"
        )
        created_files.append("index.html")

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
        logger.info("Bootstrapped deploy files for project %s", project.id)
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
        gitea = GiteaClient()
        repo = gitea.create_repo(
            name=project.slug,
            description=project.description or "",
        )
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
    """Set up Gitea→Coolify webhook for auto-redeploy on push.

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
        logger.info("Created Gitea webhook for %s/%s → Coolify %s", owner, repo, app_uuid)
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
    if _use_local_direct_port_mode():
        reserved_ports = _reserved_local_deploy_ports(exclude_project_id=project.id)
        host_port = _pick_host_port(start=local_port_start, reserved_ports=reserved_ports)
        ports_mappings = f"{host_port}:5000"
        deploy_url = _local_deploy_url(host_port)

    result = coolify.create_application(
        name=app_name,
        git_repo_url=ssh_repo_url,
        git_branch=git_branch,
        server_uuid=server_uuid,
        project_uuid=coolify_proj["uuid"],
        ports_mappings=ports_mappings,
        private_key_uuid=deploy_key_uuid,
    )
    app_uuid = result.get("uuid", "")

    if not deploy_url:
        deploy_url = _normalize_deploy_url(result.get("domains"))

    return app_uuid, deploy_url


def _ensure_staging_application(project, coolify):
    """Ensure staging app exists, is reachable, and webhook is configured."""
    staging_branch = project.staging_branch or config.EXPERT_STAGING_BRANCH

    app_uuid = project.staging_coolify_app_uuid
    deploy_url = project.staging_deploy_url

    if app_uuid:
        if _use_local_direct_port_mode():
            app_state = coolify.get_status(app_uuid)
            mapped_port = _extract_host_port_mapping(app_state.get("ports_mappings"))
            reserved_ports = _reserved_local_deploy_ports(exclude_project_id=project.id)
            if not mapped_port or mapped_port in reserved_ports:
                mapped_port = _pick_host_port(start=18080, reserved_ports=reserved_ports)
                coolify.set_ports_mapping(app_uuid, f"{mapped_port}:5000")
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
            mapped_port = _extract_host_port_mapping(app_state.get("ports_mappings"))
            reserved_ports = _reserved_local_deploy_ports(exclude_project_id=project.id)
            if not mapped_port or mapped_port in reserved_ports:
                mapped_port = _pick_host_port(start=28080, reserved_ports=reserved_ports)
                coolify.set_ports_mapping(app_uuid, f"{mapped_port}:5000")
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
    return app_uuid, deploy_url


def _get_expert_sidebar_data(user_email=None):
    """Get sidebar data for expert mode pages."""
    from .html import get_sidebar_data
    if user_email is None:
        user_email = getattr(g, "user_email", None)
    return get_sidebar_data(user_email)


# =============================================================================
# HTML pages
# =============================================================================

@bp.route("/expert")
def expert_home():
    """Expert mode landing: list of user's projects + new project button."""
    if not config.EXPERT_MODE_ENABLED:
        abort(404)

    user_email = getattr(g, "user_email", None)
    projects = store.list_projects(user_id=user_email)

    data = _get_expert_sidebar_data()
    return render_template(
        "expert/home.html",
        section="expert",
        current_conv=None,
        projects=projects,
        **data
    )


@bp.route("/expert/nouveau")
def expert_new():
    """Create new expert app -> redirects to conversation in plan mode."""
    if not config.EXPERT_MODE_ENABLED:
        abort(404)

    user_email = getattr(g, "user_email", None)
    project = store.create_project(name="Nouveau projet", user_id=user_email)
    _try_create_gitea_repo(project)
    conv = store.create_conversation(
        conv_type="project", project_id=project.id, user_id=user_email
    )
    return redirect(f"/expert/{project.slug}/{conv.id}")


@bp.route("/expert/<slug>")
def expert_project(slug):
    """Project detail: tabs for conversations, spec, deployment."""
    if not config.EXPERT_MODE_ENABLED:
        abort(404)

    project = store.get_project_by_slug(slug)
    if not project:
        return redirect("/expert")

    project_conversations = store.list_project_conversations(project.id)

    public_project = copy.deepcopy(project)
    public_project.deploy_url = _publicize_deploy_url(public_project.deploy_url)
    public_project.staging_deploy_url = _publicize_deploy_url(public_project.staging_deploy_url)
    public_project.production_deploy_url = _publicize_deploy_url(public_project.production_deploy_url)
    public_project.staging_preview_url = _preview_url(project.slug, "staging")
    public_project.production_preview_url = _preview_url(project.slug, "production")

    data = _get_expert_sidebar_data()
    return render_template(
        "expert/project.html",
        section="expert",
        current_conv=None,
        project=public_project,
        project_conversations=project_conversations,
        **data
    )


@bp.route("/expert/<slug>/preview/<environment>/", defaults={"subpath": ""}, methods=["GET", "HEAD"])
@bp.route("/expert/<slug>/preview/<environment>/<path:subpath>", methods=["GET", "HEAD"])
def expert_project_preview(slug, environment, subpath):
    """Proxy project preview through Matometa host so localhost ports are not required client-side."""
    if not config.EXPERT_MODE_ENABLED:
        abort(404)

    if environment not in {"staging", "production"}:
        abort(404)

    project = store.get_project_by_slug(slug)
    if not project:
        abort(404)

    upstream_base = _environment_deploy_url(project, environment)
    if not upstream_base:
        return "Application non deployee pour cet environnement.", 404

    parsed_subpath = urlsplit(subpath)
    if parsed_subpath.scheme or parsed_subpath.netloc:
        abort(400)

    safe_subpath = parsed_subpath.path.lstrip("/")
    target_url = urljoin(upstream_base.rstrip("/") + "/", safe_subpath)
    target_url = _internal_proxy_url(target_url)

    allowed_targets = {
        urlsplit(upstream_base).netloc,
        urlsplit(_internal_proxy_url(upstream_base)).netloc,
    }
    if urlsplit(target_url).netloc not in allowed_targets:
        abort(400)

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

    try:
        upstream_resp = requests.request(
            method=request.method,
            url=target_url,
            params=request.args,
            headers=upstream_headers,
            data=request.get_data(),
            allow_redirects=False,
            timeout=30,
        )
    except requests.RequestException as exc:
        logger.warning("Preview proxy error for %s/%s: %s", slug, environment, exc)
        return "Impossible de joindre l'application deployee.", 502

    response_headers = []
    location = upstream_resp.headers.get("Location")
    if location:
        parsed_loc = urlsplit(location)
        parsed_target = urlsplit(upstream_base)
        parsed_internal_target = urlsplit(_internal_proxy_url(upstream_base))
        if location.startswith("/"):
            rewritten = _preview_base_path(slug, environment) + location
            response_headers.append(("Location", rewritten))
        elif parsed_loc.netloc in {parsed_target.netloc, parsed_internal_target.netloc}:
            rewritten = _preview_base_path(slug, environment) + (parsed_loc.path or "/")
            if parsed_loc.query:
                rewritten = f"{rewritten}?{parsed_loc.query}"
            response_headers.append(("Location", rewritten))
        else:
            response_headers.append(("Location", location))

    for key, value in upstream_resp.headers.items():
        key_lower = key.lower()
        if key_lower in hop_by_hop or key_lower in {"content-length", "location"}:
            continue
        response_headers.append((key, value))

    body = upstream_resp.content
    content_type = (upstream_resp.headers.get("Content-Type") or "").lower()
    if "text/html" in content_type and body:
        charset = upstream_resp.encoding or "utf-8"
        try:
            html = body.decode(charset, errors="replace")
            body = _rewrite_proxy_html(html, slug, environment).encode(charset, errors="replace")
        except Exception:
            logger.exception("Failed to rewrite preview HTML for %s/%s", slug, environment)

    return Response(body, status=upstream_resp.status_code, headers=response_headers)


@bp.route("/expert/<slug>/<conv_id>")
def expert_conversation(slug, conv_id):
    """Expert mode conversation view — same chat UI, different chrome."""
    if not config.EXPERT_MODE_ENABLED:
        abort(404)

    project = store.get_project_by_slug(slug)
    if not project:
        return redirect("/expert")

    conv = store.get_conversation(conv_id, include_messages=False)
    if not conv:
        return redirect(f"/expert/{slug}")

    data = _get_expert_sidebar_data()
    return render_template(
        "expert/conversation.html",
        section="expert",
        current_conv=conv,
        project=project,
        **data
    )


# =============================================================================
# API endpoints
# =============================================================================

@bp.route("/api/expert/projects", methods=["POST"])
def api_create_project():
    """Create project + first conversation."""
    if not config.EXPERT_MODE_ENABLED:
        return jsonify({"error": "Expert mode not enabled"}), 403

    data = request.get_json() or {}
    name = data.get("name", "Nouveau projet")
    description = data.get("description")
    user_email = getattr(g, "user_email", None)

    project = store.create_project(name=name, user_id=user_email, description=description)
    _try_create_gitea_repo(project)
    # Re-fetch so gitea fields are included in response
    project = store.get_project(project.id) or project
    conv = store.create_conversation(
        conv_type="project", project_id=project.id, user_id=user_email
    )

    return jsonify({
        "project": _project_to_public_dict(project),
        "conversation_id": conv.id,
        "redirect": f"/expert/{project.slug}/{conv.id}",
    }), 201


@bp.route("/api/expert/projects/<project_id>", methods=["PATCH"])
def api_update_project(project_id):
    """Update project fields (name, spec, status)."""
    if not config.EXPERT_MODE_ENABLED:
        return jsonify({"error": "Expert mode not enabled"}), 403

    project = store.get_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    data = request.get_json() or {}
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
        return jsonify({"error": "No valid fields to update"}), 400

    store.update_project(project_id, **updates)
    updated = store.get_project(project_id)
    return jsonify(_project_to_public_dict(updated))


@bp.route("/api/expert/projects/<project_id>/conversations", methods=["POST"])
def api_new_conversation(project_id):
    """Start a new conversation within an existing project."""
    if not config.EXPERT_MODE_ENABLED:
        return jsonify({"error": "Expert mode not enabled"}), 403

    project = store.get_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    user_email = getattr(g, "user_email", None)
    conv = store.create_conversation(
        conv_type="project", project_id=project.id, user_id=user_email
    )

    return jsonify({
        "conversation_id": conv.id,
        "redirect": f"/expert/{project.slug}/{conv.id}",
    }), 201


@bp.route("/api/expert/projects/<project_id>/deploy", methods=["POST"])
def api_deploy_project(project_id):
    """Promote staging to production and trigger production deployment."""
    if not config.EXPERT_MODE_ENABLED:
        return jsonify({"error": "Expert mode not enabled"}), 403

    project = store.get_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    if not project.gitea_url:
        return jsonify({"error": "Project has no Gitea repo yet"}), 400

    if not config.COOLIFY_API_TOKEN:
        return jsonify({"error": "Coolify not configured"}), 503

    try:
        from lib.coolify import CoolifyClient
        coolify = CoolifyClient()

        _ensure_local_git_repo(project)
        ensure_project_branches(project)

        # Guarantee the repository is deployable on first deploy.
        _ensure_deployable_repo(project)
        commit_and_push_staging_if_changed(project)

        # Ensure staging infra is always alive and webhook-driven.
        staging_app_uuid, staging_url = _ensure_staging_application(project, coolify)
        if staging_app_uuid and not project.staging_coolify_app_uuid:
            coolify.deploy(staging_app_uuid)

        refreshed = store.get_project(project_id) or project

        # Promote staging branch to production branch before production deploy.
        promotion = promote_staging_to_production(refreshed)

        refreshed = store.get_project(project_id) or refreshed
        production_app_uuid, production_url = _ensure_production_application(refreshed, coolify)

        deploy_result = None
        if production_app_uuid:
            deploy_result = coolify.deploy(production_app_uuid)

        updated = store.get_project(project_id)
        return jsonify(
            {
                "status": "production_deploying",
                "promotion": promotion,
                "staging": {
                    "app_uuid": staging_app_uuid,
                    "deploy_url": staging_url,
                },
                "production": {
                    "app_uuid": production_app_uuid,
                    "deploy_url": production_url,
                    "detail": deploy_result,
                },
                "project": _project_to_public_dict(updated) if updated else _project_to_public_dict(refreshed),
            }
        )
    except Exception as e:
        logger.exception("Production deploy failed")
        return jsonify({"error": str(e)}), 500


@bp.route("/api/expert/projects/<project_id>/deploy-staging", methods=["POST"])
def api_deploy_staging_project(project_id):
    """Create/redeploy staging app (auto path used by expert workflow)."""
    if not config.EXPERT_MODE_ENABLED:
        return jsonify({"error": "Expert mode not enabled"}), 403

    project = store.get_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    if not project.gitea_url:
        return jsonify({"error": "Project has no Gitea repo yet"}), 400

    if not config.COOLIFY_API_TOKEN:
        return jsonify({"error": "Coolify not configured"}), 503

    try:
        from lib.coolify import CoolifyClient
        coolify = CoolifyClient()

        _ensure_local_git_repo(project)
        ensure_project_branches(project)
        _ensure_deployable_repo(project)

        staging_app_uuid, staging_url = _ensure_staging_application(project, coolify)
        detail = coolify.deploy(staging_app_uuid) if staging_app_uuid else None

        updated = store.get_project(project_id)
        return jsonify(
            {
                "status": "staging_deploying",
                "staging": {
                    "app_uuid": staging_app_uuid,
                    "deploy_url": staging_url,
                    "detail": detail,
                },
                "project": _project_to_public_dict(updated) if updated else _project_to_public_dict(project),
            }
        )
    except Exception as e:
        logger.exception("Staging deploy failed")
        return jsonify({"error": str(e)}), 500


@bp.route("/api/expert/projects/<project_id>/deploy-status", methods=["GET"])
def api_deploy_status(project_id):
    """Poll deployment status (AJAX from project detail page)."""
    if not config.EXPERT_MODE_ENABLED:
        return jsonify({"error": "Expert mode not enabled"}), 403

    project = store.get_project(project_id)
    if not project:
        return jsonify({"error": "Project not found"}), 404

    if not project.staging_coolify_app_uuid and not project.production_coolify_app_uuid:
        return jsonify({"status": "not_deployed"})

    if not config.COOLIFY_API_TOKEN:
        return jsonify({"status": "unknown", "error": "Coolify not configured"})

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

        staging_preview_url = _preview_url(project.slug, "staging") if project.staging_deploy_url else None
        production_preview_url = _preview_url(project.slug, "production") if project.production_deploy_url else None

        primary_url = production_preview_url or staging_preview_url or _publicize_deploy_url(
            project.production_deploy_url or project.staging_deploy_url or project.deploy_url
        )

        return jsonify({
            "status": overall_status,
            "deploy_url": primary_url,
            "staging": {
                "status": staging_detail.get("status", "unknown") if staging_detail else "not_deployed",
                "deploy_url": staging_preview_url,
                "technical_deploy_url": _publicize_deploy_url(project.staging_deploy_url),
                "app_uuid": project.staging_coolify_app_uuid,
                "detail": staging_detail,
            },
            "production": {
                "status": production_detail.get("status", "unknown") if production_detail else "not_deployed",
                "deploy_url": production_preview_url,
                "technical_deploy_url": _publicize_deploy_url(project.production_deploy_url),
                "app_uuid": project.production_coolify_app_uuid,
                "detail": production_detail,
            },
        })
    except Exception as e:
        logger.exception("Deploy status check failed")
        return jsonify({"status": "error", "error": str(e)}), 500
