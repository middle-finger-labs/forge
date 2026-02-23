"""Integration tests for the GitHub integration layer.

These tests cover the full stack: identity management, API client, repo
connector, and issue tracker.  Tests that hit the real GitHub API are gated
behind environment variables and the ``integration`` pytest marker:

    GITHUB_TOKEN          — required for any API tests
    FORGE_TEST_REPO       — owner/repo for read-write tests (e.g. "acme/forge-test")
    FORGE_TEST_REPO_URL   — full clone URL (e.g. "git@github.com:acme/forge-test.git")

Run integration tests::

    GITHUB_TOKEN=ghp_xxx FORGE_TEST_REPO=owner/repo \\
        python -m pytest tests/test_github_integration.py -v

Unit tests in this file (identity manager, mocked client) always run.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import uuid
from unittest.mock import AsyncMock

import pytest
import yaml

from integrations.git_identity import (
    GitIdentity,
    GitIdentityManager,
    parse_github_url,
)
from integrations.github_client import (
    GitHubClient,
    GitHubError,
    GitHubNotFoundError,
)
from integrations.issue_tracker import IssueTracker
from integrations.repo_connector import RepoConnector

# ---------------------------------------------------------------------------
# Markers & environment helpers
# ---------------------------------------------------------------------------

_GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
_TEST_REPO = os.environ.get("FORGE_TEST_REPO", "")  # "owner/repo"
_TEST_REPO_URL = os.environ.get("FORGE_TEST_REPO_URL", "")  # clone URL

integration = pytest.mark.skipif(
    not _GITHUB_TOKEN,
    reason="GITHUB_TOKEN not set — skipping integration tests",
)

needs_test_repo = pytest.mark.skipif(
    not (_GITHUB_TOKEN and _TEST_REPO),
    reason="GITHUB_TOKEN and FORGE_TEST_REPO required",
)


def _test_identity() -> GitIdentity:
    """Build an identity suitable for integration tests."""
    return GitIdentity(
        name="integration-test",
        github_username="test-user",
        email="test@example.com",
        ssh_key_path=os.environ.get("FORGE_TEST_SSH_KEY", "~/.ssh/id_ed25519"),
        ssh_host_alias="github.com",
    )


def _test_repo_parts() -> tuple[str, str]:
    """Split FORGE_TEST_REPO into (owner, repo)."""
    owner, repo = _TEST_REPO.split("/", 1)
    return owner, repo


# ===================================================================
# SECTION 1: GitIdentityManager (unit tests — always run)
# ===================================================================


class TestIdentityManagerWithConfig:
    """Test GitIdentityManager against a real YAML config file."""

    @pytest.fixture()
    def config_dir(self, tmp_path):
        """Write a test identities.yaml with two identities."""
        config_file = tmp_path / "identities.yaml"
        config = {
            "identities": [
                {
                    "name": "personal",
                    "github_username": "nate",
                    "email": "nate@example.com",
                    "ssh_key_path": "~/.ssh/id_personal",
                    "ssh_host_alias": "github-personal",
                    "default": True,
                },
                {
                    "name": "work",
                    "github_username": "nate-corp",
                    "email": "nate@corp.com",
                    "ssh_key_path": "~/.ssh/id_work",
                    "ssh_host_alias": "github-work",
                    "github_org": "CorpInc",
                    "extra_orgs": ["CorpLabs"],
                },
            ],
        }
        with open(config_file, "w") as f:
            yaml.dump(config, f)
        return str(config_file)

    def test_loads_two_identities(self, config_dir):
        mgr = GitIdentityManager(config_path=config_dir)
        identities = mgr.list_identities()
        assert len(identities) == 2
        assert identities[0].name == "personal"
        assert identities[1].name == "work"

    def test_resolve_by_org(self, config_dir):
        mgr = GitIdentityManager(config_path=config_dir)
        ident = mgr.resolve_identity("git@github.com:CorpInc/project.git")
        assert ident.name == "work"

    def test_resolve_by_extra_org(self, config_dir):
        mgr = GitIdentityManager(config_path=config_dir)
        ident = mgr.resolve_identity("git@github.com:CorpLabs/toolkit.git")
        assert ident.name == "work"

    def test_resolve_by_username(self, config_dir):
        mgr = GitIdentityManager(config_path=config_dir)
        ident = mgr.resolve_identity("git@github.com:nate/dotfiles.git")
        assert ident.name == "personal"

    def test_resolve_falls_back_to_default(self, config_dir):
        mgr = GitIdentityManager(config_path=config_dir)
        ident = mgr.resolve_identity("git@github.com:UnknownOrg/repo.git")
        assert ident.name == "personal"
        assert ident.default is True

    def test_resolve_with_https_url(self, config_dir):
        mgr = GitIdentityManager(config_path=config_dir)
        ident = mgr.resolve_identity("https://github.com/CorpInc/app.git")
        assert ident.name == "work"

    def test_get_identity_by_name(self, config_dir):
        mgr = GitIdentityManager(config_path=config_dir)
        assert mgr.get_identity("work") is not None
        assert mgr.get_identity("work").github_org == "CorpInc"
        assert mgr.get_identity("nonexistent") is None

    def test_get_git_env(self, config_dir):
        mgr = GitIdentityManager(config_path=config_dir)
        ident = mgr.get_identity("work")
        env = mgr.get_git_env(ident)

        assert "GIT_SSH_COMMAND" in env
        assert "id_work" in env["GIT_SSH_COMMAND"]
        assert "IdentitiesOnly=yes" in env["GIT_SSH_COMMAND"]
        assert env["GIT_AUTHOR_NAME"] == "nate-corp"
        assert env["GIT_AUTHOR_EMAIL"] == "nate@corp.com"
        assert env["GIT_COMMITTER_NAME"] == "nate-corp"
        assert env["GIT_COMMITTER_EMAIL"] == "nate@corp.com"

    def test_get_ssh_url_rewrites(self, config_dir):
        mgr = GitIdentityManager(config_path=config_dir)
        ident = mgr.get_identity("work")

        rewritten = mgr.get_ssh_url("https://github.com/CorpInc/api.git", ident)
        assert rewritten == "git@github-work:CorpInc/api.git"

    def test_get_ssh_url_preserves_unparseable(self, config_dir):
        mgr = GitIdentityManager(config_path=config_dir)
        ident = mgr.get_identity("work")
        assert mgr.get_ssh_url("not-a-url", ident) == "not-a-url"

    def test_get_ssh_url_ssh_to_ssh(self, config_dir):
        mgr = GitIdentityManager(config_path=config_dir)
        ident = mgr.get_identity("personal")
        rewritten = mgr.get_ssh_url("git@github.com:nate/repo.git", ident)
        assert rewritten == "git@github-personal:nate/repo.git"

    def test_no_config_file(self, tmp_path):
        mgr = GitIdentityManager(config_path=str(tmp_path / "missing.yaml"))
        assert mgr.list_identities() == []

    def test_resolve_no_identities_raises(self, tmp_path):
        mgr = GitIdentityManager(config_path=str(tmp_path / "missing.yaml"))
        with pytest.raises(ValueError, match="No identities configured"):
            mgr.resolve_identity("git@github.com:any/repo.git")


# ===================================================================
# SECTION 2: GitHubClient (mocked unit tests)
# ===================================================================


class TestGitHubClientMocked:
    """Test GitHubClient with mocked HTTP — no real API calls."""

    @pytest.fixture(autouse=True)
    def _set_token(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_fake_for_tests")

    @pytest.fixture()
    def identity(self):
        return GitIdentity(
            name="mock",
            github_username="mock-user",
            email="mock@test.com",
            ssh_key_path="~/.ssh/id_mock",
            ssh_host_alias="github-mock",
        )

    @pytest.mark.asyncio
    async def test_get_authenticated_user_pat(self, identity):
        client = GitHubClient(identity)
        client._api = AsyncMock(
            return_value={"login": "mock-user", "id": 42, "name": "Mock"},
        )
        async with client:
            user = await client.get_authenticated_user()
        assert user["login"] == "mock-user"
        assert user["type"] == "user"
        client._api.assert_called_once_with("GET", "/user")

    @pytest.mark.asyncio
    async def test_get_repo_info(self, identity):
        client = GitHubClient(identity)
        client._api = AsyncMock(return_value={
            "full_name": "acme/widgets",
            "default_branch": "main",
            "language": "Python",
            "visibility": "private",
            "description": "Widget factory",
            "clone_url": "https://github.com/acme/widgets.git",
            "ssh_url": "git@github.com:acme/widgets.git",
            "archived": False,
            "fork": False,
        })
        async with client:
            info = await client.get_repo_info("acme", "widgets")
        assert info["full_name"] == "acme/widgets"
        assert info["default_branch"] == "main"
        assert info["language"] == "Python"

    @pytest.mark.asyncio
    async def test_create_issue(self, identity):
        client = GitHubClient(identity)
        client._api = AsyncMock(return_value={
            "number": 99,
            "url": "https://api.github.com/repos/acme/w/issues/99",
            "html_url": "https://github.com/acme/w/issues/99",
            "state": "open",
            "title": "Test issue",
        })
        async with client:
            result = await client.create_issue(
                "acme", "w", "Test issue", "Body here",
                labels=["forge"],
            )
        assert result["number"] == 99
        assert result["title"] == "Test issue"
        call_kwargs = client._api.call_args
        assert call_kwargs[0] == ("POST", "/repos/acme/w/issues")

    @pytest.mark.asyncio
    async def test_add_issue_comment(self, identity):
        client = GitHubClient(identity)
        client._api = AsyncMock(return_value={
            "id": 1234,
            "url": "https://api.github.com/repos/acme/w/issues/comments/1234",
            "html_url": "https://github.com/acme/w/issues/99#comment-1234",
            "body": "Hello",
        })
        async with client:
            result = await client.add_issue_comment("acme", "w", 99, "Hello")
        assert result["id"] == 1234

    @pytest.mark.asyncio
    async def test_create_pr(self, identity):
        client = GitHubClient(identity)
        client._api = AsyncMock(return_value={
            "number": 5,
            "url": "https://api.github.com/repos/acme/w/pulls/5",
            "html_url": "https://github.com/acme/w/pull/5",
            "state": "open",
            "draft": True,
            "head": {"ref": "feature-branch"},
            "base": {"ref": "main"},
        })
        async with client:
            result = await client.create_pr(
                "acme", "w", "Add auth", "PR body", "feature-branch",
            )
        assert result["number"] == 5
        assert result["head"] == "feature-branch"
        call_kwargs = client._api.call_args
        assert call_kwargs[1]["json"]["draft"] is True

    @pytest.mark.asyncio
    async def test_list_issues(self, identity):
        client = GitHubClient(identity)
        client._api = AsyncMock(return_value=[
            {
                "number": 1, "title": "First", "state": "open",
                "html_url": "https://github.com/acme/w/issues/1",
                "labels": [], "assignees": [],
                "created_at": "2025-01-01T00:00:00Z",
                "updated_at": "2025-01-01T00:00:00Z",
            },
            {
                "number": 2, "title": "Second", "state": "open",
                "html_url": "https://github.com/acme/w/issues/2",
                "labels": [{"name": "forge"}], "assignees": [],
                "created_at": "2025-01-02T00:00:00Z",
                "updated_at": "2025-01-02T00:00:00Z",
            },
        ])
        async with client:
            issues = await client.list_issues("acme", "w", labels=["forge"])
        assert len(issues) == 2
        assert issues[0]["number"] == 1
        assert issues[1]["labels"] == ["forge"]

    @pytest.mark.asyncio
    async def test_not_found_raises(self, identity):
        client = GitHubClient(identity)
        client._api = AsyncMock(side_effect=GitHubNotFoundError("not found"))
        async with client:
            with pytest.raises(GitHubNotFoundError):
                await client.get_repo_info("acme", "nonexistent")

    @pytest.mark.asyncio
    async def test_update_pr_state(self, identity):
        client = GitHubClient(identity)
        client._api = AsyncMock(return_value={
            "number": 5,
            "url": "https://api.github.com/repos/acme/w/pulls/5",
            "html_url": "https://github.com/acme/w/pull/5",
            "state": "closed",
        })
        async with client:
            result = await client.update_pr("acme", "w", 5, state="closed")
        assert result["state"] == "closed"


# ===================================================================
# SECTION 2b: GitHubClient (real API — requires GITHUB_TOKEN)
# ===================================================================


@integration
class TestGitHubClientReal:
    """Tests that hit the real GitHub API."""

    @pytest.fixture()
    def identity(self):
        return _test_identity()

    @pytest.mark.asyncio
    async def test_authenticated_user(self, identity, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", _GITHUB_TOKEN)
        async with GitHubClient(identity) as gh:
            user = await gh.get_authenticated_user()
        assert "login" in user or "name" in user
        assert user.get("type") in ("user", "app")

    @pytest.mark.asyncio
    async def test_get_public_repo_info(self, identity, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", _GITHUB_TOKEN)
        async with GitHubClient(identity) as gh:
            info = await gh.get_repo_info("octocat", "Hello-World")
        assert info["full_name"] == "octocat/Hello-World"
        assert info["default_branch"] is not None
        assert isinstance(info["fork"], bool)

    @pytest.mark.asyncio
    async def test_list_issues_public_repo(self, identity, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", _GITHUB_TOKEN)
        async with GitHubClient(identity) as gh:
            issues = await gh.list_issues(
                "octocat", "Hello-World", state="all", per_page=5,
            )
        # This famous repo has many issues
        assert isinstance(issues, list)

    @pytest.mark.asyncio
    async def test_not_found_repo(self, identity, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", _GITHUB_TOKEN)
        async with GitHubClient(identity) as gh:
            with pytest.raises(GitHubNotFoundError):
                await gh.get_repo_info(
                    "definitely-not-a-real-org-xyz", "nonexistent-repo",
                )


@needs_test_repo
class TestGitHubClientWriteOps:
    """Tests that create/modify GitHub resources.  Cleans up after itself."""

    @pytest.fixture()
    def identity(self):
        return _test_identity()

    @pytest.fixture()
    def repo_parts(self):
        return _test_repo_parts()

    @pytest.mark.asyncio
    async def test_create_and_close_issue(self, identity, repo_parts, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", _GITHUB_TOKEN)
        owner, repo = repo_parts
        tag = uuid.uuid4().hex[:8]

        async with GitHubClient(identity) as gh:
            # Create
            issue = await gh.create_issue(
                owner, repo,
                f"[test] Integration test {tag}",
                "Automated test — will be closed immediately.",
                labels=["forge-test"],
            )
            issue_number = issue["number"]
            assert issue_number > 0

            # Comment
            comment = await gh.add_issue_comment(
                owner, repo, issue_number, f"Test comment {tag}",
            )
            assert comment["id"] > 0

            # Close (cleanup)
            await gh.update_issue(owner, repo, issue_number, state="closed")

    @pytest.mark.asyncio
    async def test_create_branch_pr_and_cleanup(
        self, identity, repo_parts, monkeypatch,
    ):
        monkeypatch.setenv("GITHUB_TOKEN", _GITHUB_TOKEN)
        owner, repo = repo_parts
        branch_name = f"forge-test-{uuid.uuid4().hex[:8]}"

        async with GitHubClient(identity) as gh:
            # Get default branch
            info = await gh.get_repo_info(owner, repo)
            default_branch = info["default_branch"]

            # Create branch
            await gh.create_branch(owner, repo, branch_name, default_branch)

            # Create a draft PR
            pr = await gh.create_pr(
                owner, repo,
                f"[test] PR {branch_name}",
                "Automated integration test — will be closed.",
                branch_name, default_branch,
                draft=True,
            )
            assert pr["number"] > 0

            # Close PR (cleanup)
            await gh.update_pr(owner, repo, pr["number"], state="closed")

            # Delete branch (cleanup)
            try:
                await gh._api(
                    "DELETE",
                    f"/repos/{owner}/{repo}/git/refs/heads/{branch_name}",
                    expected=(204,),
                )
            except GitHubError:
                pass  # best-effort cleanup


# ===================================================================
# SECTION 3: RepoConnector (mocked unit tests)
# ===================================================================


class TestRepoConnectorMocked:
    """Test RepoConnector with fully mocked GitHubClient."""

    @pytest.fixture()
    def identity(self):
        return GitIdentity(
            name="test",
            github_username="test-user",
            email="test@co.com",
            ssh_key_path="~/.ssh/id_test",
            ssh_host_alias="github-test",
        )

    @pytest.fixture()
    def gh(self):
        mock = AsyncMock(spec=GitHubClient)
        mock.get_repo_info = AsyncMock(return_value={
            "full_name": "acme/app",
            "default_branch": "main",
            "language": "Python",
            "visibility": "private",
            "description": "Test app",
            "clone_url": "https://github.com/acme/app.git",
            "ssh_url": "git@github.com:acme/app.git",
            "archived": False,
            "fork": False,
        })
        mock.clone_repo = AsyncMock(return_value="/tmp/test/project")
        mock.push_branch = AsyncMock()
        mock.create_pr = AsyncMock(return_value={
            "number": 10,
            "html_url": "https://github.com/acme/app/pull/10",
            "url": "https://api.github.com/repos/acme/app/pulls/10",
            "state": "open",
        })
        mock.update_pr = AsyncMock(return_value={
            "number": 10,
            "html_url": "https://github.com/acme/app/pull/10",
            "url": "https://api.github.com/repos/acme/app/pulls/10",
            "state": "open",
        })
        mock.add_issue_comment = AsyncMock(return_value={"id": 1})
        mock._run_git = AsyncMock(return_value="")
        return mock

    @pytest.mark.asyncio
    async def test_initialize_clones_and_syncs(self, gh, identity):
        connector = RepoConnector(gh, identity, "acme", "app")
        path = await connector.initialize("/tmp/test/project")

        gh.get_repo_info.assert_called_once_with("acme", "app")
        gh.clone_repo.assert_called_once()
        assert path is not None

    @pytest.mark.asyncio
    async def test_report_to_issue(self, gh, identity):
        connector = RepoConnector(gh, identity, "acme", "app")
        await connector.report_to_issue(
            42, "pipe-123",
            {
                "pr_url": "https://github.com/acme/app/pull/10",
                "tickets_total": 5,
                "tickets_passed": 4,
                "total_cost_usd": 2.50,
                "duration": "5m",
            },
        )
        gh.add_issue_comment.assert_called_once()
        body = gh.add_issue_comment.call_args[0][3]
        assert "pipe-123" in body
        assert "4" in body  # tickets passed


@needs_test_repo
class TestRepoConnectorReal:
    """Test RepoConnector with real git operations on a public/test repo."""

    @pytest.fixture()
    def identity(self):
        return _test_identity()

    @pytest.fixture()
    def repo_parts(self):
        return _test_repo_parts()

    @pytest.mark.asyncio
    async def test_clone_and_verify(self, identity, repo_parts, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", _GITHUB_TOKEN)
        owner, repo = repo_parts
        tmp_dir = tempfile.mkdtemp(prefix="forge-integ-")

        try:
            async with GitHubClient(identity) as gh:
                connector = RepoConnector(gh, identity, owner, repo)
                repo_path = await connector.initialize(
                    os.path.join(tmp_dir, repo),
                )

            # Verify git log shows commits
            result = subprocess.run(
                ["git", "log", "--oneline", "-3"],
                capture_output=True, text=True, cwd=repo_path,
            )
            assert result.returncode == 0
            assert len(result.stdout.strip().split("\n")) > 0

            # Verify we're on a real branch
            result = subprocess.run(
                ["git", "branch", "--show-current"],
                capture_output=True, text=True, cwd=repo_path,
            )
            assert result.returncode == 0
            assert result.stdout.strip() != ""

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)

    @pytest.mark.asyncio
    async def test_create_branch_and_commit(
        self, identity, repo_parts, monkeypatch,
    ):
        monkeypatch.setenv("GITHUB_TOKEN", _GITHUB_TOKEN)
        owner, repo = repo_parts
        tmp_dir = tempfile.mkdtemp(prefix="forge-integ-")
        branch_name = f"forge-integ-{uuid.uuid4().hex[:8]}"

        try:
            async with GitHubClient(identity) as gh:
                connector = RepoConnector(gh, identity, owner, repo)
                repo_path = await connector.initialize(
                    os.path.join(tmp_dir, repo),
                )

            # Create a local branch, add a file, commit
            mgr = GitIdentityManager()
            try:
                ident = mgr.resolve_identity(_TEST_REPO_URL or "")
            except ValueError:
                ident = identity
            git_env = {**os.environ, **mgr.get_git_env(ident)}

            subprocess.run(
                ["git", "checkout", "-b", branch_name],
                cwd=repo_path, env=git_env, check=True,
                capture_output=True,
            )

            test_file = os.path.join(repo_path, f"test-{branch_name}.txt")
            with open(test_file, "w") as f:
                f.write("Integration test file\n")

            subprocess.run(
                ["git", "add", "."],
                cwd=repo_path, env=git_env, check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "-m", "test: integration test commit"],
                cwd=repo_path, env=git_env, check=True,
                capture_output=True,
            )

            # Verify branch exists locally
            result = subprocess.run(
                ["git", "branch", "--list", branch_name],
                capture_output=True, text=True, cwd=repo_path,
            )
            assert branch_name in result.stdout

        finally:
            shutil.rmtree(tmp_dir, ignore_errors=True)


# ===================================================================
# SECTION 4: IssueTracker (mocked unit tests)
# ===================================================================


class TestIssueTrackerMocked:
    """Test IssueTracker with mocked GitHubClient."""

    @pytest.fixture()
    def gh(self):
        return AsyncMock(spec=GitHubClient)

    @pytest.mark.asyncio
    async def test_get_issue_as_spec(self, gh):
        gh._api = AsyncMock(
            side_effect=[
                # First call: get issue
                {
                    "number": 10,
                    "title": "Add user auth",
                    "body": "We need OAuth support for SSO.",
                    "labels": [
                        {"name": "feature"},
                        {"name": "high"},
                    ],
                    "user": {"login": "pm-user"},
                    "created_at": "2025-01-15T10:00:00Z",
                    "html_url": "https://github.com/acme/app/issues/10",
                },
                # Second call: get comments
                [
                    {
                        "user": {"login": "pm-user"},
                        "body": "Should support Google and GitHub providers.",
                        "created_at": "2025-01-15T11:00:00Z",
                    },
                    {
                        "user": {"login": "github-actions[bot]", "type": "Bot"},
                        "body": "CI status: passing",
                        "created_at": "2025-01-15T11:30:00Z",
                    },
                ],
            ],
        )

        tracker = IssueTracker(gh, "acme", "app")
        spec = await tracker.get_issue_as_spec(10)

        # Should contain issue title and body
        assert "Add user auth" in spec
        assert "OAuth" in spec
        # Should contain non-bot comment
        assert "Google and GitHub providers" in spec
        # Should NOT contain bot comment
        assert "CI status" not in spec

    @pytest.mark.asyncio
    async def test_get_issues_for_pipeline(self, gh):
        # list_issues returns normalized format (labels as strings)
        gh.list_issues = AsyncMock(return_value=[
            {
                "number": 1, "title": "Low priority fix", "state": "open",
                "html_url": "https://github.com/acme/app/issues/1",
                "labels": ["low"], "assignees": [],
                "created_at": "2025-01-01T00:00:00Z",
                "updated_at": "2025-01-01T00:00:00Z",
            },
            {
                "number": 2, "title": "Critical bug", "state": "open",
                "html_url": "https://github.com/acme/app/issues/2",
                "labels": ["critical", "bug"], "assignees": [],
                "created_at": "2025-01-02T00:00:00Z",
                "updated_at": "2025-01-02T00:00:00Z",
            },
            {
                "number": 3, "title": "Medium feature", "state": "open",
                "html_url": "https://github.com/acme/app/issues/3",
                "labels": ["medium", "feature"], "assignees": [],
                "created_at": "2025-01-03T00:00:00Z",
                "updated_at": "2025-01-03T00:00:00Z",
            },
        ])
        # _get_issue_body calls gh._api for each issue's full body
        gh._api = AsyncMock(side_effect=[
            {"body": "Minor tweak"},
            {"body": "App crashes"},
            {"body": "Add logging"},
        ])

        tracker = IssueTracker(gh, "acme", "app")
        issues = await tracker.get_issues_for_pipeline(labels=["forge"])

        # Should be sorted by priority weight descending
        assert issues[0]["number"] == 2  # critical = 40
        assert issues[1]["number"] == 3  # medium = 20
        assert issues[2]["number"] == 1  # low = 10

    @pytest.mark.asyncio
    async def test_update_issue_status(self, gh):
        gh.add_issue_comment = AsyncMock(return_value={"id": 100})

        tracker = IssueTracker(gh, "acme", "app")
        await tracker.update_issue_status(42, "Pipeline started", "Running analysis")

        gh.add_issue_comment.assert_called_once()
        call_args = gh.add_issue_comment.call_args
        body = call_args[0][3]
        assert "Pipeline started" in body
        assert "Running analysis" in body

    @pytest.mark.asyncio
    async def test_create_sub_issues(self, gh):
        gh.create_issue = AsyncMock(
            side_effect=[
                {"number": 101},
                {"number": 102},
            ],
        )
        gh.add_issue_comment = AsyncMock(return_value={"id": 1})

        tracker = IssueTracker(gh, "acme", "app")
        tickets = [
            {
                "key": "TASK-1",
                "title": "Implement login",
                "description": "Add login page",
                "priority": "high",
                "story_points": 5,
                "acceptance_criteria": ["Login form renders"],
                "dependencies": [],
            },
            {
                "key": "TASK-2",
                "title": "Add tests",
                "description": "Unit tests for login",
                "priority": "medium",
                "story_points": 3,
                "acceptance_criteria": ["Tests pass"],
                "dependencies": ["TASK-1"],
            },
        ]
        numbers = await tracker.create_sub_issues(10, tickets)

        assert numbers == [101, 102]
        assert gh.create_issue.call_count == 2


@integration
class TestIssueTrackerReal:
    """Test IssueTracker against real GitHub API (read-only)."""

    @pytest.fixture()
    def identity(self):
        return _test_identity()

    @pytest.mark.asyncio
    async def test_fetch_issues_public_repo(self, identity, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN", _GITHUB_TOKEN)
        async with GitHubClient(identity) as gh:
            tracker = IssueTracker(gh, "octocat", "Hello-World")
            issues = await tracker.get_issues_for_pipeline(limit=3)
        # May or may not have forge-labeled issues; just verify it returns a list
        assert isinstance(issues, list)


# ===================================================================
# SECTION 5: End-to-end mocked flow
# ===================================================================


class TestEndToEndMocked:
    """Test a full issue-to-PR flow with all components mocked."""

    @pytest.mark.asyncio
    async def test_issue_to_pipeline_flow(self):
        """Simulate: fetch issue -> format spec -> create sub-issues."""
        identity = GitIdentity(
            name="e2e",
            github_username="forge-bot",
            email="bot@forge.dev",
            ssh_key_path="~/.ssh/id_e2e",
            ssh_host_alias="github-e2e",
        )

        gh = AsyncMock(spec=GitHubClient)
        gh._api = AsyncMock(
            side_effect=[
                # get_issue_as_spec: issue fetch
                {
                    "number": 42,
                    "title": "Build notification system",
                    "body": (
                        "We need email and Slack notifications "
                        "when pipeline events occur."
                    ),
                    "labels": [{"name": "feature"}, {"name": "forge"}],
                    "user": {"login": "product-manager"},
                    "created_at": "2025-06-01T10:00:00Z",
                    "html_url": "https://github.com/acme/app/issues/42",
                },
                # get_issue_as_spec: comments
                [],
            ],
        )

        # Phase 1: Issue → spec
        tracker = IssueTracker(gh, "acme", "app")
        spec = await tracker.get_issue_as_spec(42)
        assert "notification" in spec.lower()
        assert "#42" in spec

        # Phase 2: update_issue_status
        gh.add_issue_comment = AsyncMock(return_value={"id": 500})
        await tracker.update_issue_status(42, "Pipeline started")
        gh.add_issue_comment.assert_called_once()

        # Phase 3: create_sub_issues
        gh.create_issue = AsyncMock(
            side_effect=[{"number": 100}, {"number": 101}],
        )
        tickets = [
            {
                "key": "NOTIF-1",
                "title": "Email notifications",
                "description": "Send emails on pipeline events",
                "priority": "high",
                "story_points": 5,
                "acceptance_criteria": ["Emails sent on success/failure"],
                "dependencies": [],
            },
            {
                "key": "NOTIF-2",
                "title": "Slack notifications",
                "description": "Post to Slack channel",
                "priority": "medium",
                "story_points": 3,
                "acceptance_criteria": ["Slack message posted"],
                "dependencies": ["NOTIF-1"],
            },
        ]
        sub_issues = await tracker.create_sub_issues(42, tickets)
        assert sub_issues == [100, 101]

        # Phase 4: RepoConnector.report_to_issue
        connector = RepoConnector(gh, identity, "acme", "app")
        await connector.report_to_issue(
            42, "pipe-e2e-001",
            {
                "pr_url": "https://github.com/acme/app/pull/77",
                "tickets_total": 2,
                "tickets_passed": 2,
                "total_cost_usd": 1.50,
                "duration": "3m",
            },
        )
        # add_issue_comment called 3 times: status + sub-issue checklist + report
        assert gh.add_issue_comment.call_count == 3


# ===================================================================
# SECTION 6: Helper / utility coverage
# ===================================================================


class TestHelperFunctions:
    """Test pure helper functions from across the integration modules."""

    def test_parse_github_url_variants(self):
        cases = [
            ("git@github.com:Org/Repo.git", ("Org", "Repo")),
            ("git@github-custom:Org/Repo.git", ("Org", "Repo")),
            ("https://github.com/Org/Repo.git", ("Org", "Repo")),
            ("https://github.com/Org/Repo", ("Org", "Repo")),
            ("https://github.com/Org/Repo/", ("Org", "Repo")),
            ("git@github.com:user/my-repo", ("user", "my-repo")),
            ("git@github.com:user/my.repo.git", ("user", "my.repo")),
            ("not-a-url", None),
            ("ftp://example.com/repo", None),
        ]
        for url, expected in cases:
            assert parse_github_url(url) == expected, f"Failed for {url}"

    def test_identity_to_dict_round_trip(self):
        ident = GitIdentity(
            name="rt",
            github_username="usr",
            email="usr@co.com",
            ssh_key_path="~/.ssh/id_rt",
            ssh_host_alias="github-rt",
            github_org="MyOrg",
            default=True,
            extra_orgs=["SubOrg"],
        )
        d = ident.to_dict()
        assert d["name"] == "rt"
        assert d["github_org"] == "MyOrg"
        assert d["default"] is True
        assert d["extra_orgs"] == ["SubOrg"]

    def test_identity_to_dict_omits_none(self):
        ident = GitIdentity(
            name="simple",
            github_username="usr",
            email="usr@co.com",
            ssh_key_path="~/.ssh/id",
            ssh_host_alias="github",
        )
        d = ident.to_dict()
        assert "github_org" not in d
        assert "default" not in d or d.get("default") is not True

    def test_repo_connector_build_pr_context(self):
        from integrations.repo_connector import _build_pr_context

        artifacts = [
            {
                "ticket_key": "T-1",
                "git_branch": "feat/t1",
                "files_created": ["a.py"],
                "files_modified": ["b.py"],
                "test_results": {"total": 3, "passed": 3, "failed": 0},
                "qa_review": {"verdict": "approved"},
                "notes": "Done",
            },
            {
                "ticket_key": "T-2",
                "git_branch": "feat/t2",
                "files_created": ["c.py", "d.py"],
                "files_modified": [],
                "test_results": {"total": 3, "passed": 2, "failed": 1},
                "qa_review": {"verdict": "needs_revision"},
                "notes": "",
            },
        ]
        ctx = _build_pr_context(artifacts)
        assert len(ctx["tickets"]) == 2
        assert len(ctx["files_created"]) == 3  # 1 + 2
        assert len(ctx["files_modified"]) == 1
        assert ctx["total_tests"] == 6  # 3+3
        assert ctx["passed_tests"] == 5
        assert ctx["failed_tests"] == 1
        assert ctx["qa_passed"] == 1
        assert ctx["qa_total"] == 2

    def test_repo_connector_format_pr_body(self):
        from integrations.repo_connector import _format_pr_body

        ctx = {
            "project_name": "widgets",
            "tickets": ["T-1", "T-2"],
            "files_created": ["a.py", "b.py", "c.py", "d.py", "e.py"],
            "files_modified": ["x.py", "y.py"],
            "total_tests": 10,
            "passed_tests": 9,
            "failed_tests": 1,
            "qa_passed": 2,
            "qa_total": 2,
        }
        body = _format_pr_body("pipe-001", ctx)
        assert "pipe-001" in body
        assert "T-1" in body
        assert "T-2" in body
        assert "5" in body  # files created
