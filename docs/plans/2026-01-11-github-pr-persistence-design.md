# GitHub PR Persistence for Knowledge/Skills

## Problem

Currently, deploying replaces `knowledge/` and `skills/` via rsync. Users can edit these files via the web UI, but changes are lost on next deploy.

## Solution

Replace the current flow with GitHub PR-based persistence:

1. User edits stay in staging until "commit"
2. Commit creates a GitHub PR instead of writing to filesystem
3. Someone merges the PR manually
4. Deploy does `git pull` instead of rsync

Changes only go live after merge + deploy (or a pull trigger).

## Architecture

```
User edits file via web UI
      │
      ▼
┌─────────────┐
│ Staging dir │  (preview, iterate with agent)
└─────────────┘
      │ commit
      ▼
┌─────────────────────────────┐
│ GitHub API                  │
│ - Create branch             │
│ - Commit file(s)            │
│ - Create PR                 │
└─────────────────────────────┘
      │
      ▼
PR URL returned to user
      │
      ▼ (manual merge by maintainer)
┌─────────────┐
│ main branch │
└─────────────┘
      │
      ▼ (GitHub Actions triggered)
┌─────────────────────────────┐
│ deploy-content.yml          │
│ SSH to server, git checkout │
└─────────────────────────────┘
      │
      ▼
┌─────────────┐
│ Server      │  (changes live)
└─────────────┘
```

**Audit trail:** Git history replaces JOURNAL.md. Each PR includes conversation ID for traceability.

## Changes Required

### 1. GitHub Token Configuration

Add to `.env`:

```
GITHUB_PR_TOKEN=ghp_...
GITHUB_REPO=gip-inclusion/matometa
GITHUB_BRANCH=main
```

Token needs (fine-grained PAT):
- Repository: single repo only
- Permissions: `contents:write`, `pull_requests:write`, `metadata:read`

### 2. Deploy Script

Replace rsync with git pull for knowledge/skills:

```bash
# deploy/deploy.sh

# Sync code (still rsync, excludes knowledge/ and skills/)
RSYNC_OPTS=(
    -avz
    --delete
    --exclude='.git'
    --exclude='knowledge/'   # NEW: exclude from rsync
    --exclude='skills/'      # NEW: exclude from rsync
    # ... existing excludes
)
rsync "${RSYNC_OPTS[@]}" "$LOCAL_DIR/" "$SERVER:$REMOTE_DIR/"

# Pull knowledge/skills from git
ssh "$SERVER" "cd $REMOTE_DIR && git fetch origin && git checkout origin/main -- knowledge/ skills/"
```

Alternative: full git-based deploy (simpler but bigger change):

```bash
ssh "$SERVER" "cd $REMOTE_DIR && git pull origin main"
```

### 3. GitHub API Module

New file: `web/github.py`

```python
"""GitHub API integration for PR-based persistence."""

import base64
import os
from typing import Optional
import requests

GITHUB_API = "https://api.github.com"


class GitHubClient:
    def __init__(self):
        self.token = os.environ.get("GITHUB_PR_TOKEN")
        self.repo = os.environ.get("GITHUB_REPO")
        self.base_branch = os.environ.get("GITHUB_BRANCH", "main")

        if not self.token or not self.repo:
            raise RuntimeError("GITHUB_PR_TOKEN and GITHUB_REPO must be set")

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def get_file_sha(self, path: str, branch: str = None) -> Optional[str]:
        """Get current SHA of a file (needed for updates)."""
        branch = branch or self.base_branch
        resp = requests.get(
            f"{GITHUB_API}/repos/{self.repo}/contents/{path}",
            headers=self._headers(),
            params={"ref": branch},
        )
        if resp.status_code == 200:
            return resp.json()["sha"]
        return None

    def get_branch_sha(self, branch: str = None) -> str:
        """Get SHA of branch HEAD."""
        branch = branch or self.base_branch
        resp = requests.get(
            f"{GITHUB_API}/repos/{self.repo}/git/ref/heads/{branch}",
            headers=self._headers(),
        )
        resp.raise_for_status()
        return resp.json()["object"]["sha"]

    def create_branch(self, branch_name: str) -> None:
        """Create a new branch from base branch."""
        sha = self.get_branch_sha()
        resp = requests.post(
            f"{GITHUB_API}/repos/{self.repo}/git/refs",
            headers=self._headers(),
            json={
                "ref": f"refs/heads/{branch_name}",
                "sha": sha,
            },
        )
        resp.raise_for_status()

    def update_file(
        self,
        path: str,
        content: str,
        message: str,
        branch: str,
    ) -> None:
        """Create or update a file on a branch."""
        sha = self.get_file_sha(path, branch)

        payload = {
            "message": message,
            "content": base64.b64encode(content.encode()).decode(),
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha

        resp = requests.put(
            f"{GITHUB_API}/repos/{self.repo}/contents/{path}",
            headers=self._headers(),
            json=payload,
        )
        resp.raise_for_status()

    def create_pr(
        self,
        title: str,
        branch: str,
        body: str = "",
    ) -> str:
        """Create a pull request, return PR URL."""
        resp = requests.post(
            f"{GITHUB_API}/repos/{self.repo}/pulls",
            headers=self._headers(),
            json={
                "title": title,
                "head": branch,
                "base": self.base_branch,
                "body": body,
            },
        )
        resp.raise_for_status()
        return resp.json()["html_url"]

    def create_knowledge_pr(
        self,
        files: dict[str, str],  # {path: content}
        summary: str,
        conversation_id: str,
    ) -> str:
        """
        Create a PR with multiple file changes.

        Args:
            files: Dict mapping file paths to their new content
            summary: Commit message / PR title
            conversation_id: For branch naming

        Returns:
            PR URL
        """
        branch_name = f"knowledge-update-{conversation_id[:8]}"

        # Create branch
        self.create_branch(branch_name)

        # Update each file
        for path, content in files.items():
            self.update_file(
                path=path,
                content=content,
                message=summary,
                branch=branch_name,
            )

        # Create PR
        file_list = "\n".join(f"- `{path}`" for path in files.keys())
        body = f"Files updated:\n{file_list}\n\nConversation: {conversation_id}"

        return self.create_pr(
            title=summary,
            branch=branch_name,
            body=body,
        )
```

### 4. Update Commit Endpoint

Modify `web/routes/knowledge.py`:

```python
from ..github import GitHubClient

@bp.route("/conversations/<conv_id>/commit", methods=["POST"])
def commit_knowledge_changes(conv_id: str):
    """Create GitHub PR with staged changes."""
    conv = store.get_conversation(conv_id, include_messages=False)
    if not conv or conv.conv_type != "knowledge":
        return jsonify({"error": "Knowledge conversation not found"}), 404

    if conv.status != "active":
        return jsonify({"error": "Conversation is not active"}), 400

    staging_dir = get_staging_dir(conv_id)
    if not staging_dir.exists():
        return jsonify({"error": "No staged files"}), 400

    staged_files = list_staged_files(conv_id)
    if not staged_files:
        return jsonify({"error": "No staged files"}), 400

    data = request.get_json() or {}
    summary = data.get("summary", "Knowledge update")

    # Collect file contents
    files = {}
    for rel_path in staged_files:
        src = staging_dir / rel_path
        if src.exists():
            # Path in repo includes knowledge/ prefix
            repo_path = f"knowledge/{rel_path}"
            files[repo_path] = src.read_text()

    # Create GitHub PR
    try:
        github = GitHubClient()
        pr_url = github.create_knowledge_pr(
            files=files,
            summary=summary,
            conversation_id=conv_id,
        )
    except Exception as e:
        return jsonify({"error": f"GitHub PR creation failed: {e}"}), 500

    # Clean up staging
    shutil.rmtree(staging_dir, ignore_errors=True)
    store.update_conversation(conv_id, status="committed")

    # Store PR URL on conversation for reference
    store.update_conversation(conv_id, pr_url=pr_url)

    return jsonify({
        "status": "committed",
        "files": list(files.keys()),
        "conversation_id": conv_id,
        "pr_url": pr_url,
    })
```

### 5. Show PR Link in Conversation

The frontend should display the PR URL when commit returns. Options:

A) Toast notification with link
B) System message injected into conversation
C) Both

Recommend B: inject a system message so it's preserved in history:

```python
# After successful PR creation
store.add_message(
    conv_id,
    type="system",
    content=f"Changes submitted as PR: {pr_url}",
)
```

### 6. Database Schema Update

Add `pr_url` column to conversations table:

```sql
ALTER TABLE conversations ADD COLUMN pr_url TEXT;
```

Or handle in `store.update_conversation()` if using flexible schema.

### 7. GitHub Actions Auto-Deploy

New file: `.github/workflows/deploy-content.yml`

```yaml
name: Deploy Content Changes

on:
  push:
    branches: [main]
    paths:
      - 'knowledge/**'
      - 'skills/**'

jobs:
  deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Pull changes on server
        uses: appleboy/ssh-action@v1.0.3
        with:
          host: ljt.cc
          username: matometa
          key: ${{ secrets.DEPLOY_SSH_KEY }}
          script: |
            cd /srv/matometa
            git fetch origin main
            git checkout origin/main -- knowledge/ skills/
```

Requires adding `DEPLOY_SSH_KEY` secret to the repo (SSH private key for matometa@ljt.cc).

### 8. Remove JOURNAL.md Logging

The current commit endpoint appends to JOURNAL.md. This is no longer needed since:
- PR descriptions capture the change summary
- Git history provides full audit trail
- Commit messages include conversation ID for traceability

Remove the JOURNAL.md update code from `commit_knowledge_changes()`.

JOURNAL.md itself can be archived or deleted from the repo.

## Migration Path

1. Add `GITHUB_PR_TOKEN` and `GITHUB_REPO` to server `.env`
2. Generate SSH deploy key, add public key to server, private key to GitHub secrets as `DEPLOY_SSH_KEY`
3. Deploy the code changes (still via old rsync for this deploy)
4. Add GitHub Actions workflow
5. Test with a knowledge edit → verify PR created → merge → verify auto-deploy
6. Update deploy script to exclude knowledge/skills from rsync (git manages them now)
7. Archive or delete JOURNAL.md

## Future Enhancements

- Auto-merge for certain paths (e.g., `knowledge/sites/*.md`)
- Webhook to auto-pull when PRs merge
- Privileged users who can merge their own PRs
- Conflict detection (warn if file changed since conversation started)

## Security Considerations

- Token stored in `.env` as `GITHUB_PR_TOKEN`, never in code
- Fine-grained PAT scoped to single repo
- Only `contents` and `pull_requests` permissions
- Branch names include conversation ID (audit trail)
- No direct push to main (always via PR)
