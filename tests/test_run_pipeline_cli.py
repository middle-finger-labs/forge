"""Tests for run_pipeline.py CLI — new commands (identities, repos, repo-based start)."""

from __future__ import annotations

import argparse
import os
import subprocess
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from run_pipeline import (
    _append_ssh_config,
    _fetch_issue_spec,
    build_parser,
    cmd_identities_list,
    cmd_identities_test,
    cmd_start,
)

# ---------------------------------------------------------------------------
# Parser tests
# ---------------------------------------------------------------------------


class TestParser:
    """Verify argparse structure for new commands."""

    def _parse(self, *argv: str) -> argparse.Namespace:
        parser = build_parser()
        return parser.parse_args(list(argv))

    def test_start_with_spec(self):
        args = self._parse("start", "--spec", "Build an app")
        assert args.command == "start"
        assert args.spec == "Build an app"
        assert args.repo is None
        assert args.issue is None

    def test_start_with_repo_and_spec(self):
        args = self._parse(
            "start", "--repo", "git@github.com:acme/app.git", "--spec", "Add auth",
        )
        assert args.repo == "git@github.com:acme/app.git"
        assert args.spec == "Add auth"

    def test_start_with_repo_and_issue(self):
        args = self._parse(
            "start", "--repo", "git@github.com:acme/app.git", "--issue", "42",
        )
        assert args.repo == "git@github.com:acme/app.git"
        assert args.issue == 42

    def test_start_with_identity(self):
        args = self._parse(
            "start", "--repo", "git@github.com:acme/app.git",
            "--spec", "x", "--identity", "draftkings",
        )
        assert args.identity == "draftkings"

    def test_start_with_pr_strategy(self):
        args = self._parse(
            "start", "--spec", "x", "--pr-strategy", "pr_per_ticket",
        )
        assert args.pr_strategy == "pr_per_ticket"

    def test_start_pr_strategy_default(self):
        args = self._parse("start", "--spec", "x")
        assert args.pr_strategy == "single_pr"

    def test_start_pr_strategy_invalid(self):
        with pytest.raises(SystemExit):
            self._parse("start", "--spec", "x", "--pr-strategy", "yolo")

    def test_identities_list(self):
        args = self._parse("identities", "list")
        assert args.command == "identities"
        assert args.identities_command == "list"

    def test_identities_test(self):
        args = self._parse("identities", "test", "personal")
        assert args.identities_command == "test"
        assert args.identity_name == "personal"

    def test_identities_add(self):
        args = self._parse("identities", "add")
        assert args.identities_command == "add"

    def test_repos_test(self):
        args = self._parse("repos", "test", "git@github.com:acme/app.git")
        assert args.command == "repos"
        assert args.repos_command == "test"
        assert args.repo_url == "git@github.com:acme/app.git"

    def test_repos_test_with_identity(self):
        args = self._parse(
            "repos", "test", "git@github.com:acme/app.git", "--identity", "work",
        )
        assert args.identity == "work"


# ---------------------------------------------------------------------------
# Identities list
# ---------------------------------------------------------------------------


class TestIdentitiesList:
    """Tests for cmd_identities_list."""

    @patch("integrations.git_identity.GitIdentityManager")
    def test_list_empty(self, mock_mgr_cls, capsys):
        mock_mgr = MagicMock()
        mock_mgr.list_identities.return_value = []
        mock_mgr_cls.return_value = mock_mgr

        cmd_identities_list(argparse.Namespace())
        out = capsys.readouterr().out
        assert "No identities" in out

    @patch("integrations.git_identity.GitIdentityManager")
    def test_list_shows_identities(self, mock_mgr_cls, capsys):
        from integrations.git_identity import GitIdentity

        ident = GitIdentity(
            name="personal",
            github_username="octocat",
            email="cat@github.com",
            ssh_key_path="~/.ssh/id_ed25519_personal",
            ssh_host_alias="github-personal",
            default=True,
        )
        mock_mgr = MagicMock()
        mock_mgr.list_identities.return_value = [ident]
        mock_mgr_cls.return_value = mock_mgr

        cmd_identities_list(argparse.Namespace())
        out = capsys.readouterr().out
        assert "personal" in out
        assert "octocat" in out


# ---------------------------------------------------------------------------
# Identities test
# ---------------------------------------------------------------------------


class TestIdentitiesTest:
    """Tests for cmd_identities_test."""

    @patch("integrations.git_identity.GitIdentityManager")
    def test_identity_not_found(self, mock_mgr_cls):
        mock_mgr = MagicMock()
        mock_mgr.get_identity.return_value = None
        mock_mgr_cls.return_value = mock_mgr

        with pytest.raises(SystemExit):
            cmd_identities_test(argparse.Namespace(identity_name="nope"))

    @patch("integrations.git_identity.GitIdentityManager")
    def test_identity_test_ok(self, mock_mgr_cls, capsys):
        from integrations.git_identity import GitIdentity

        ident = GitIdentity(
            name="work",
            github_username="dev",
            email="dev@co.com",
            ssh_key_path="~/.ssh/id_work",
            ssh_host_alias="github-work",
        )
        mock_mgr = MagicMock()
        mock_mgr.get_identity.return_value = ident
        mock_mgr.setup_identity.return_value = {
            "name": "work",
            "key_exists": True,
            "connection_ok": True,
            "github_user": "dev",
            "error": None,
        }
        mock_mgr_cls.return_value = mock_mgr

        cmd_identities_test(argparse.Namespace(identity_name="work"))
        out = capsys.readouterr().out
        assert "found" in out
        assert "OK" in out
        assert "dev" in out

    @patch("integrations.git_identity.GitIdentityManager")
    def test_identity_test_key_missing(self, mock_mgr_cls, capsys):
        from integrations.git_identity import GitIdentity

        ident = GitIdentity(
            name="missing",
            github_username="dev",
            email="dev@co.com",
            ssh_key_path="~/.ssh/id_nope",
            ssh_host_alias="github-missing",
        )
        mock_mgr = MagicMock()
        mock_mgr.get_identity.return_value = ident
        mock_mgr.setup_identity.return_value = {
            "name": "missing",
            "key_exists": False,
            "connection_ok": False,
            "github_user": None,
            "error": "SSH key not found",
        }
        mock_mgr_cls.return_value = mock_mgr

        cmd_identities_test(argparse.Namespace(identity_name="missing"))
        out = capsys.readouterr().out
        assert "NOT FOUND" in out


# ---------------------------------------------------------------------------
# cmd_start with repo + issue
# ---------------------------------------------------------------------------


class TestStartWithRepo:
    """Tests for cmd_start with --repo and --issue flags."""

    @patch("run_pipeline.Client")
    @patch("run_pipeline._fetch_issue_spec")
    def test_start_with_repo_and_issue(self, mock_fetch, mock_client_cls):
        mock_fetch.return_value = "# Issue Spec\nDo the thing"

        mock_client = MagicMock()
        mock_handle = MagicMock()
        mock_handle.result_run_id = "run-123"
        mock_client.start_workflow = AsyncMock(return_value=mock_handle)
        mock_client_cls.connect = AsyncMock(return_value=mock_client)

        import asyncio

        args = argparse.Namespace(
            spec=None,
            spec_file=None,
            repo="git@github.com:acme/app.git",
            issue=42,
            identity=None,
            pr_strategy="single_pr",
            id=None,
            name=None,
        )
        asyncio.run(cmd_start(args))

        # Verify start_workflow was called with correct PipelineInput
        call_args = mock_client.start_workflow.call_args
        pipeline_input = call_args[0][1]
        assert pipeline_input.repo_url == "git@github.com:acme/app.git"
        assert pipeline_input.repo_owner == "acme"
        assert pipeline_input.repo_name == "app"
        assert pipeline_input.issue_number == 42
        assert "Issue Spec" in pipeline_input.business_spec

    @patch("run_pipeline.Client")
    def test_start_with_repo_and_spec(self, mock_client_cls):
        mock_client = MagicMock()
        mock_handle = MagicMock()
        mock_handle.result_run_id = "run-456"
        mock_client.start_workflow = AsyncMock(return_value=mock_handle)
        mock_client_cls.connect = AsyncMock(return_value=mock_client)

        import asyncio

        args = argparse.Namespace(
            spec="Add OAuth support",
            spec_file=None,
            repo="git@github.com:acme/app.git",
            issue=None,
            identity="draftkings",
            pr_strategy="pr_per_ticket",
            id="test123",
            name="MyApp",
        )
        asyncio.run(cmd_start(args))

        call_args = mock_client.start_workflow.call_args
        pipeline_input = call_args[0][1]
        assert pipeline_input.business_spec == "Add OAuth support"
        assert pipeline_input.git_identity_name == "draftkings"
        assert pipeline_input.pr_strategy == "pr_per_ticket"
        assert pipeline_input.pipeline_id == "test123"

    @patch("run_pipeline.Client")
    def test_start_no_spec_no_issue_no_repo(self, mock_client_cls):
        """Should fail if no spec source is provided."""
        import asyncio

        args = argparse.Namespace(
            spec=None,
            spec_file=None,
            repo=None,
            issue=None,
            identity=None,
            pr_strategy="single_pr",
            id=None,
            name=None,
        )
        with pytest.raises(SystemExit):
            asyncio.run(cmd_start(args))


# ---------------------------------------------------------------------------
# _fetch_issue_spec
# ---------------------------------------------------------------------------


class TestFetchIssueSpec:
    """Tests for the _fetch_issue_spec helper."""

    @patch("integrations.issue_tracker.IssueTracker")
    @patch("integrations.github_client.GitHubClient")
    @patch("integrations.git_identity.GitIdentityManager")
    def test_fetches_issue(self, mock_mgr_cls, mock_gh_cls, mock_tracker_cls):
        import asyncio

        from integrations.git_identity import GitIdentity

        identity = GitIdentity(
            name="test",
            github_username="dev",
            email="dev@test.com",
            ssh_key_path="~/.ssh/id_test",
            ssh_host_alias="github-test",
        )
        mock_mgr = MagicMock()
        mock_mgr.resolve_identity.return_value = identity
        mock_mgr_cls.return_value = mock_mgr

        mock_gh = AsyncMock()
        mock_gh.__aenter__ = AsyncMock(return_value=mock_gh)
        mock_gh.__aexit__ = AsyncMock(return_value=None)
        mock_gh_cls.return_value = mock_gh

        mock_tracker = MagicMock()
        mock_tracker.get_issue_as_spec = AsyncMock(return_value="# My Issue\nDetails here")
        mock_tracker_cls.return_value = mock_tracker

        result = asyncio.run(
            _fetch_issue_spec("git@github.com:acme/app.git", 42, None),
        )
        assert "My Issue" in result
        mock_tracker.get_issue_as_spec.assert_called_once_with(42)

    def test_bad_url_exits(self):
        import asyncio

        with pytest.raises(SystemExit):
            asyncio.run(_fetch_issue_spec("not-a-url", 1, None))


# ---------------------------------------------------------------------------
# _append_ssh_config
# ---------------------------------------------------------------------------


class TestAppendSshConfig:
    """Tests for the SSH config append helper."""

    def test_appends_block(self, tmp_path):
        config_file = tmp_path / "ssh_config"
        config_file.write_text("# existing\n")

        block = "Host github-test\n    HostName github.com\n    User git"

        with patch("run_pipeline.os.path.expanduser", return_value=str(config_file)):
            with patch("run_pipeline.os.path.isfile", return_value=True):
                # We need to patch open to use our temp file
                import builtins
                original_open = builtins.open

                def patched_open(path, *a, **kw):
                    if "/.ssh/config" in str(path):
                        return original_open(str(config_file), *a, **kw)
                    return original_open(path, *a, **kw)

                with patch("builtins.open", side_effect=patched_open):
                    _append_ssh_config(block)

        content = config_file.read_text()
        assert "Host github-test" in content

    def test_skips_if_already_present(self, tmp_path, capsys):
        config_file = tmp_path / "ssh_config"
        config_file.write_text("Host github-test\n    HostName github.com\n")

        block = "Host github-test\n    HostName github.com\n    User git"

        import builtins
        original_open = builtins.open

        def patched_open(path, *a, **kw):
            if "/.ssh/config" in str(path):
                return original_open(str(config_file), *a, **kw)
            return original_open(path, *a, **kw)

        with patch("run_pipeline.os.path.expanduser", return_value=str(config_file)):
            with patch("run_pipeline.os.path.isfile", return_value=True):
                with patch("builtins.open", side_effect=patched_open):
                    _append_ssh_config(block)

        out = capsys.readouterr().out
        assert "already present" in out


# ---------------------------------------------------------------------------
# Setup script exists and is executable
# ---------------------------------------------------------------------------


class TestSetupScript:
    """Verify the setup_github.sh script exists and has correct structure."""

    def test_script_exists(self):
        script = os.path.join(os.path.dirname(__file__), "..", "scripts", "setup_github.sh")
        assert os.path.isfile(script)

    def test_script_is_executable(self):
        script = os.path.join(os.path.dirname(__file__), "..", "scripts", "setup_github.sh")
        assert os.access(script, os.X_OK)

    def test_script_has_shebang(self):
        script = os.path.join(os.path.dirname(__file__), "..", "scripts", "setup_github.sh")
        with open(script) as f:
            first_line = f.readline()
        assert first_line.startswith("#!/")

    def test_script_passes_shellcheck(self):
        """Run shellcheck if available (non-fatal if shellcheck not installed)."""
        script = os.path.join(os.path.dirname(__file__), "..", "scripts", "setup_github.sh")
        try:
            result = subprocess.run(
                ["shellcheck", "--severity=error", script],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode != 0:
                pytest.fail(f"shellcheck errors:\n{result.stdout}\n{result.stderr}")
        except FileNotFoundError:
            pytest.skip("shellcheck not installed")
