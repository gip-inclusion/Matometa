"""Git helpers for expert-mode projects (staging/prod workflow)."""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

from web import config

logger = logging.getLogger(__name__)


def authenticated_clone_url(repo_path: str) -> str:
    """Build an authenticated HTTP clone URL for Gitea using the configured token."""
    base = config.GITEA_URL.rstrip("/")
    parts = urlsplit(base)

    token = quote(config.GITEA_API_TOKEN or "", safe="")
    netloc = f"{token}@{parts.netloc}" if token else parts.netloc
    base_path = parts.path.rstrip("/")
    clone_path = f"{base_path}/{repo_path}.git" if base_path else f"/{repo_path}.git"

    return urlunsplit((parts.scheme, netloc, clone_path, "", ""))


def extract_owner_repo_from_url(repo_url: str) -> tuple[str, str]:
    """Extract owner/repo from an HTTP(S) Gitea URL."""
    path = urlsplit(repo_url).path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]

    parts = [p for p in path.split("/") if p]
    if len(parts) < 2:
        raise ValueError(f"Invalid Gitea repo URL: {repo_url}")

    return parts[-2], parts[-1]


def run_git(workdir: Path, *args: str, timeout: int = 40) -> str:
    """Run a git command and return stdout."""
    result = subprocess.run(
        ["git", *args],
        cwd=workdir,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.stdout.strip()


def ensure_local_git_repo(project) -> bool:
    """Ensure project working directory is a valid local clone of its Gitea repository."""
    workdir = config.PROJECTS_DIR / project.id
    if (workdir / ".git").exists():
        return True
    if not project.gitea_url:
        return False

    owner, repo = extract_owner_repo_from_url(project.gitea_url)
    clone_url = authenticated_clone_url(f"{owner}/{repo}")
    workdir.mkdir(parents=True, exist_ok=True)

    existing_files = [p for p in workdir.iterdir() if p.name != ".git"]
    try:
        if not existing_files:
            subprocess.run(
                ["git", "clone", clone_url, str(workdir)],
                check=True,
                capture_output=True,
                timeout=40,
            )
        else:
            # Preserve existing local files, then import them into a clean clone.
            with tempfile.TemporaryDirectory(prefix=f"matometa-{project.id}-") as tmpdir:
                tmp_path = Path(tmpdir)
                shutil.copytree(workdir, tmp_path, dirs_exist_ok=True)

                for child in list(workdir.iterdir()):
                    if child.is_dir():
                        shutil.rmtree(child)
                    else:
                        child.unlink()

                subprocess.run(
                    ["git", "clone", clone_url, str(workdir)],
                    check=True,
                    capture_output=True,
                    timeout=40,
                )

                for child in tmp_path.iterdir():
                    if child.name == ".git":
                        continue
                    target = workdir / child.name
                    if child.is_dir():
                        shutil.copytree(child, target, dirs_exist_ok=True)
                    else:
                        shutil.copy2(child, target)

                ensure_git_identity(workdir)
                run_git(workdir, "add", "-A")
                diff = run_git(workdir, "diff", "--cached", "--name-only")
                if diff:
                    run_git(workdir, "commit", "-m", "chore: import existing project files")
                    run_git(workdir, "push", "origin", "HEAD:main")

        ensure_git_identity(workdir)
        return True
    except Exception:
        logger.exception("Failed to initialize local git repo for project %s", project.id)
        return False


def ensure_git_identity(workdir: Path):
    """Configure commit identity for automated expert commits."""
    run_git(workdir, "config", "user.email", "matometa@localhost")
    run_git(workdir, "config", "user.name", "Matometa")


def _remote_branch_exists(workdir: Path, branch: str) -> bool:
    output = run_git(workdir, "ls-remote", "--heads", "origin", branch)
    return bool(output.strip())


def _local_branch_exists(workdir: Path, branch: str) -> bool:
    try:
        run_git(workdir, "show-ref", "--verify", f"refs/heads/{branch}")
        return True
    except Exception:
        return False


def _resolve_base_branch(workdir: Path) -> str:
    """Find a usable default branch from origin (prefer main)."""
    for candidate in ("main", "master"):
        if _remote_branch_exists(workdir, candidate):
            return candidate
    # Fall back to current branch if remote discovery fails
    current = run_git(workdir, "rev-parse", "--abbrev-ref", "HEAD")
    return current if current and current != "HEAD" else "main"


def ensure_branch(workdir: Path, branch: str):
    """Ensure a branch exists locally/remotely and checkout it."""
    run_git(workdir, "fetch", "origin")
    remote_exists = _remote_branch_exists(workdir, branch)
    local_exists = _local_branch_exists(workdir, branch)

    if local_exists:
        run_git(workdir, "checkout", branch)
    elif remote_exists:
        run_git(workdir, "checkout", "-b", branch, f"origin/{branch}")
    else:
        base = _resolve_base_branch(workdir)
        run_git(workdir, "checkout", "-B", branch, f"origin/{base}")

    if not remote_exists:
        run_git(workdir, "push", "-u", "origin", branch)


def ensure_project_branches(project):
    """Ensure staging and production branches exist; leave repo on staging."""
    workdir = config.PROJECTS_DIR / project.id
    if not (workdir / ".git").exists():
        return

    staging = project.staging_branch or config.EXPERT_STAGING_BRANCH
    production = project.production_branch or config.EXPERT_PRODUCTION_BRANCH

    ensure_git_identity(workdir)
    ensure_branch(workdir, staging)
    ensure_branch(workdir, production)
    ensure_branch(workdir, staging)


def commit_and_push_staging_if_changed(project, conversation_id: str | None = None) -> dict | None:
    """Commit and push all local changes to the staging branch if needed."""
    workdir = config.PROJECTS_DIR / project.id
    if not (workdir / ".git").exists():
        return None

    staging = project.staging_branch or config.EXPERT_STAGING_BRANCH
    ensure_git_identity(workdir)

    current_branch = run_git(workdir, "rev-parse", "--abbrev-ref", "HEAD")
    if current_branch != staging:
        # Only switch branches when working tree is clean.
        dirty = run_git(workdir, "status", "--porcelain")
        if dirty.strip():
            raise RuntimeError(
                f"Cannot switch to staging branch {staging} with local uncommitted changes on {current_branch}"
            )
        ensure_branch(workdir, staging)

    run_git(workdir, "add", "-A")
    changed = run_git(workdir, "diff", "--cached", "--name-only")
    if not changed:
        return None

    changed_files = [line for line in changed.splitlines() if line.strip()]
    suffix = conversation_id[:8] if conversation_id else "manual"
    message = f"chore(expert): update via conversation {suffix}"

    run_git(workdir, "commit", "-m", message)
    run_git(workdir, "push", "origin", staging)
    commit_hash = run_git(workdir, "rev-parse", "--short", "HEAD")

    return {
        "branch": staging,
        "commit": commit_hash,
        "files": changed_files,
    }


def promote_staging_to_production(project) -> dict:
    """Merge staging into production branch and push production."""
    workdir = config.PROJECTS_DIR / project.id
    if not (workdir / ".git").exists():
        raise RuntimeError("Project git repository is not initialized")

    staging = project.staging_branch or config.EXPERT_STAGING_BRANCH
    production = project.production_branch or config.EXPERT_PRODUCTION_BRANCH

    ensure_project_branches(project)
    run_git(workdir, "fetch", "origin")

    ensure_branch(workdir, production)
    run_git(workdir, "merge", "--no-edit", f"origin/{staging}")
    run_git(workdir, "push", "origin", production)
    commit_hash = run_git(workdir, "rev-parse", "--short", "HEAD")

    # Keep expert editing branch as staging by default.
    ensure_branch(workdir, staging)

    return {
        "production_branch": production,
        "source_branch": staging,
        "commit": commit_hash,
    }
