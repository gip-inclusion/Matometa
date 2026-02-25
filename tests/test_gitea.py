"""Integration tests for Gitea API client.

These tests require a running Gitea instance.
Run with: pytest tests/test_gitea.py -m integration
"""

import pytest
import uuid

from web import config


@pytest.fixture
def gitea_client():
    """Create a Gitea client (requires GITEA_API_TOKEN in env)."""
    # Skip if not configured
    if not config.GITEA_API_TOKEN:
        pytest.skip("GITEA_API_TOKEN not configured")

    from lib.gitea import GiteaClient

    return GiteaClient()


@pytest.fixture
def gitea_repo(gitea_client):
    """Create a temporary Gitea repo for testing."""
    owner = config.GITEA_ORG or "matometa"
    name = f"test-{uuid.uuid4().hex[:8]}"

    repo = gitea_client.create_repo(name=name, description="Automated test repo", org=owner)
    yield repo

    # Cleanup
    try:
        gitea_client.delete_repo(owner, repo["name"])
    except Exception:
        pass


@pytest.mark.integration
class TestGiteaClient:
    """Test Gitea API operations against a running instance."""

    def test_create_repo(self, gitea_client):
        owner = config.GITEA_ORG or "matometa"
        name = f"test-create-{uuid.uuid4().hex[:8]}"

        repo = gitea_client.create_repo(name=name, description="Test create")
        assert repo["name"] == name
        assert repo["private"] is True
        assert repo["default_branch"] == "main"

        # Cleanup
        gitea_client.delete_repo(owner, repo["name"])

    def test_get_repo(self, gitea_client, gitea_repo):
        owner = config.GITEA_ORG or "matometa"
        fetched = gitea_client.get_repo(owner, gitea_repo["name"])
        assert fetched["id"] == gitea_repo["id"]
        assert fetched["name"] == gitea_repo["name"]

    def test_push_files(self, gitea_client, gitea_repo):
        owner = config.GITEA_ORG or "matometa"
        result = gitea_client.push_files(
            owner=owner,
            repo=gitea_repo["name"],
            branch="main",
            files={
                "hello.txt": "Hello, World!",
                "docs/readme.md": "# Test\nAutomated test file.",
            },
            message="test: push files via API",
        )
        assert result  # Non-empty response

    def test_create_branch(self, gitea_client, gitea_repo):
        owner = config.GITEA_ORG or "matometa"
        branch = gitea_client.create_branch(
            owner=owner,
            repo=gitea_repo["name"],
            branch="feature-test",
            ref="main",
        )
        assert branch["name"] == "feature-test"

    def test_create_pull_request(self, gitea_client, gitea_repo):
        owner = config.GITEA_ORG or "matometa"
        # Create a branch with a file change
        gitea_client.create_branch(
            owner=owner,
            repo=gitea_repo["name"],
            branch="pr-test",
            ref="main",
        )
        gitea_client.push_files(
            owner=owner,
            repo=gitea_repo["name"],
            branch="pr-test",
            files={"pr-file.txt": "PR content"},
            message="test: add file for PR",
        )

        pr = gitea_client.create_pull_request(
            owner=owner,
            repo=gitea_repo["name"],
            source="pr-test",
            target="main",
            title="Test PR",
        )
        assert pr["title"] == "Test PR"
        assert pr["head"]["label"] == "pr-test"

    def test_version(self, gitea_client):
        version = gitea_client.version()
        assert version  # Non-empty string
