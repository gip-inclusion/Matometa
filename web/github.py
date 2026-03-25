"""GitHub API integration for PR-based persistence."""

import base64
import os
from typing import Optional

import requests

GITHUB_API = "https://api.github.com"


class GitHubError(Exception):
    """GitHub API error."""

    pass


class GitHubClient:
    def __init__(self):
        self.token = os.environ.get("GITHUB_PR_TOKEN")
        self.repo = os.environ.get("GITHUB_REPO")
        self.base_branch = os.environ.get("GITHUB_BRANCH", "main")

        if not self.token or not self.repo:
            raise GitHubError("GITHUB_PR_TOKEN and GITHUB_REPO must be set")

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        resp = requests.request(method, url, headers=self._headers(), **kwargs)
        if not resp.ok:
            try:
                error = resp.json().get("message", resp.text)
            except Exception:
                error = resp.text
            raise GitHubError(f"GitHub API error ({resp.status_code}): {error}")
        return resp

    def get_file_sha(self, path: str, branch: str = None) -> Optional[str]:
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
        branch = branch or self.base_branch
        resp = self._request(
            "GET",
            f"{GITHUB_API}/repos/{self.repo}/git/ref/heads/{branch}",
        )
        return resp.json()["object"]["sha"]

    def create_branch(self, branch_name: str) -> None:
        sha = self.get_branch_sha()
        self._request(
            "POST",
            f"{GITHUB_API}/repos/{self.repo}/git/refs",
            json={
                "ref": f"refs/heads/{branch_name}",
                "sha": sha,
            },
        )

    def update_file(
        self,
        path: str,
        content: str,
        message: str,
        branch: str,
    ) -> None:
        sha = self.get_file_sha(path, branch)

        payload = {
            "message": message,
            "content": base64.b64encode(content.encode()).decode(),
            "branch": branch,
        }
        if sha:
            payload["sha"] = sha

        self._request(
            "PUT",
            f"{GITHUB_API}/repos/{self.repo}/contents/{path}",
            json=payload,
        )

    def create_pr(
        self,
        title: str,
        branch: str,
        body: str = "",
    ) -> str:
        resp = self._request(
            "POST",
            f"{GITHUB_API}/repos/{self.repo}/pulls",
            json={
                "title": title,
                "head": branch,
                "base": self.base_branch,
                "body": body,
            },
        )
        return resp.json()["html_url"]

    def create_knowledge_pr(
        self,
        files: dict[str, str],
        summary: str,
        conversation_id: str,
    ) -> str:
        branch_name = f"knowledge-update-{conversation_id[:8]}"

        self.create_branch(branch_name)

        for path, content in files.items():
            self.update_file(
                path=path,
                content=content,
                message=summary,
                branch=branch_name,
            )

        file_list = "\n".join(f"- `{path}`" for path in files.keys())
        body = f"Files updated:\n{file_list}\n\nConversation: `{conversation_id}`"

        return self.create_pr(
            title=summary,
            branch=branch_name,
            body=body,
        )
