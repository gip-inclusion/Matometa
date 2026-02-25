"""Coolify PaaS API client (v4 API)."""

import logging
import requests

from web import config

logger = logging.getLogger(__name__)


class CoolifyClient:
    """Client for Coolify v4 PaaS API (same machine)."""

    def __init__(self):
        self.base_url = config.COOLIFY_URL.rstrip("/")
        self.token = config.COOLIFY_API_TOKEN
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {self.token}"
        self._session.headers["Accept"] = "application/json"
        self._session.headers["Content-Type"] = "application/json"

    def _url(self, path: str) -> str:
        return f"{self.base_url}/api/v1{path}"

    def create_project(self, name: str, description: str = "") -> dict:
        """Create a Coolify project (container for environments/apps)."""
        payload = {"name": name, "description": description}
        resp = self._session.post(self._url("/projects"), json=payload)
        resp.raise_for_status()
        return resp.json()

    def get_project(self, project_uuid: str) -> dict:
        """Get project details including environments."""
        resp = self._session.get(self._url(f"/projects/{project_uuid}"))
        resp.raise_for_status()
        return resp.json()

    def create_application(
        self,
        name: str,
        git_repo_url: str,
        git_branch: str,
        server_uuid: str,
        project_uuid: str,
        environment_name: str = "production",
        ports_exposes: str = "5000",
        ports_mappings: str | None = None,
        build_pack: str = "dockerfile",
        private_key_uuid: str | None = None,
    ) -> dict:
        """Create a new application from a git repository.

        Uses private-deploy-key endpoint with SSH URL for Gitea repos.
        The git_repo_url should be an SSH URL like git@matometa-gitea:org/repo.git
        (using Docker DNS name, not host.docker.internal).
        """
        payload = {
            "name": name,
            "git_repository": git_repo_url,
            "git_branch": git_branch,
            "server_uuid": server_uuid,
            "project_uuid": project_uuid,
            "environment_name": environment_name,
            "build_pack": build_pack,
            "ports_exposes": ports_exposes,
        }

        if ports_mappings:
            payload["ports_mappings"] = ports_mappings

        if private_key_uuid:
            payload["private_key_uuid"] = private_key_uuid
            endpoint = "/applications/private-deploy-key"
        else:
            endpoint = "/applications/public"

        resp = self._session.post(self._url(endpoint), json=payload)
        resp.raise_for_status()
        return resp.json()

    def get_deploy_key_uuid(self, name_contains: str = "gitea") -> str | None:
        """Find the UUID of the deploy key for Gitea SSH access."""
        resp = self._session.get(self._url("/security/keys"))
        if resp.status_code != 200:
            return None
        for key in resp.json():
            if name_contains.lower() in key.get("name", "").lower():
                return key.get("uuid")
        return None

    def deploy(self, app_uuid: str) -> dict:
        """Trigger a deployment (restart with rebuild)."""
        resp = self._session.post(
            self._url(f"/applications/{app_uuid}/restart")
        )
        resp.raise_for_status()
        return resp.json()

    def get_status(self, app_uuid: str) -> dict:
        """Get application status."""
        resp = self._session.get(self._url(f"/applications/{app_uuid}"))
        resp.raise_for_status()
        return resp.json()

    def get_logs(self, app_uuid: str, lines: int = 50) -> str:
        """Get application logs."""
        resp = self._session.get(
            self._url(f"/applications/{app_uuid}/logs"),
            params={"lines": lines},
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list):
            return "\n".join(str(line) for line in data)
        return str(data)

    def get_webhook_secret(self, app_uuid: str, provider: str = "gitea") -> str | None:
        """Read the manual webhook secret for a provider from the app config."""
        data = self.get_status(app_uuid)
        return data.get(f"manual_webhook_secret_{provider}")

    def set_webhook_secret(self, app_uuid: str, secret: str, provider: str = "gitea") -> dict:
        """Set the manual webhook secret on a Coolify application."""
        payload = {f"manual_webhook_secret_{provider}": secret}
        resp = self._session.patch(self._url(f"/applications/{app_uuid}"), json=payload)
        resp.raise_for_status()
        return resp.json()

    def set_ports_mapping(self, app_uuid: str, ports_mappings: str) -> dict:
        """Set host:container port mapping for an application."""
        payload = {"ports_mappings": ports_mappings}
        resp = self._session.patch(self._url(f"/applications/{app_uuid}"), json=payload)
        resp.raise_for_status()
        return resp.json()

    def list_servers(self) -> list:
        """List all available servers."""
        resp = self._session.get(self._url("/servers"))
        resp.raise_for_status()
        return resp.json()

    def version(self) -> str:
        """Get Coolify version."""
        resp = self._session.get(self._url("/version"))
        resp.raise_for_status()
        return resp.text.strip().strip('"')
