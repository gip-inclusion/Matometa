"""Async code review agent for expert-mode projects.

Calls a local Ollama model to review the staged diff after each commit.
Designed to run in parallel with deploy — non-blocking, advisory only.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

import httpx

from web import config

logger = logging.getLogger(__name__)

# Ollama endpoint — reuse the same config as the rest of Matometa.
OLLAMA_URL = getattr(config, "OLLAMA_URL", "http://localhost:11434")
REVIEW_MODEL = getattr(config, "REVIEW_MODEL", "qwen3.5:latest")

REVIEW_PROMPT = """\
You are a code reviewer. Review the following git diff and report any issues.

Focus on:
- Bugs, logic errors, off-by-one mistakes
- Security issues (hardcoded secrets, injection, auth bypass)
- Missing error handling on I/O or network calls
- Dead code or unused imports introduced in this diff

Output a concise structured report:

## Review
**Files**: {n_files} | **Lines**: +{added}/-{removed}

### Findings
For each finding:
#### [{severity}] {file}:{line} — {title}
{explanation}
**Fix**: {suggestion}

Severity levels: Critical, Major, Minor.
If no issues found, say "No issues found." in one line. Do not invent problems.

```diff
{diff}
```
"""


def _get_diff(workdir: Path, commit_hash: str) -> str:
    """Get the diff for a specific commit."""
    try:
        result = subprocess.run(
            ["git", "diff", f"{commit_hash}~1..{commit_hash}"],
            cwd=workdir,
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        return result.stdout.strip()
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        logger.warning("Failed to get diff for %s: %s", commit_hash, exc)
        return ""


def _diff_stats(diff: str) -> tuple[int, int, int]:
    """Count files, added lines, removed lines."""
    files, added, removed = set(), 0, 0
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            files.add(line[6:])
        elif line.startswith("+") and not line.startswith("+++"):
            added += 1
        elif line.startswith("-") and not line.startswith("---"):
            removed += 1
    return len(files), added, removed


def review_commit(project_id: str, commit_hash: str) -> dict | None:
    """Review a commit diff using a local Ollama model.

    Returns {"review": str, "model": str} on success, None on failure.
    This is a blocking call — run via asyncio.to_thread().
    """
    workdir = config.PROJECTS_DIR / project_id
    diff = _get_diff(workdir, commit_hash)
    if not diff:
        return None

    n_files, added, removed = _diff_stats(diff)

    # Truncate very large diffs to avoid overwhelming the model.
    max_diff_chars = 12_000
    if len(diff) > max_diff_chars:
        diff = diff[:max_diff_chars] + "\n... (diff truncated)"

    prompt = REVIEW_PROMPT.format(
        diff=diff,
        n_files=n_files,
        added=added,
        removed=removed,
    )

    try:
        response = httpx.post(
            f"{OLLAMA_URL}/api/chat",
            json={
                "model": REVIEW_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": 0.2, "num_predict": 2048},
            },
            timeout=120,
        )
        response.raise_for_status()
        data = response.json()
        review_text = data.get("message", {}).get("content", "")
        return {
            "review": review_text,
            "model": REVIEW_MODEL,
        }
    except Exception as exc:
        logger.warning("Ollama review failed for %s/%s: %s", project_id, commit_hash, exc)
        return None
