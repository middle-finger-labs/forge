"""Tests for integrations.repo_connector."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from integrations.git_identity import GitIdentity
from integrations.github_client import GitHubClient, GitOperationError
from integrations.repo_connector import (
    RepoConnector,
    _build_pr_context,
    _format_pr_body,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_IDENTITY = GitIdentity(
    name="test-org",
    github_username="bot-user",
    email="bot@test.com",
    ssh_key_path="~/.ssh/id_test",
    ssh_host_alias="github-test",
    github_org="TestOrg",
)


@pytest.fixture(autouse=True)
def _set_token(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN_TEST_ORG", "ghp_fake123")


@pytest.fixture
def gh_client():
    """A GitHubClient with all async methods mocked."""
    client = GitHubClient(_IDENTITY, auth_method="pat")
    client.clone_repo = AsyncMock(return_value="/tmp/repo")
    client.push_branch = AsyncMock()
    client.create_pr = AsyncMock(return_value={
        "number": 1,
        "url": "https://api.github.com/repos/O/R/pulls/1",
        "html_url": "https://github.com/O/R/pull/1",
        "state": "open",
        "draft": True,
        "head": "forge/pipe-001",
        "base": "main",
    })
    client.update_pr = AsyncMock(return_value={
        "number": 1, "url": "u", "html_url": "h", "state": "open",
    })
    client.get_repo_info = AsyncMock(return_value={
        "full_name": "TestOrg/my-repo",
        "default_branch": "main",
        "language": "Python",
        "visibility": "private",
        "description": "test",
        "clone_url": "https://github.com/TestOrg/my-repo.git",
        "ssh_url": "git@github.com:TestOrg/my-repo.git",
        "archived": False,
        "fork": False,
    })
    client.add_issue_comment = AsyncMock(return_value={
        "id": 99, "url": "u", "html_url": "h", "body": "comment",
    })
    client._run_git = AsyncMock(return_value="")
    client._api = AsyncMock(return_value={})
    return client


@pytest.fixture
def connector(gh_client):
    return RepoConnector(gh_client, _IDENTITY, "TestOrg", "my-repo")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_ARTIFACTS = [
    {
        "ticket_key": "FORGE-1",
        "git_branch": "forge/forge-1",
        "files_created": ["src/auth/router.ts", "src/auth/service.ts"],
        "files_modified": ["src/index.ts"],
        "test_results": {
            "total": 4,
            "passed": 3,
            "failed": 1,
            "skipped": 0,
            "duration_seconds": 1.2,
        },
        "lint_passed": True,
        "notes": "Added auth endpoints",
    },
    {
        "ticket_key": "FORGE-2",
        "git_branch": "forge/forge-2",
        "files_created": ["src/users/model.ts"],
        "files_modified": [],
        "test_results": {
            "total": 2,
            "passed": 2,
            "failed": 0,
            "skipped": 0,
        },
        "qa_review": {"verdict": "approved"},
        "lint_passed": True,
        "notes": "",
    },
]


# ---------------------------------------------------------------------------
# initialize
# ---------------------------------------------------------------------------


class TestInitialize:
    @pytest.mark.asyncio
    async def test_clones_and_configures(self, connector, gh_client):
        path = await connector.initialize("/tmp/repo")

        assert path == "/tmp/repo"
        gh_client.get_repo_info.assert_called_once_with(
            "TestOrg", "my-repo",
        )
        gh_client.clone_repo.assert_called_once_with(
            "git@github.com:TestOrg/my-repo.git",
            "/tmp/repo",
            branch="main",
        )

        # Should have configured user.name and user.email
        git_calls = gh_client._run_git.call_args_list
        config_calls = [
            c for c in git_calls if c[0][0] == "config"
        ]
        assert len(config_calls) == 2
        assert config_calls[0][0][2] == "bot-user"
        assert config_calls[1][0][2] == "bot@test.com"

    @pytest.mark.asyncio
    async def test_uses_discovered_default_branch(
        self, connector, gh_client,
    ):
        gh_client.get_repo_info.return_value["default_branch"] = "develop"
        gh_client._run_git.return_value = "develop"

        await connector.initialize("/tmp/repo")

        gh_client.clone_repo.assert_called_once_with(
            "git@github.com:TestOrg/my-repo.git",
            "/tmp/repo",
            branch="develop",
        )
        assert connector._default_branch == "develop"

    @pytest.mark.asyncio
    async def test_verifies_head_branch(self, connector, gh_client):
        """HEAD check runs after clone; warning logged if mismatch."""
        # The third _run_git call is symbolic-ref
        gh_client._run_git.side_effect = [
            "",       # config user.name
            "",       # config user.email
            "main",   # symbolic-ref --short HEAD
        ]
        path = await connector.initialize("/tmp/repo")
        assert path == "/tmp/repo"


# ---------------------------------------------------------------------------
# sync_from_remote
# ---------------------------------------------------------------------------


class TestSyncFromRemote:
    @pytest.mark.asyncio
    async def test_fetch_and_pull(self, connector, gh_client):
        gh_client._run_git.side_effect = [
            "",       # fetch origin
            "main",   # symbolic-ref --short HEAD
            "",       # pull --rebase
        ]
        await connector.sync_from_remote("/tmp/repo")

        calls = gh_client._run_git.call_args_list
        assert calls[0][0][0] == "fetch"
        assert calls[1][0] == ("symbolic-ref", "--short", "HEAD")
        assert calls[2][0][:2] == ("pull", "--rebase")

    @pytest.mark.asyncio
    async def test_rebase_failure_falls_back_to_merge(
        self, connector, gh_client,
    ):
        gh_client._run_git.side_effect = [
            "",                                          # fetch
            "main",                                      # symbolic-ref
            GitOperationError("conflict", returncode=1), # pull --rebase
            "",                                          # rebase --abort
            "",                                          # pull (merge)
        ]
        await connector.sync_from_remote("/tmp/repo")

        calls = gh_client._run_git.call_args_list
        assert calls[3][0] == ("rebase", "--abort")
        assert calls[4][0][:2] == ("pull", "origin")

    @pytest.mark.asyncio
    async def test_rebase_abort_failure_ignored(
        self, connector, gh_client,
    ):
        """If rebase --abort also fails, we still try merge pull."""
        gh_client._run_git.side_effect = [
            "",                                          # fetch
            "main",                                      # symbolic-ref
            GitOperationError("conflict", returncode=1), # pull --rebase
            GitOperationError("no rebase", returncode=1),# rebase --abort
            "",                                          # pull (merge)
        ]
        await connector.sync_from_remote("/tmp/repo")
        assert gh_client._run_git.call_count == 5


# ---------------------------------------------------------------------------
# push_pipeline_results
# ---------------------------------------------------------------------------


class TestPushPipelineResults:
    @pytest.mark.asyncio
    async def test_single_pr_strategy(self, connector, gh_client):
        gh_client._run_git.return_value = ""

        result = await connector.push_pipeline_results(
            "/tmp/repo", "pipe-001", SAMPLE_ARTIFACTS, "single_pr",
        )
        assert len(result["prs"]) == 1
        assert result["prs"][0] == "https://github.com/O/R/pull/1"
        assert result["branches"] == ["forge/pipe-001"]

        # Verify branch was created and pushed
        git_calls = gh_client._run_git.call_args_list
        checkout_call = git_calls[0]
        assert checkout_call[0] == ("checkout", "-b", "forge/pipe-001")
        gh_client.push_branch.assert_called_once()

    @pytest.mark.asyncio
    async def test_direct_push_strategy(self, connector, gh_client):
        gh_client._run_git.return_value = "main"

        result = await connector.push_pipeline_results(
            "/tmp/repo", "pipe-001", SAMPLE_ARTIFACTS, "direct_push",
        )
        assert result["prs"] == []
        assert result["branches"] == ["main"]
        gh_client.push_branch.assert_called_once_with("/tmp/repo", "main")

    @pytest.mark.asyncio
    async def test_pr_per_ticket_strategy(self, connector, gh_client):
        # _branch_exists returns False (rev-parse fails), then create
        gh_client._run_git.side_effect = [
            # ticket 1: rev-parse fails → doesn't exist
            GitOperationError("not found", returncode=128),
            # ticket 1: checkout -b (from _create_ticket_branch checkout fails)
            GitOperationError("no branch", returncode=1),
            # ticket 1: checkout -b from default
            "",
            # ticket 2: rev-parse fails
            GitOperationError("not found", returncode=128),
            # ticket 2: checkout fails
            GitOperationError("no branch", returncode=1),
            # ticket 2: checkout -b from default
            "",
        ]

        result = await connector.push_pipeline_results(
            "/tmp/repo", "pipe-001", SAMPLE_ARTIFACTS, "pr_per_ticket",
        )
        assert len(result["prs"]) == 2
        assert len(result["branches"]) == 2
        assert gh_client.push_branch.call_count == 2

    @pytest.mark.asyncio
    async def test_unknown_strategy_raises(self, connector):
        with pytest.raises(ValueError, match="Unknown push strategy"):
            await connector.push_pipeline_results(
                "/tmp/repo", "pipe-001", [], "yolo",
            )


# ---------------------------------------------------------------------------
# create_pipeline_pr
# ---------------------------------------------------------------------------


class TestCreatePipelinePr:
    @pytest.mark.asyncio
    async def test_creates_draft_pr(self, connector, gh_client):
        ctx = _build_pr_context(SAMPLE_ARTIFACTS)
        url = await connector.create_pipeline_pr(
            "/tmp/repo", "forge/pipe-001", "pipe-001", ctx,
        )
        assert url == "https://github.com/O/R/pull/1"

        call_kwargs = gh_client.create_pr.call_args
        assert call_kwargs[1]["draft"] is True
        assert "pipe-001" in call_kwargs[0][2]  # title

    @pytest.mark.asyncio
    async def test_pr_title_format(self, connector, gh_client):
        ctx = _build_pr_context(SAMPLE_ARTIFACTS)
        ctx["project_name"] = "MyProject"
        await connector.create_pipeline_pr(
            "/tmp/repo", "forge/pipe-001", "pipe-001", ctx,
        )
        title = gh_client.create_pr.call_args[0][2]
        assert title.startswith("feat: MyProject")
        assert "pipe-001" in title

    @pytest.mark.asyncio
    async def test_labels_attached(self, connector, gh_client):
        ctx = _build_pr_context([])
        await connector.create_pipeline_pr(
            "/tmp/repo", "br", "p1", ctx,
        )
        # _api called for label attachment
        label_call = gh_client._api.call_args
        assert "labels" in label_call[0][1]
        assert label_call[1]["json"]["labels"] == [
            "forge-generated", "ai-code",
        ]

    @pytest.mark.asyncio
    async def test_label_failure_does_not_raise(
        self, connector, gh_client,
    ):
        gh_client._api.side_effect = Exception("label not found")
        ctx = _build_pr_context([])
        # Should not raise
        url = await connector.create_pipeline_pr(
            "/tmp/repo", "br", "p1", ctx,
        )
        assert url == "https://github.com/O/R/pull/1"


# ---------------------------------------------------------------------------
# link_issues
# ---------------------------------------------------------------------------


class TestLinkIssues:
    @pytest.mark.asyncio
    async def test_appends_closes_refs(self, connector, gh_client):
        gh_client._api.return_value = {
            "body": "Original PR body",
        }
        await connector.link_issues(1, [10, 20])

        gh_client.update_pr.assert_called_once()
        new_body = gh_client.update_pr.call_args[1]["body"]
        assert "Closes #10" in new_body
        assert "Closes #20" in new_body
        assert "Original PR body" in new_body

    @pytest.mark.asyncio
    async def test_empty_issues_is_noop(self, connector, gh_client):
        await connector.link_issues(1, [])
        gh_client._api.assert_not_called()
        gh_client.update_pr.assert_not_called()

    @pytest.mark.asyncio
    async def test_handles_none_body(self, connector, gh_client):
        gh_client._api.return_value = {"body": None}
        await connector.link_issues(1, [5])
        new_body = gh_client.update_pr.call_args[1]["body"]
        assert "Closes #5" in new_body


# ---------------------------------------------------------------------------
# report_to_issue
# ---------------------------------------------------------------------------


class TestReportToIssue:
    @pytest.mark.asyncio
    async def test_posts_comment(self, connector, gh_client):
        result = {
            "pr_url": "https://github.com/O/R/pull/1",
            "tickets_total": 5,
            "tickets_passed": 4,
            "total_cost_usd": 1.23,
            "duration": "12m 30s",
        }
        await connector.report_to_issue(42, "pipe-001", result)

        gh_client.add_issue_comment.assert_called_once()
        args = gh_client.add_issue_comment.call_args[0]
        assert args[0] == "TestOrg"
        assert args[1] == "my-repo"
        assert args[2] == 42

        body = args[3]
        assert "pipe-001" in body
        assert "4/5 passed QA" in body
        assert "$1.23" in body
        assert "12m 30s" in body
        assert "https://github.com/O/R/pull/1" in body

    @pytest.mark.asyncio
    async def test_includes_errors_section(self, connector, gh_client):
        result = {
            "pr_url": "N/A",
            "tickets_total": 1,
            "tickets_passed": 0,
            "total_cost_usd": 0.50,
            "duration": "5m",
            "errors": ["LLM timeout in stage 5", "Git conflict in FORGE-3"],
        }
        await connector.report_to_issue(10, "pipe-002", result)

        body = gh_client.add_issue_comment.call_args[0][3]
        assert "### Errors" in body
        assert "LLM timeout in stage 5" in body
        assert "Git conflict in FORGE-3" in body

    @pytest.mark.asyncio
    async def test_handles_missing_fields(self, connector, gh_client):
        """Missing keys should use defaults, not crash."""
        await connector.report_to_issue(1, "pipe-003", {})
        body = gh_client.add_issue_comment.call_args[0][3]
        assert "pipe-003" in body
        assert "0/0 passed QA" in body
        assert "$0.00" in body


# ---------------------------------------------------------------------------
# _build_pr_context
# ---------------------------------------------------------------------------


class TestBuildPrContext:
    def test_aggregates_tickets(self):
        ctx = _build_pr_context(SAMPLE_ARTIFACTS)
        assert ctx["tickets"] == ["FORGE-1", "FORGE-2"]

    def test_aggregates_files(self):
        ctx = _build_pr_context(SAMPLE_ARTIFACTS)
        assert "src/auth/router.ts" in ctx["files_created"]
        assert "src/users/model.ts" in ctx["files_created"]
        assert "src/index.ts" in ctx["files_modified"]

    def test_aggregates_tests(self):
        ctx = _build_pr_context(SAMPLE_ARTIFACTS)
        assert ctx["total_tests"] == 6
        assert ctx["passed_tests"] == 5
        assert ctx["failed_tests"] == 1

    def test_counts_qa_approvals(self):
        ctx = _build_pr_context(SAMPLE_ARTIFACTS)
        assert ctx["qa_passed"] == 1
        assert ctx["qa_total"] == 1

    def test_empty_artifacts(self):
        ctx = _build_pr_context([])
        assert ctx["tickets"] == []
        assert ctx["total_tests"] == 0


# ---------------------------------------------------------------------------
# _format_pr_body
# ---------------------------------------------------------------------------


class TestFormatPrBody:
    def test_contains_pipeline_id(self):
        ctx = _build_pr_context(SAMPLE_ARTIFACTS)
        body = _format_pr_body("pipe-001", ctx)
        assert "pipe-001" in body

    def test_contains_ticket_list(self):
        ctx = _build_pr_context(SAMPLE_ARTIFACTS)
        body = _format_pr_body("p1", ctx)
        assert "FORGE-1" in body
        assert "FORGE-2" in body

    def test_contains_test_results(self):
        ctx = _build_pr_context(SAMPLE_ARTIFACTS)
        body = _format_pr_body("p1", ctx)
        assert "5/6 passed" in body
        assert "1 failed" in body

    def test_contains_qa_section(self):
        ctx = _build_pr_context(SAMPLE_ARTIFACTS)
        body = _format_pr_body("p1", ctx)
        assert "1/1 tickets approved" in body

    def test_file_lists_collapsed(self):
        ctx = _build_pr_context(SAMPLE_ARTIFACTS)
        body = _format_pr_body("p1", ctx)
        assert "<details>" in body
        assert "Files created" in body

    def test_no_tests_section_when_zero(self):
        ctx = _build_pr_context([])
        body = _format_pr_body("p1", ctx)
        assert "Test Results" not in body

    def test_no_qa_section_when_zero(self):
        ctx = _build_pr_context([{"ticket_key": "T-1"}])
        body = _format_pr_body("p1", ctx)
        assert "QA Review" not in body

    def test_footer_present(self):
        body = _format_pr_body("p1", _build_pr_context([]))
        assert "Forge" in body
        assert "Review carefully" in body


# ---------------------------------------------------------------------------
# _branch_exists (internal)
# ---------------------------------------------------------------------------


class TestBranchExists:
    @pytest.mark.asyncio
    async def test_returns_true_when_exists(self, connector, gh_client):
        gh_client._run_git.return_value = "abc123"
        result = await connector._branch_exists("/tmp/repo", "main")
        assert result is True

    @pytest.mark.asyncio
    async def test_returns_false_when_missing(self, connector, gh_client):
        gh_client._run_git.side_effect = GitOperationError(
            "not a valid ref", returncode=128,
        )
        result = await connector._branch_exists(
            "/tmp/repo", "nonexistent",
        )
        assert result is False
