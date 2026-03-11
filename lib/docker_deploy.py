"""Direct Docker Compose deployment manager (replaces Coolify).

Manages project containers via `docker compose` commands through the Docker socket.
Each project gets its own compose project in /app/data/projects/{id}/.
"""

import logging
import re
import subprocess
from pathlib import Path

from web import config

logger = logging.getLogger(__name__)

# Docker socket path (mounted from host)
DOCKER_SOCKET = "/var/run/docker.sock"

# Port ranges
STAGING_PORT_START = 18080
STAGING_PORT_END = 19999
PRODUCTION_PORT_START = 28080
PRODUCTION_PORT_END = 29999


def _run_compose(project_dir: Path, *args, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run a docker compose command in a project directory."""
    cmd = ["docker", "compose", "-f", str(project_dir / "docker-compose.yml"), *args]
    logger.info("Running: %s", " ".join(cmd))
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=str(project_dir),
    )


def _run_docker(*args, timeout: int = 30) -> subprocess.CompletedProcess:
    """Run a docker command."""
    cmd = ["docker", *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def docker_available() -> bool:
    """Check if Docker socket is accessible."""
    try:
        result = _run_docker("info", "--format", "{{.ServerVersion}}", timeout=5)
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def validate_compose(project_id: str) -> list[str]:
    """Check a project's docker-compose.yml for common issues.

    Returns a list of warning strings (empty = OK).
    """
    compose_file = config.PROJECTS_DIR / project_id / "docker-compose.yml"
    if not compose_file.exists():
        return ["No docker-compose.yml found"]

    content = compose_file.read_text()
    warnings = []

    # Check for hardcoded host port (should use ${HOST_PORT})
    import re
    # Match ports like "8080:8080", "80:80", "5432:5432" (without HOST_PORT)
    port_lines = re.findall(r'ports:\s*\n((?:\s+-\s*.*\n)*)', content)
    for block in port_lines:
        for line in block.strip().splitlines():
            line = line.strip().lstrip("- ").strip('"').strip("'")
            if "HOST_PORT" not in line and re.match(r'^\d+:\d+$', line):
                warnings.append(f"Hardcoded port mapping: {line} (use ${{HOST_PORT}} instead)")

    # Check for exposed database ports
    for bad_port in ("5432:5432", "3306:3306", "6379:6379", "27017:27017"):
        if bad_port in content:
            warnings.append(f"Database port exposed to host: {bad_port} (remove this)")

    return warnings


def validate_build_context(project_id: str) -> list[str]:
    """Check that files referenced in docker-compose.yml exist in the build context.

    Returns a list of warning strings (empty = OK).
    """
    workdir = config.PROJECTS_DIR / project_id
    compose_file = workdir / "docker-compose.yml"
    if not compose_file.exists():
        return ["No docker-compose.yml found"]

    warnings = []

    # Check Dockerfile exists
    content = compose_file.read_text()
    # If compose uses 'build: .' or 'build: { context: ... }', check Dockerfile
    if "build:" in content:
        dockerfile = workdir / "Dockerfile"
        if not dockerfile.exists():
            warnings.append("Dockerfile not found but docker-compose.yml has 'build:' directive")

    # Check volume-mounted files/dirs exist
    import yaml
    try:
        compose_data = yaml.safe_load(content)
        if not compose_data or "services" not in compose_data:
            return warnings

        for svc_name, svc in compose_data.get("services", {}).items():
            for vol in svc.get("volumes", []):
                if isinstance(vol, str) and ":" in vol:
                    host_path = vol.split(":")[0].strip()
                    if host_path.startswith("./") or host_path.startswith("../"):
                        abs_path = workdir / host_path
                        if not abs_path.exists():
                            warnings.append(
                                f"Service '{svc_name}': volume mount '{host_path}' does not exist"
                            )
    except Exception:
        pass  # yaml parsing failure is not fatal for validation

    return warnings


def deploy(project_id: str, environment: str = "staging") -> dict:
    """Build and start a project's containers.

    Returns dict with: status, port, container_name, error.
    On failure, includes 'logs' key with recent container output for diagnostics.
    """
    from web.database import ConversationStore
    store = ConversationStore()
    project = store.get_project(project_id)
    if not project:
        return {"status": "error", "error": "Project not found"}

    workdir = config.PROJECTS_DIR / project_id
    compose_file = workdir / "docker-compose.yml"

    if not compose_file.exists():
        return {"status": "error", "error": "No docker-compose.yml found"}

    # Validate compose file
    warnings = validate_compose(project_id)

    # Validate build context (missing files, volumes)
    context_warnings = validate_build_context(project_id)
    warnings.extend(context_warnings)

    if warnings:
        logger.warning("Compose validation for %s: %s", project_id, "; ".join(warnings))

    # Determine port
    port = _get_or_assign_port(project, environment, store)
    if not port:
        return {"status": "error", "error": "Could not assign port"}

    # Set environment for compose
    env_vars = {
        "HOST_PORT": str(port),
        "COMPOSE_PROJECT_NAME": f"{project.slug}-{environment}",
    }

    # Build
    result = _run_compose(workdir, "build", "--no-cache", timeout=300)
    if result.returncode != 0:
        logger.error("Build failed for %s/%s: %s", project.slug, environment, result.stderr[-500:])
        return {
            "status": "build_failed",
            "error": result.stderr[-1000:],
            "port": port,
            "warnings": warnings if warnings else None,
        }

    # Stop existing containers first (if any)
    _run_compose(workdir, "down", "--remove-orphans", timeout=30)

    # Start with port override
    up_env_args = []
    for k, v in env_vars.items():
        up_env_args.extend(["-e", f"{k}={v}"])

    # Use subprocess directly for env var injection
    cmd = [
        "docker", "compose",
        "-f", str(compose_file),
        "-p", f"{project.slug}-{environment}",
        "up", "-d", "--build",
    ]
    logger.info("Starting: %s (HOST_PORT=%s)", " ".join(cmd), port)
    import os
    env = dict(os.environ)
    env.update(env_vars)

    up_result = subprocess.run(
        cmd, capture_output=True, text=True, timeout=300,
        cwd=str(workdir), env=env,
    )

    if up_result.returncode != 0:
        logger.error("Up failed for %s/%s: %s", project.slug, environment, up_result.stderr[-500:])
        # Collect container logs for diagnostics
        diag_logs = logs(project_id, environment, lines=50)
        return {
            "status": "start_failed",
            "error": up_result.stderr[-1000:],
            "port": port,
            "logs": diag_logs,
            "warnings": warnings if warnings else None,
        }

    # Update DB with deploy URL
    deploy_url = f"http://localhost:{port}"
    if environment == "staging":
        store.update_project(project_id, staging_deploy_url=deploy_url, status="deployed")
    else:
        store.update_project(project_id, production_deploy_url=deploy_url, status="deployed")

    # Also update legacy fields
    store.update_project(project_id, deploy_url=deploy_url)

    return {
        "status": "running",
        "port": port,
        "deploy_url": deploy_url,
        "container_prefix": f"{project.slug}-{environment}",
    }


def status(project_id: str, environment: str = "staging") -> dict:
    """Get container status for a project environment.

    Returns dict with: status, port, uptime, health.
    """
    from web.database import ConversationStore
    store = ConversationStore()
    project = store.get_project(project_id)
    if not project:
        return {"status": "not_found"}

    project_name = f"{project.slug}-{environment}"

    result = _run_docker(
        "compose", "-p", project_name, "ps",
        "--format", "{{.Name}}\t{{.State}}\t{{.Status}}\t{{.Ports}}",
    )

    if result.returncode != 0 or not result.stdout.strip():
        return {"status": "not_deployed"}

    containers = []
    for line in result.stdout.strip().splitlines():
        parts = line.split("\t")
        if len(parts) >= 3:
            containers.append({
                "name": parts[0],
                "state": parts[1],
                "status_text": parts[2],
                "ports": parts[3] if len(parts) > 3 else "",
            })

    if not containers:
        return {"status": "not_deployed"}

    # Overall status: if any container is running, report running
    states = [c["state"] for c in containers]
    if "running" in states:
        overall = "running"
    elif "exited" in states:
        overall = "exited"
    else:
        overall = states[0] if states else "unknown"

    # Extract port from deploy URL
    deploy_url = (project.staging_deploy_url if environment == "staging"
                  else project.production_deploy_url)
    port = None
    if deploy_url:
        m = re.search(r":(\d+)$", deploy_url)
        if m:
            port = int(m.group(1))

    return {
        "status": overall,
        "containers": containers,
        "port": port,
        "deploy_url": deploy_url,
    }


def logs(project_id: str, environment: str = "staging", lines: int = 100) -> str:
    """Get container logs for a project."""
    from web.database import ConversationStore
    store = ConversationStore()
    project = store.get_project(project_id)
    if not project:
        return "Project not found"

    project_name = f"{project.slug}-{environment}"
    result = _run_docker(
        "compose", "-p", project_name, "logs",
        "--tail", str(lines), "--no-color",
        timeout=15,
    )
    return result.stdout or result.stderr or "No logs available"


def stop(project_id: str, environment: str = "staging") -> dict:
    """Stop project containers."""
    from web.database import ConversationStore
    store = ConversationStore()
    project = store.get_project(project_id)
    if not project:
        return {"status": "error", "error": "Project not found"}

    project_name = f"{project.slug}-{environment}"
    result = _run_docker("compose", "-p", project_name, "down", timeout=30)
    return {
        "status": "stopped" if result.returncode == 0 else "error",
        "output": result.stdout + result.stderr,
    }


def restart(project_id: str, environment: str = "staging") -> dict:
    """Restart project containers (without rebuild)."""
    from web.database import ConversationStore
    store = ConversationStore()
    project = store.get_project(project_id)
    if not project:
        return {"status": "error", "error": "Project not found"}

    workdir = config.PROJECTS_DIR / project_id
    project_name = f"{project.slug}-{environment}"

    # Determine port from existing deploy URL
    deploy_url = (project.staging_deploy_url if environment == "staging"
                  else project.production_deploy_url)
    port = None
    if deploy_url:
        m = re.search(r":(\d+)$", deploy_url)
        if m:
            port = int(m.group(1))

    if not port:
        port = _get_or_assign_port(project, environment, store)

    import os
    env = dict(os.environ)
    env["HOST_PORT"] = str(port)
    env["COMPOSE_PROJECT_NAME"] = project_name

    compose_file = workdir / "docker-compose.yml"
    if not compose_file.exists():
        return {"status": "error", "error": "No docker-compose.yml"}

    result = subprocess.run(
        ["docker", "compose", "-f", str(compose_file), "-p", project_name, "up", "-d"],
        capture_output=True, text=True, timeout=60,
        cwd=str(workdir), env=env,
    )

    return {
        "status": "running" if result.returncode == 0 else "error",
        "port": port,
        "output": result.stdout + result.stderr,
    }


def _get_or_assign_port(project, environment: str, store) -> int | None:
    """Get existing port from deploy URL or assign a new one."""
    deploy_url = (project.staging_deploy_url if environment == "staging"
                  else project.production_deploy_url)

    if deploy_url:
        m = re.search(r":(\d+)$", deploy_url)
        if m:
            return int(m.group(1))

    # Assign new port
    if environment == "staging":
        start, end = STAGING_PORT_START, STAGING_PORT_END
    else:
        start, end = PRODUCTION_PORT_START, PRODUCTION_PORT_END

    used_ports = _used_ports()
    for port in range(start, end + 1):
        if port not in used_ports:
            return port

    return None


def _used_ports() -> set[int]:
    """Collect all ports already assigned to projects."""
    from web.database import ConversationStore
    store = ConversationStore()
    used = set()
    for p in store.list_projects(limit=2000):
        for url in (p.deploy_url, p.staging_deploy_url, p.production_deploy_url):
            if url:
                m = re.search(r":(\d+)$", url)
                if m:
                    used.add(int(m.group(1)))
    return used


def health_check_all() -> dict[str, str]:
    """Check all project containers and return status map.

    Returns {project_slug: status} for all deployed projects.
    """
    from web.database import ConversationStore
    store = ConversationStore()
    results = {}

    for project in store.list_projects(limit=500):
        for env in ("staging", "production"):
            deploy_url = (project.staging_deploy_url if env == "staging"
                          else project.production_deploy_url)
            if not deploy_url:
                continue

            st = status(project.id, env)
            key = f"{project.slug}-{env}"
            results[key] = st.get("status", "unknown")

            # Auto-restart exited containers
            if st.get("status") == "exited":
                logger.info("Auto-restarting exited container: %s", key)
                restart(project.id, env)

    return results
