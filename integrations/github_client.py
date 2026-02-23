"""GitHub API client with multi-account authentication.

Supports two auth methods:

- **PAT (Personal Access Token)**: Uses SSH for git operations and a
  fine-grained PAT for API calls.  Reads from ``GITHUB_TOKEN_{NAME}``
  env var, falling back to ``GITHUB_TOKEN``.  Simplest setup.

- **GitHub App**: Uses a GitHub App installation token for everything.
  Generates a JWT from the app's private key, exchanges it for an
  installation access token, and auto-refreshes when it expires (~1 hr).
  More secure, better for orgs.

Usage::

    from integrations.git_identity import GitIdentity
    from integrations.github_client import GitHubClient

    identity = GitIdentity(name="draftkings", ...)
    async with GitHubClient(identity, auth_method="pat") as gh:
        user = await gh.get_authenticated_user()
        pr = await gh.create_pr("DraftKings", "svc", "feat: thing", "...", "my-branch")
        await gh.clone_repo("git@github.com:DraftKings/svc.git", "/tmp/svc")
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from types import TracebackType

import httpx

from integrations.git_identity import GitIdentity, GitIdentityManager, parse_github_url

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_API_BASE = "https://api.github.com"
_ACCEPT = "application/vnd.github+json"
_API_VERSION = "2022-11-28"

# Retry / rate-limit
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 1.0  # seconds; doubles each attempt
_RATE_LIMIT_BUFFER = 5  # sleep when remaining falls below this


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class GitHubError(Exception):
    """Base exception for GitHub API errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body or {}


class GitHubAuthError(GitHubError):
    """Authentication or authorisation failure (401/403)."""


class GitHubNotFoundError(GitHubError):
    """Resource not found (404)."""


class GitHubRateLimitError(GitHubError):
    """Primary or secondary rate limit hit (403 with rate-limit headers)."""


class GitHubValidationError(GitHubError):
    """Unprocessable entity — invalid input (422)."""


class GitOperationError(Exception):
    """A local git subprocess command failed."""

    def __init__(self, message: str, *, returncode: int = 1, stderr: str = "") -> None:
        super().__init__(message)
        self.returncode = returncode
        self.stderr = stderr


# ---------------------------------------------------------------------------
# GitHub App token management
# ---------------------------------------------------------------------------


@dataclass
class _AppTokenCache:
    """Cached installation access token with expiry."""

    token: str = ""
    expires_at: float = 0.0  # time.monotonic() value

    @property
    def expired(self) -> bool:
        # Refresh 5 minutes before actual expiry for safety
        return time.monotonic() >= (self.expires_at - 300)


def _generate_app_jwt(app_id: str, private_key_pem: str) -> str:
    """Create a short-lived JWT (10 min) for authenticating as a GitHub App.

    Requires the ``PyJWT`` and ``cryptography`` packages.
    """
    try:
        import jwt
    except ImportError as exc:
        raise ImportError(
            "GitHub App auth requires PyJWT: pip install PyJWT cryptography"
        ) from exc

    now = int(time.time())
    payload = {
        "iat": now - 60,  # issued-at, 60s in the past to cover clock skew
        "exp": now + 600,  # expires in 10 minutes (GitHub max)
        "iss": app_id,
    }
    return jwt.encode(payload, private_key_pem, algorithm="RS256")


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class GitHubClient:
    """Async GitHub API client tied to a specific :class:`GitIdentity`.

    Use as an async context manager::

        async with GitHubClient(identity) as gh:
            await gh.create_pr(...)
    """

    def __init__(
        self,
        identity: GitIdentity,
        auth_method: str = "pat",
        *,
        # GitHub App fields — read from env/config if not passed explicitly
        app_id: str | None = None,
        app_private_key_path: str | None = None,
        app_installation_id: str | None = None,
    ) -> None:
        self._identity = identity
        self._auth_method = auth_method

        # --- resolve PAT token ---
        self._pat_token: str | None = None
        if auth_method == "pat":
            env_key = f"GITHUB_TOKEN_{identity.name.upper().replace('-', '_')}"
            self._pat_token = os.environ.get(env_key) or os.environ.get("GITHUB_TOKEN")
            if not self._pat_token:
                raise GitHubAuthError(
                    f"No PAT found.  Set {env_key} or GITHUB_TOKEN env var.",
                    status_code=401,
                )

        # --- resolve GitHub App credentials ---
        self._app_id = app_id or os.environ.get(
            f"GITHUB_APP_ID_{identity.name.upper().replace('-', '_')}",
            os.environ.get("GITHUB_APP_ID", ""),
        )
        self._app_key_path = app_private_key_path or os.environ.get(
            f"GITHUB_APP_KEY_{identity.name.upper().replace('-', '_')}",
            os.environ.get("GITHUB_APP_KEY", ""),
        )
        self._app_installation_id = app_installation_id or os.environ.get(
            f"GITHUB_APP_INSTALLATION_ID_{identity.name.upper().replace('-', '_')}",
            os.environ.get("GITHUB_APP_INSTALLATION_ID", ""),
        )

        if auth_method == "app":
            missing = []
            if not self._app_id:
                missing.append("app_id (GITHUB_APP_ID)")
            if not self._app_key_path:
                missing.append("private_key_path (GITHUB_APP_KEY)")
            if not self._app_installation_id:
                missing.append("installation_id (GITHUB_APP_INSTALLATION_ID)")
            if missing:
                raise GitHubAuthError(
                    f"GitHub App auth missing: {', '.join(missing)}",
                    status_code=401,
                )

        self._app_token_cache = _AppTokenCache()

        # httpx client — created in __aenter__, closed in __aexit__
        self._http: httpx.AsyncClient | None = None

        # Identity manager for SSH env/URL rewriting
        self._id_mgr = GitIdentityManager.__new__(GitIdentityManager)
        self._id_mgr._identities = []  # we only need the helper methods

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> GitHubClient:
        self._http = httpx.AsyncClient(
            base_url=_API_BASE,
            headers={
                "Accept": _ACCEPT,
                "X-GitHub-Api-Version": _API_VERSION,
                "User-Agent": "forge-github-client/1.0",
            },
            timeout=httpx.Timeout(30.0, connect=10.0),
            follow_redirects=True,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    # ------------------------------------------------------------------
    # Auth header resolution
    # ------------------------------------------------------------------

    async def _get_auth_header(self) -> dict[str, str]:
        """Return the ``Authorization`` header for the current auth method."""
        if self._auth_method == "pat":
            return {"Authorization": f"Bearer {self._pat_token}"}

        # GitHub App — get or refresh installation token
        if self._app_token_cache.expired:
            await self._refresh_app_token()
        return {"Authorization": f"Bearer {self._app_token_cache.token}"}

    async def _refresh_app_token(self) -> None:
        """Exchange App JWT for an installation access token."""
        key_path = os.path.expanduser(self._app_key_path)
        with open(key_path) as f:
            private_key = f.read()

        app_jwt = _generate_app_jwt(self._app_id, private_key)

        assert self._http is not None
        resp = await self._http.post(
            f"/app/installations/{self._app_installation_id}/access_tokens",
            headers={"Authorization": f"Bearer {app_jwt}"},
        )

        if resp.status_code != 201:
            ct = resp.headers.get("content-type", "")
            body = resp.json() if ct.startswith("application/json") else {}
            raise GitHubAuthError(
                f"Failed to get installation token: {resp.status_code} {body.get('message', '')}",
                status_code=resp.status_code,
                response_body=body,
            )

        data = resp.json()
        self._app_token_cache.token = data["token"]
        # Token expires in ~1 hour; we track with monotonic clock
        self._app_token_cache.expires_at = time.monotonic() + 3300  # ~55 min

        logger.info(
            "GitHub App token refreshed for installation %s",
            self._app_installation_id,
        )

    # ------------------------------------------------------------------
    # Low-level HTTP with retry + rate-limit handling
    # ------------------------------------------------------------------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | list | None = None,
        params: dict | None = None,
    ) -> httpx.Response:
        """Make an authenticated API request with retry and rate-limit handling."""
        assert self._http is not None, (
            "Client not initialised — use `async with GitHubClient(...) as gh:`"
        )

        last_exc: Exception | None = None

        for attempt in range(_MAX_RETRIES):
            auth = await self._get_auth_header()

            try:
                resp = await self._http.request(
                    method,
                    path,
                    headers=auth,
                    json=json,
                    params=params,
                )
            except httpx.TimeoutException as exc:
                last_exc = exc
                delay = _RETRY_BACKOFF_BASE * (2**attempt)
                logger.warning(
                    "Request timeout (attempt %d/%d), retrying in %.1fs",
                    attempt + 1, _MAX_RETRIES, delay,
                )
                await asyncio.sleep(delay)
                continue
            except httpx.HTTPError as exc:
                last_exc = exc
                delay = _RETRY_BACKOFF_BASE * (2**attempt)
                logger.warning(
                    "HTTP error %s (attempt %d/%d), retrying in %.1fs",
                    exc, attempt + 1, _MAX_RETRIES, delay,
                )
                await asyncio.sleep(delay)
                continue

            # --- Rate limit handling ---
            remaining = resp.headers.get("x-ratelimit-remaining")
            if remaining is not None and int(remaining) < _RATE_LIMIT_BUFFER:
                reset_at = int(resp.headers.get("x-ratelimit-reset", "0"))
                wait = max(reset_at - int(time.time()), 1)
                logger.warning(
                    "Rate limit low (%s remaining), sleeping %ds until reset",
                    remaining, wait,
                )
                await asyncio.sleep(wait)

            # Secondary rate limit (abuse detection): 403 + retry-after
            if resp.status_code == 403:
                retry_after = resp.headers.get("retry-after")
                if retry_after:
                    wait = int(retry_after)
                    logger.warning(
                        "Secondary rate limit, sleeping %ds (attempt %d/%d)",
                        wait, attempt + 1, _MAX_RETRIES,
                    )
                    await asyncio.sleep(wait)
                    continue

                body = _safe_json(resp)
                msg = body.get("message", "")
                if "rate limit" in msg.lower():
                    reset_at = int(resp.headers.get("x-ratelimit-reset", "0"))
                    wait = max(reset_at - int(time.time()), 5)
                    logger.warning(
                        "Rate limited: %s, sleeping %ds", msg, wait,
                    )
                    await asyncio.sleep(wait)
                    continue

            # --- 5xx retry ---
            if resp.status_code >= 500:
                delay = _RETRY_BACKOFF_BASE * (2**attempt)
                logger.warning(
                    "Server error %d (attempt %d/%d), retrying in %.1fs",
                    resp.status_code, attempt + 1, _MAX_RETRIES, delay,
                )
                last_exc = GitHubError(
                    f"Server error {resp.status_code}",
                    status_code=resp.status_code,
                )
                await asyncio.sleep(delay)
                continue

            # --- Success or client error — return immediately ---
            return resp

        # All retries exhausted
        if last_exc:
            raise last_exc
        raise GitHubError("Request failed after all retries")

    async def _api(
        self,
        method: str,
        path: str,
        *,
        json: dict | list | None = None,
        params: dict | None = None,
        expected: tuple[int, ...] = (200, 201),
    ) -> dict | list:
        """Make a request and return parsed JSON, raising on error status."""
        resp = await self._request(method, path, json=json, params=params)
        body = _safe_json(resp)

        if resp.status_code in expected:
            return body

        msg = body.get("message", resp.text[:300]) if isinstance(body, dict) else str(body)[:300]

        resp_body = body if isinstance(body, dict) else {}
        if resp.status_code == 401:
            raise GitHubAuthError(msg, status_code=401, response_body=resp_body)
        if resp.status_code == 403:
            raise GitHubAuthError(msg, status_code=403, response_body=resp_body)
        if resp.status_code == 404:
            raise GitHubNotFoundError(msg, status_code=404, response_body=resp_body)
        if resp.status_code == 422:
            raise GitHubValidationError(
                msg, status_code=422, response_body=body if isinstance(body, dict) else {},
            )
        raise GitHubError(
            f"GitHub API error {resp.status_code}: {msg}",
            status_code=resp.status_code,
            response_body=body if isinstance(body, dict) else {},
        )

    # ------------------------------------------------------------------
    # Git env helper
    # ------------------------------------------------------------------

    def _git_env(self) -> dict[str, str]:
        """Build env dict for subprocess git calls using the identity's SSH key."""
        key = self._identity.resolved_key_path
        return {
            **os.environ,
            "GIT_SSH_COMMAND": (
                f"ssh -i {key} -o IdentitiesOnly=yes"
                " -o StrictHostKeyChecking=accept-new"
            ),
            "GIT_AUTHOR_NAME": self._identity.github_username,
            "GIT_AUTHOR_EMAIL": self._identity.email,
            "GIT_COMMITTER_NAME": self._identity.github_username,
            "GIT_COMMITTER_EMAIL": self._identity.email,
        }

    def _ssh_url(self, repo_url: str) -> str:
        """Rewrite a repo URL to use the identity's SSH host alias."""
        parsed = parse_github_url(repo_url)
        if parsed is None:
            return repo_url
        owner, repo = parsed
        return f"git@{self._identity.ssh_host_alias}:{owner}/{repo}.git"

    async def _run_git(self, *args: str, cwd: str | None = None) -> str:
        """Run a git command asynchronously, returning stdout."""
        proc = await asyncio.create_subprocess_exec(
            "git", *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=cwd,
            env=self._git_env(),
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        stdout = stdout_bytes.decode(errors="replace").strip()
        stderr = stderr_bytes.decode(errors="replace").strip()

        if proc.returncode != 0:
            raise GitOperationError(
                f"git {args[0]} failed (exit {proc.returncode}): {stderr or stdout}",
                returncode=proc.returncode,
                stderr=stderr,
            )
        return stdout

    # ==================================================================
    # Repository operations
    # ==================================================================

    async def clone_repo(
        self,
        repo_url: str,
        dest_path: str,
        *,
        branch: str = "main",
        depth: int | None = None,
    ) -> str:
        """Clone a repo using the identity's SSH key.

        Returns the absolute path to the cloned directory.
        """
        ssh_url = self._ssh_url(repo_url)
        cmd = ["clone", "--branch", branch]
        if depth:
            cmd += ["--depth", str(depth)]
        cmd += [ssh_url, dest_path]

        await self._run_git(*cmd)
        return os.path.abspath(dest_path)

    async def create_branch(
        self,
        owner: str,
        repo: str,
        branch_name: str,
        from_branch: str = "main",
    ) -> None:
        """Create a branch via the GitHub API (refs endpoint)."""
        # Get the SHA of the source branch
        ref_data = await self._api("GET", f"/repos/{owner}/{repo}/git/ref/heads/{from_branch}")
        sha = ref_data["object"]["sha"]

        await self._api(
            "POST",
            f"/repos/{owner}/{repo}/git/refs",
            json={"ref": f"refs/heads/{branch_name}", "sha": sha},
            expected=(201,),
        )

    async def push_branch(self, repo_path: str, branch_name: str) -> None:
        """Push a local branch to origin using the identity's SSH credentials."""
        await self._run_git("push", "origin", branch_name, cwd=repo_path)

    async def create_pr(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
        *,
        draft: bool = True,
    ) -> dict:
        """Create a pull request.  Returns the PR dict (number, url, html_url)."""
        data = await self._api(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            json={
                "title": title,
                "body": body,
                "head": head,
                "base": base,
                "draft": draft,
            },
            expected=(201,),
        )
        return {
            "number": data["number"],
            "url": data["url"],
            "html_url": data["html_url"],
            "state": data["state"],
            "draft": data.get("draft", False),
            "head": data["head"]["ref"],
            "base": data["base"]["ref"],
        }

    async def update_pr(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        *,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
    ) -> dict:
        """Update an existing pull request."""
        payload: dict = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if state is not None:
            payload["state"] = state

        data = await self._api(
            "PATCH",
            f"/repos/{owner}/{repo}/pulls/{pr_number}",
            json=payload,
        )
        return {
            "number": data["number"],
            "url": data["url"],
            "html_url": data["html_url"],
            "state": data["state"],
        }

    async def get_repo_info(self, owner: str, repo: str) -> dict:
        """Get repository metadata."""
        data = await self._api("GET", f"/repos/{owner}/{repo}")
        return {
            "full_name": data["full_name"],
            "default_branch": data["default_branch"],
            "language": data.get("language"),
            "visibility": data.get("visibility", "private"),
            "description": data.get("description"),
            "clone_url": data["clone_url"],
            "ssh_url": data["ssh_url"],
            "archived": data.get("archived", False),
            "fork": data.get("fork", False),
        }

    # ==================================================================
    # Issue operations
    # ==================================================================

    async def create_issue(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        *,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
    ) -> dict:
        """Create a GitHub issue."""
        payload: dict = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        if assignees:
            payload["assignees"] = assignees

        data = await self._api(
            "POST",
            f"/repos/{owner}/{repo}/issues",
            json=payload,
            expected=(201,),
        )
        return {
            "number": data["number"],
            "url": data["url"],
            "html_url": data["html_url"],
            "state": data["state"],
            "title": data["title"],
        }

    async def update_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        *,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
    ) -> dict:
        """Update an existing issue."""
        payload: dict = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            payload["body"] = body
        if state is not None:
            payload["state"] = state
        if labels is not None:
            payload["labels"] = labels
        if assignees is not None:
            payload["assignees"] = assignees

        data = await self._api(
            "PATCH",
            f"/repos/{owner}/{repo}/issues/{issue_number}",
            json=payload,
        )
        return {
            "number": data["number"],
            "url": data["url"],
            "html_url": data["html_url"],
            "state": data["state"],
            "title": data["title"],
        }

    async def list_issues(
        self,
        owner: str,
        repo: str,
        *,
        state: str = "open",
        labels: list[str] | None = None,
        per_page: int = 30,
    ) -> list[dict]:
        """List issues for a repository."""
        params: dict = {"state": state, "per_page": per_page}
        if labels:
            params["labels"] = ",".join(labels)

        data = await self._api(
            "GET",
            f"/repos/{owner}/{repo}/issues",
            params=params,
        )
        return [
            {
                "number": issue["number"],
                "title": issue["title"],
                "state": issue["state"],
                "html_url": issue["html_url"],
                "labels": [lb["name"] for lb in issue.get("labels", [])],
                "assignees": [a["login"] for a in issue.get("assignees", [])],
                "created_at": issue["created_at"],
                "updated_at": issue["updated_at"],
            }
            for issue in data
            if isinstance(issue, dict)
        ]

    async def add_issue_comment(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        body: str,
    ) -> dict:
        """Add a comment to an issue or pull request."""
        data = await self._api(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            json={"body": body},
            expected=(201,),
        )
        return {
            "id": data["id"],
            "url": data["url"],
            "html_url": data["html_url"],
            "body": data["body"],
        }

    # ==================================================================
    # Utility
    # ==================================================================

    async def get_authenticated_user(self) -> dict:
        """Verify auth works and return user/app info."""
        if self._auth_method == "app":
            # App tokens authenticate as an installation, not a user
            data = await self._api("GET", "/app")
            return {
                "type": "app",
                "name": data.get("name"),
                "id": data.get("id"),
                "slug": data.get("slug"),
            }

        data = await self._api("GET", "/user")
        return {
            "type": "user",
            "login": data["login"],
            "id": data["id"],
            "name": data.get("name"),
            "email": data.get("email"),
        }

    async def check_permissions(self, owner: str, repo: str) -> dict:
        """Check what permissions the current token has on a repo.

        Returns a dict with ``permission`` (admin/write/read/none) and
        boolean convenience flags.
        """
        try:
            data = await self._api("GET", f"/repos/{owner}/{repo}")
        except GitHubNotFoundError:
            return {"permission": "none", "admin": False, "push": False, "pull": False}

        perms = data.get("permissions", {})
        if perms.get("admin"):
            level = "admin"
        elif perms.get("push"):
            level = "write"
        elif perms.get("pull"):
            level = "read"
        else:
            level = "none"

        return {
            "permission": level,
            "admin": perms.get("admin", False),
            "push": perms.get("push", False),
            "pull": perms.get("pull", False),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_json(resp: httpx.Response) -> dict | list:
    """Parse response JSON, returning {} on failure."""
    ct = resp.headers.get("content-type", "")
    if "json" not in ct:
        return {}
    try:
        return resp.json()
    except Exception:
        return {}
