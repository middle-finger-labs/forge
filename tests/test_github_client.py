"""Tests for integrations.github_client."""

from __future__ import annotations

import os
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from integrations.git_identity import GitIdentity
from integrations.github_client import (
    GitHubAuthError,
    GitHubClient,
    GitHubError,
    GitHubNotFoundError,
    GitHubRateLimitError,
    GitHubValidationError,
    GitOperationError,
    _AppTokenCache,
    _generate_app_jwt,
    _safe_json,
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
    """Ensure a PAT is available for every test that builds a client."""
    monkeypatch.setenv("GITHUB_TOKEN_TEST_ORG", "ghp_fake123")


@pytest.fixture
def client():
    return GitHubClient(_IDENTITY, auth_method="pat")


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


class TestExceptions:
    def test_github_error_fields(self):
        e = GitHubError("boom", status_code=500, response_body={"msg": "bad"})
        assert str(e) == "boom"
        assert e.status_code == 500
        assert e.response_body == {"msg": "bad"}

    def test_github_error_defaults(self):
        e = GitHubError("x")
        assert e.status_code is None
        assert e.response_body == {}

    def test_auth_error_is_github_error(self):
        e = GitHubAuthError("unauth", status_code=401)
        assert isinstance(e, GitHubError)

    def test_not_found_is_github_error(self):
        e = GitHubNotFoundError("gone", status_code=404)
        assert isinstance(e, GitHubError)

    def test_rate_limit_is_github_error(self):
        e = GitHubRateLimitError("slow down", status_code=403)
        assert isinstance(e, GitHubError)

    def test_validation_is_github_error(self):
        e = GitHubValidationError("invalid", status_code=422)
        assert isinstance(e, GitHubError)

    def test_git_operation_error_fields(self):
        e = GitOperationError("failed", returncode=128, stderr="fatal: ...")
        assert str(e) == "failed"
        assert e.returncode == 128
        assert e.stderr == "fatal: ..."

    def test_git_operation_error_not_github_error(self):
        """GitOperationError is for local git — not a subclass of GitHubError."""
        e = GitOperationError("x")
        assert not isinstance(e, GitHubError)


# ---------------------------------------------------------------------------
# _AppTokenCache
# ---------------------------------------------------------------------------


class TestAppTokenCache:
    def test_expired_when_empty(self):
        c = _AppTokenCache()
        assert c.expired is True

    def test_not_expired_when_fresh(self):
        c = _AppTokenCache(token="tok", expires_at=time.monotonic() + 600)
        assert c.expired is False

    def test_expired_within_safety_margin(self):
        # 4 minutes left, but safety margin is 5 min → expired
        c = _AppTokenCache(token="tok", expires_at=time.monotonic() + 240)
        assert c.expired is True


# ---------------------------------------------------------------------------
# _generate_app_jwt
# ---------------------------------------------------------------------------


class TestGenerateAppJwt:
    def test_missing_pyjwt(self):
        """When PyJWT is not importable, give a clear error."""
        with patch.dict("sys.modules", {"jwt": None}):
            with pytest.raises(ImportError, match="PyJWT"):
                _generate_app_jwt("123", "fake-key")

    def test_calls_jwt_encode(self):
        mock_jwt = MagicMock()
        mock_jwt.encode.return_value = "eyJ.test.token"
        with patch.dict("sys.modules", {"jwt": mock_jwt}):
            result = _generate_app_jwt("42", "PRIVATE_KEY")
        mock_jwt.encode.assert_called_once()
        args, kwargs = mock_jwt.encode.call_args
        payload = args[0]
        assert payload["iss"] == "42"
        assert "iat" in payload
        assert "exp" in payload
        assert args[1] == "PRIVATE_KEY"
        assert kwargs["algorithm"] == "RS256"
        assert result == "eyJ.test.token"


# ---------------------------------------------------------------------------
# Client construction
# ---------------------------------------------------------------------------


class TestClientInit:
    def test_pat_from_env(self, monkeypatch):
        monkeypatch.setenv("GITHUB_TOKEN_TEST_ORG", "ghp_specific")
        c = GitHubClient(_IDENTITY, auth_method="pat")
        assert c._pat_token == "ghp_specific"

    def test_pat_fallback_to_generic(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN_TEST_ORG", raising=False)
        monkeypatch.setenv("GITHUB_TOKEN", "ghp_generic")
        c = GitHubClient(_IDENTITY, auth_method="pat")
        assert c._pat_token == "ghp_generic"

    def test_pat_missing_raises(self, monkeypatch):
        monkeypatch.delenv("GITHUB_TOKEN_TEST_ORG", raising=False)
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
        with pytest.raises(GitHubAuthError, match="No PAT found"):
            GitHubClient(_IDENTITY, auth_method="pat")

    def test_app_auth_missing_fields(self, monkeypatch):
        monkeypatch.delenv("GITHUB_APP_ID", raising=False)
        monkeypatch.delenv("GITHUB_APP_KEY", raising=False)
        monkeypatch.delenv("GITHUB_APP_INSTALLATION_ID", raising=False)
        with pytest.raises(GitHubAuthError, match="GitHub App auth missing"):
            GitHubClient(_IDENTITY, auth_method="app")

    def test_app_auth_explicit_args(self, monkeypatch):
        # No env vars needed if passed explicitly
        c = GitHubClient(
            _IDENTITY,
            auth_method="app",
            app_id="111",
            app_private_key_path="/fake/key.pem",
            app_installation_id="222",
        )
        assert c._app_id == "111"
        assert c._app_installation_id == "222"


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestContextManager:
    @pytest.mark.asyncio
    async def test_enter_creates_http_client(self, client):
        assert client._http is None
        async with client as gh:
            assert gh._http is not None
            assert isinstance(gh._http, httpx.AsyncClient)
        assert client._http is None

    @pytest.mark.asyncio
    async def test_exit_closes_on_exception(self, client):
        with pytest.raises(RuntimeError):
            async with client as gh:
                assert gh._http is not None
                raise RuntimeError("boom")
        assert client._http is None


# ---------------------------------------------------------------------------
# Auth header
# ---------------------------------------------------------------------------


class TestAuthHeader:
    @pytest.mark.asyncio
    async def test_pat_header(self, client):
        async with client as gh:
            header = await gh._get_auth_header()
            assert header == {"Authorization": "Bearer ghp_fake123"}

    @pytest.mark.asyncio
    async def test_app_header_refreshes_on_expired(self, monkeypatch):
        c = GitHubClient(
            _IDENTITY,
            auth_method="app",
            app_id="1",
            app_private_key_path="/fake/key.pem",
            app_installation_id="2",
        )
        c._app_token_cache = _AppTokenCache(token="old", expires_at=0)
        c._refresh_app_token = AsyncMock()

        async with c as gh:
            # After refresh, set a valid token
            def side_effect():
                gh._app_token_cache = _AppTokenCache(
                    token="new-token",
                    expires_at=time.monotonic() + 3600,
                )

            gh._refresh_app_token = AsyncMock(side_effect=side_effect)
            header = await gh._get_auth_header()
            gh._refresh_app_token.assert_called_once()
            assert header == {"Authorization": "Bearer new-token"}


# ---------------------------------------------------------------------------
# _ssh_url
# ---------------------------------------------------------------------------


class TestSshUrl:
    def test_rewrites_github_url(self, client):
        url = client._ssh_url("git@github.com:TestOrg/repo.git")
        assert url == "git@github-test:TestOrg/repo.git"

    def test_rewrites_https_url(self, client):
        url = client._ssh_url("https://github.com/TestOrg/repo.git")
        assert url == "git@github-test:TestOrg/repo.git"

    def test_passthrough_on_bad_url(self, client):
        url = client._ssh_url("not-a-url")
        assert url == "not-a-url"


# ---------------------------------------------------------------------------
# _git_env
# ---------------------------------------------------------------------------


class TestGitEnv:
    def test_contains_ssh_command(self, client):
        env = client._git_env()
        assert "GIT_SSH_COMMAND" in env
        assert "id_test" in env["GIT_SSH_COMMAND"]
        assert "IdentitiesOnly=yes" in env["GIT_SSH_COMMAND"]

    def test_contains_author_info(self, client):
        env = client._git_env()
        assert env["GIT_AUTHOR_NAME"] == "bot-user"
        assert env["GIT_AUTHOR_EMAIL"] == "bot@test.com"
        assert env["GIT_COMMITTER_NAME"] == "bot-user"
        assert env["GIT_COMMITTER_EMAIL"] == "bot@test.com"


# ---------------------------------------------------------------------------
# _safe_json
# ---------------------------------------------------------------------------


class TestSafeJson:
    def test_parses_json(self):
        resp = httpx.Response(200, json={"ok": True})
        assert _safe_json(resp) == {"ok": True}

    def test_returns_empty_on_non_json(self):
        resp = httpx.Response(200, text="plain", headers={"content-type": "text/html"})
        assert _safe_json(resp) == {}

    def test_returns_empty_on_bad_json(self):
        resp = httpx.Response(
            200,
            content=b"not json",
            headers={"content-type": "application/json"},
        )
        assert _safe_json(resp) == {}


# ---------------------------------------------------------------------------
# _request — retry and rate-limit logic
# ---------------------------------------------------------------------------


def _make_response(
    status: int = 200,
    json_body: dict | None = None,
    headers: dict | None = None,
) -> httpx.Response:
    """Create a fake httpx.Response."""
    hdrs = {"content-type": "application/json", **(headers or {})}
    return httpx.Response(
        status,
        json=json_body or {},
        headers=hdrs,
    )


class TestRequest:
    @pytest.mark.asyncio
    async def test_success_no_retry(self, client):
        async with client as gh:
            gh._http.request = AsyncMock(
                return_value=_make_response(200, {"ok": True})
            )
            resp = await gh._request("GET", "/test")
            assert resp.status_code == 200
            gh._http.request.assert_called_once()

    @pytest.mark.asyncio
    async def test_retries_on_timeout(self, client):
        async with client as gh:
            gh._http.request = AsyncMock(
                side_effect=[
                    httpx.TimeoutException("timeout"),
                    _make_response(200, {"ok": True}),
                ]
            )
            with patch("integrations.github_client.asyncio.sleep", new_callable=AsyncMock):
                resp = await gh._request("GET", "/test")
            assert resp.status_code == 200
            assert gh._http.request.call_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_5xx(self, client):
        async with client as gh:
            gh._http.request = AsyncMock(
                side_effect=[
                    _make_response(502, {"message": "bad gateway"}),
                    _make_response(200, {"ok": True}),
                ]
            )
            with patch("integrations.github_client.asyncio.sleep", new_callable=AsyncMock):
                resp = await gh._request("GET", "/test")
            assert resp.status_code == 200
            assert gh._http.request.call_count == 2

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self, client):
        async with client as gh:
            gh._http.request = AsyncMock(
                side_effect=httpx.TimeoutException("timeout"),
            )
            with (
                patch(
                    "integrations.github_client.asyncio.sleep",
                    new_callable=AsyncMock,
                ),
                pytest.raises(httpx.TimeoutException),
            ):
                await gh._request("GET", "/test")
            assert gh._http.request.call_count == 3  # _MAX_RETRIES

    @pytest.mark.asyncio
    async def test_retries_on_secondary_rate_limit(self, client):
        """403 with retry-after header → sleep and retry."""
        rate_resp = _make_response(
            403,
            {"message": "secondary rate limit"},
            headers={"retry-after": "1"},
        )
        ok_resp = _make_response(200, {"ok": True})

        async with client as gh:
            gh._http.request = AsyncMock(side_effect=[rate_resp, ok_resp])
            with patch("integrations.github_client.asyncio.sleep", new_callable=AsyncMock):
                resp = await gh._request("GET", "/test")
            assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_4xx_returned_immediately(self, client):
        """Client errors (4xx) are NOT retried — returned as-is."""
        async with client as gh:
            gh._http.request = AsyncMock(
                return_value=_make_response(422, {"message": "invalid"})
            )
            resp = await gh._request("GET", "/test")
            assert resp.status_code == 422
            gh._http.request.assert_called_once()


# ---------------------------------------------------------------------------
# _api — error classification
# ---------------------------------------------------------------------------


class TestApi:
    @pytest.mark.asyncio
    async def test_returns_json_on_success(self, client):
        async with client as gh:
            gh._request = AsyncMock(
                return_value=_make_response(200, {"data": "value"})
            )
            result = await gh._api("GET", "/test")
            assert result == {"data": "value"}

    @pytest.mark.asyncio
    async def test_raises_auth_error_on_401(self, client):
        async with client as gh:
            gh._request = AsyncMock(
                return_value=_make_response(401, {"message": "bad creds"})
            )
            with pytest.raises(GitHubAuthError) as exc_info:
                await gh._api("GET", "/test")
            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_raises_auth_error_on_403(self, client):
        async with client as gh:
            gh._request = AsyncMock(
                return_value=_make_response(403, {"message": "forbidden"})
            )
            with pytest.raises(GitHubAuthError) as exc_info:
                await gh._api("GET", "/test")
            assert exc_info.value.status_code == 403

    @pytest.mark.asyncio
    async def test_raises_not_found_on_404(self, client):
        async with client as gh:
            gh._request = AsyncMock(
                return_value=_make_response(404, {"message": "not found"})
            )
            with pytest.raises(GitHubNotFoundError):
                await gh._api("GET", "/test")

    @pytest.mark.asyncio
    async def test_raises_validation_on_422(self, client):
        async with client as gh:
            gh._request = AsyncMock(
                return_value=_make_response(422, {"message": "invalid"})
            )
            with pytest.raises(GitHubValidationError):
                await gh._api("GET", "/test")

    @pytest.mark.asyncio
    async def test_raises_generic_on_other_error(self, client):
        async with client as gh:
            gh._request = AsyncMock(
                return_value=_make_response(418, {"message": "teapot"})
            )
            with pytest.raises(GitHubError, match="418"):
                await gh._api("GET", "/test")

    @pytest.mark.asyncio
    async def test_custom_expected_codes(self, client):
        async with client as gh:
            gh._request = AsyncMock(
                return_value=_make_response(204, {})
            )
            result = await gh._api("GET", "/test", expected=(200, 204))
            assert result == {}


# ---------------------------------------------------------------------------
# Repository operations
# ---------------------------------------------------------------------------


class TestRepoOps:
    @pytest.mark.asyncio
    async def test_create_pr(self, client):
        pr_data = {
            "number": 42,
            "url": "https://api.github.com/repos/O/R/pulls/42",
            "html_url": "https://github.com/O/R/pull/42",
            "state": "open",
            "draft": True,
            "head": {"ref": "feat-x"},
            "base": {"ref": "main"},
        }
        async with client as gh:
            gh._api = AsyncMock(return_value=pr_data)
            result = await gh.create_pr("O", "R", "title", "body", "feat-x")
            assert result["number"] == 42
            assert result["html_url"] == "https://github.com/O/R/pull/42"
            assert result["draft"] is True
            gh._api.assert_called_once()
            call_args = gh._api.call_args
            assert call_args[0] == ("POST", "/repos/O/R/pulls")

    @pytest.mark.asyncio
    async def test_update_pr(self, client):
        pr_data = {
            "number": 42,
            "url": "u",
            "html_url": "h",
            "state": "closed",
        }
        async with client as gh:
            gh._api = AsyncMock(return_value=pr_data)
            result = await gh.update_pr("O", "R", 42, state="closed")
            assert result["state"] == "closed"
            call_args = gh._api.call_args
            assert call_args[1]["json"] == {"state": "closed"}

    @pytest.mark.asyncio
    async def test_get_repo_info(self, client):
        repo_data = {
            "full_name": "O/R",
            "default_branch": "main",
            "language": "Python",
            "visibility": "private",
            "description": "test",
            "clone_url": "https://github.com/O/R.git",
            "ssh_url": "git@github.com:O/R.git",
            "archived": False,
            "fork": False,
        }
        async with client as gh:
            gh._api = AsyncMock(return_value=repo_data)
            result = await gh.get_repo_info("O", "R")
            assert result["full_name"] == "O/R"
            assert result["default_branch"] == "main"

    @pytest.mark.asyncio
    async def test_create_branch(self, client):
        ref_data = {"object": {"sha": "abc123"}}
        async with client as gh:
            gh._api = AsyncMock(return_value=ref_data)
            await gh.create_branch("O", "R", "new-branch")
            assert gh._api.call_count == 2
            # Second call creates the ref
            second_call = gh._api.call_args_list[1]
            assert second_call[0][0] == "POST"
            assert "refs" in second_call[0][1]

    @pytest.mark.asyncio
    async def test_clone_repo(self, client):
        async with client as gh:
            gh._run_git = AsyncMock(return_value="")
            result = await gh.clone_repo(
                "git@github.com:TestOrg/repo.git", "/tmp/repo"
            )
            assert result == os.path.abspath("/tmp/repo")
            call_args = gh._run_git.call_args[0]
            assert "clone" in call_args
            # URL should be rewritten to use the identity's SSH alias
            assert "github-test" in call_args[-2]

    @pytest.mark.asyncio
    async def test_clone_repo_with_depth(self, client):
        async with client as gh:
            gh._run_git = AsyncMock(return_value="")
            await gh.clone_repo(
                "git@github.com:TestOrg/repo.git", "/tmp/repo", depth=1
            )
            call_args = gh._run_git.call_args[0]
            assert "--depth" in call_args
            assert "1" in call_args

    @pytest.mark.asyncio
    async def test_push_branch(self, client):
        async with client as gh:
            gh._run_git = AsyncMock(return_value="")
            await gh.push_branch("/tmp/repo", "feat-x")
            gh._run_git.assert_called_once_with(
                "push", "origin", "feat-x", cwd="/tmp/repo"
            )


# ---------------------------------------------------------------------------
# Issue operations
# ---------------------------------------------------------------------------


class TestIssueOps:
    @pytest.mark.asyncio
    async def test_create_issue(self, client):
        issue_data = {
            "number": 1,
            "url": "u",
            "html_url": "h",
            "state": "open",
            "title": "Bug",
        }
        async with client as gh:
            gh._api = AsyncMock(return_value=issue_data)
            result = await gh.create_issue("O", "R", "Bug", "details")
            assert result["number"] == 1
            assert result["title"] == "Bug"
            call_args = gh._api.call_args
            assert call_args[1]["json"]["title"] == "Bug"

    @pytest.mark.asyncio
    async def test_create_issue_with_labels(self, client):
        issue_data = {
            "number": 1, "url": "u", "html_url": "h",
            "state": "open", "title": "Bug",
        }
        async with client as gh:
            gh._api = AsyncMock(return_value=issue_data)
            await gh.create_issue(
                "O", "R", "Bug", "desc", labels=["bug", "p1"]
            )
            payload = gh._api.call_args[1]["json"]
            assert payload["labels"] == ["bug", "p1"]

    @pytest.mark.asyncio
    async def test_update_issue(self, client):
        issue_data = {
            "number": 5, "url": "u", "html_url": "h",
            "state": "closed", "title": "Old",
        }
        async with client as gh:
            gh._api = AsyncMock(return_value=issue_data)
            result = await gh.update_issue("O", "R", 5, state="closed")
            assert result["state"] == "closed"
            payload = gh._api.call_args[1]["json"]
            assert payload == {"state": "closed"}

    @pytest.mark.asyncio
    async def test_list_issues(self, client):
        issues = [
            {
                "number": 1,
                "title": "First",
                "state": "open",
                "html_url": "h1",
                "labels": [{"name": "bug"}],
                "assignees": [{"login": "alice"}],
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-02T00:00:00Z",
            },
        ]
        async with client as gh:
            gh._api = AsyncMock(return_value=issues)
            result = await gh.list_issues("O", "R")
            assert len(result) == 1
            assert result[0]["labels"] == ["bug"]
            assert result[0]["assignees"] == ["alice"]

    @pytest.mark.asyncio
    async def test_add_issue_comment(self, client):
        comment_data = {
            "id": 99,
            "url": "u",
            "html_url": "h",
            "body": "LGTM",
        }
        async with client as gh:
            gh._api = AsyncMock(return_value=comment_data)
            result = await gh.add_issue_comment("O", "R", 1, "LGTM")
            assert result["id"] == 99
            assert result["body"] == "LGTM"


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


class TestUtility:
    @pytest.mark.asyncio
    async def test_get_authenticated_user_pat(self, client):
        user_data = {
            "login": "bot-user",
            "id": 123,
            "name": "Bot",
            "email": "bot@test.com",
        }
        async with client as gh:
            gh._api = AsyncMock(return_value=user_data)
            result = await gh.get_authenticated_user()
            assert result["type"] == "user"
            assert result["login"] == "bot-user"
            gh._api.assert_called_with("GET", "/user")

    @pytest.mark.asyncio
    async def test_get_authenticated_user_app(self, monkeypatch):
        c = GitHubClient(
            _IDENTITY,
            auth_method="app",
            app_id="1",
            app_private_key_path="/fake/key.pem",
            app_installation_id="2",
        )
        app_data = {"name": "My App", "id": 1, "slug": "my-app"}
        async with c as gh:
            gh._api = AsyncMock(return_value=app_data)
            result = await gh.get_authenticated_user()
            assert result["type"] == "app"
            assert result["name"] == "My App"
            gh._api.assert_called_with("GET", "/app")

    @pytest.mark.asyncio
    async def test_check_permissions_admin(self, client):
        repo_data = {
            "permissions": {"admin": True, "push": True, "pull": True},
        }
        async with client as gh:
            gh._api = AsyncMock(return_value=repo_data)
            result = await gh.check_permissions("O", "R")
            assert result["permission"] == "admin"
            assert result["admin"] is True
            assert result["push"] is True

    @pytest.mark.asyncio
    async def test_check_permissions_write(self, client):
        repo_data = {
            "permissions": {"admin": False, "push": True, "pull": True},
        }
        async with client as gh:
            gh._api = AsyncMock(return_value=repo_data)
            result = await gh.check_permissions("O", "R")
            assert result["permission"] == "write"

    @pytest.mark.asyncio
    async def test_check_permissions_read(self, client):
        repo_data = {
            "permissions": {"admin": False, "push": False, "pull": True},
        }
        async with client as gh:
            gh._api = AsyncMock(return_value=repo_data)
            result = await gh.check_permissions("O", "R")
            assert result["permission"] == "read"

    @pytest.mark.asyncio
    async def test_check_permissions_not_found(self, client):
        async with client as gh:
            gh._api = AsyncMock(
                side_effect=GitHubNotFoundError("not found", status_code=404)
            )
            result = await gh.check_permissions("O", "R")
            assert result["permission"] == "none"
            assert result["push"] is False


# ---------------------------------------------------------------------------
# _run_git
# ---------------------------------------------------------------------------


class TestRunGit:
    @pytest.mark.asyncio
    async def test_success(self, client):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"output\n", b"")
        mock_proc.returncode = 0

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await client._run_git("status", cwd="/tmp")
            assert result == "output"

    @pytest.mark.asyncio
    async def test_failure_raises(self, client):
        mock_proc = AsyncMock()
        mock_proc.communicate.return_value = (b"", b"fatal: not a repo")
        mock_proc.returncode = 128

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with pytest.raises(GitOperationError) as exc_info:
                await client._run_git("status", cwd="/tmp")
            assert exc_info.value.returncode == 128
            assert "not a repo" in exc_info.value.stderr
