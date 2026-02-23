"""Manage multiple GitHub accounts and SSH keys on a single machine.

When working across personal, corporate, and contract client repos, each
with a separate GitHub account and SSH key, every ``git clone``, ``push``,
and ``gh pr create`` must use the correct identity.  This module resolves
the right identity from a repo URL, rewrites URLs to use SSH host aliases,
and provides the environment variables that make ``subprocess`` git calls
Just Work.

Usage::

    from integrations.git_identity import GitIdentityManager

    mgr = GitIdentityManager()                      # loads ~/.forge/identities.yaml
    identity = mgr.resolve_identity("git@github.com:DraftKings/lottery-service.git")
    env = mgr.get_git_env(identity)
    url = mgr.get_ssh_url("git@github.com:DraftKings/lottery-service.git", identity)
    subprocess.run(["git", "clone", url], env={**os.environ, **env})

CLI::

    python -m integrations.git_identity list
    python -m integrations.git_identity test personal
    python -m integrations.git_identity test --all
    python -m integrations.git_identity add
    python -m integrations.git_identity resolve git@github.com:DraftKings/repo.git
    python -m integrations.git_identity ssh-config
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

import yaml

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class GitIdentity:
    """A single GitHub account + SSH key pair."""

    name: str  # e.g. "personal", "draftkings", "first-allegiance"
    github_username: str
    email: str
    ssh_key_path: str  # e.g. ~/.ssh/id_ed25519_personal
    ssh_host_alias: str  # e.g. "github-personal" (Host in ~/.ssh/config)
    github_org: str | None = None  # e.g. "DraftKings" — for org-scoped repos
    default: bool = False
    # Extra orgs this identity covers (e.g. subsidiary orgs under the same key)
    extra_orgs: list[str] = field(default_factory=list)

    @property
    def resolved_key_path(self) -> str:
        """Return the SSH key path with ``~`` expanded."""
        return os.path.expanduser(self.ssh_key_path)

    def to_dict(self) -> dict:
        """Serialize to a dict suitable for YAML output."""
        d: dict = {
            "name": self.name,
            "github_username": self.github_username,
            "email": self.email,
            "ssh_key_path": self.ssh_key_path,
            "ssh_host_alias": self.ssh_host_alias,
        }
        if self.github_org:
            d["github_org"] = self.github_org
        if self.default:
            d["default"] = True
        if self.extra_orgs:
            d["extra_orgs"] = self.extra_orgs
        return d


# ---------------------------------------------------------------------------
# URL parsing
# ---------------------------------------------------------------------------

# git@github.com:Owner/repo.git  or  git@github-alias:Owner/repo.git
_SSH_RE = re.compile(r"^git@[\w.\-]+:([\w.\-]+)/([\w.\-]+?)(?:\.git)?$")

# https://github.com/Owner/repo.git  or  https://github.com/Owner/repo
_HTTPS_RE = re.compile(
    r"^https?://github\.com/([\w.\-]+)/([\w.\-]+?)(?:\.git)?/?$"
)


def parse_github_url(url: str) -> tuple[str, str] | None:
    """Extract (owner, repo) from a GitHub URL.  Returns None on failure."""
    m = _SSH_RE.match(url) or _HTTPS_RE.match(url)
    if m:
        return m.group(1), m.group(2)
    return None


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


_DEFAULT_CONFIG_PATH = "~/.forge/identities.yaml"


class GitIdentityManager:
    """Load, resolve, and manage multiple GitHub identities.

    In multi-tenant mode, call :meth:`load_org_identities` to populate
    identities from the ``org_identities`` database table. Falls back
    to the local YAML config when no org identities are found.
    """

    def __init__(self, config_path: str = _DEFAULT_CONFIG_PATH) -> None:
        self._config_path = os.path.expanduser(config_path)
        self._identities: list[GitIdentity] = []
        self._load()

    # ------------------------------------------------------------------
    # Org identity loading (database-backed, multi-tenant)
    # ------------------------------------------------------------------

    @classmethod
    async def from_org(cls, org_id: str, config_path: str = _DEFAULT_CONFIG_PATH) -> "GitIdentityManager":
        """Create a GitIdentityManager populated from org_identities table.

        Falls back to local YAML if no org identities exist.
        """
        mgr = cls.__new__(cls)
        mgr._config_path = os.path.expanduser(config_path)
        mgr._identities = []

        # Try loading from DB
        try:
            from auth.secrets import list_org_identities, get_org_identity_token, decrypt_secret
            import asyncpg

            db_identities = await list_org_identities(org_id)
            if db_identities:
                for row in db_identities:
                    mgr._identities.append(
                        GitIdentity(
                            name=row["name"],
                            github_username=row["github_username"],
                            email=row["email"],
                            ssh_key_path="",  # Hosted mode uses token auth, not SSH keys
                            ssh_host_alias=f"github-{row['name']}",
                            github_org=row.get("github_org"),
                            default=row.get("is_default", False),
                        )
                    )
                return mgr
        except Exception:
            pass

        # Fall back to local YAML
        mgr._load()
        return mgr

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load identities from the YAML config file."""
        if not os.path.isfile(self._config_path):
            return

        with open(self._config_path) as f:
            data = yaml.safe_load(f) or {}

        raw_list = data.get("identities", [])
        for item in raw_list:
            if not isinstance(item, dict):
                continue
            try:
                self._identities.append(
                    GitIdentity(
                        name=item["name"],
                        github_username=item["github_username"],
                        email=item["email"],
                        ssh_key_path=item["ssh_key_path"],
                        ssh_host_alias=item["ssh_host_alias"],
                        github_org=item.get("github_org"),
                        default=item.get("default", False),
                        extra_orgs=item.get("extra_orgs", []),
                    )
                )
            except KeyError:
                # Skip malformed entries
                continue

    def _save(self) -> None:
        """Persist the current identity list back to disk."""
        os.makedirs(os.path.dirname(self._config_path), exist_ok=True)
        data = {"identities": [ident.to_dict() for ident in self._identities]}
        with open(self._config_path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def list_identities(self) -> list[GitIdentity]:
        """Return all configured identities."""
        return list(self._identities)

    def get_identity(self, name: str) -> GitIdentity | None:
        """Look up a single identity by its short name."""
        for ident in self._identities:
            if ident.name == name:
                return ident
        return None

    def get_default(self) -> GitIdentity | None:
        """Return the identity marked ``default: true``, or None."""
        for ident in self._identities:
            if ident.default:
                return ident
        return None

    def resolve_identity(self, repo_url: str) -> GitIdentity:
        """Pick the correct identity for a GitHub repo URL.

        Resolution order:
        1. Match ``github_org`` (case-insensitive) against the URL owner.
        2. Match ``extra_orgs`` entries.
        3. Match ``github_username`` against the URL owner.
        4. Fall back to the default identity.
        5. Fall back to the first identity in the list.

        Raises ``ValueError`` if no identities are configured.
        """
        if not self._identities:
            raise ValueError(
                f"No identities configured.  Create {self._config_path} or "
                "run: python -m integrations.git_identity add"
            )

        parsed = parse_github_url(repo_url)
        if parsed is None:
            return self.get_default() or self._identities[0]

        owner, _repo = parsed
        owner_lower = owner.lower()

        # 1. Exact org match
        for ident in self._identities:
            if ident.github_org and ident.github_org.lower() == owner_lower:
                return ident

        # 2. Extra orgs
        for ident in self._identities:
            if any(o.lower() == owner_lower for o in ident.extra_orgs):
                return ident

        # 3. Username match
        for ident in self._identities:
            if ident.github_username.lower() == owner_lower:
                return ident

        # 4/5. Default or first
        return self.get_default() or self._identities[0]

    # ------------------------------------------------------------------
    # URL rewriting
    # ------------------------------------------------------------------

    def get_ssh_url(self, repo_url: str, identity: GitIdentity) -> str:
        """Rewrite a GitHub URL to use the identity's SSH host alias.

        ``git@github.com:DraftKings/repo.git``
        becomes ``git@github-dk:DraftKings/repo.git``

        This lets SSH config route the connection through the correct
        ``IdentityFile`` without per-command ``GIT_SSH_COMMAND`` overrides.
        """
        parsed = parse_github_url(repo_url)
        if parsed is None:
            return repo_url  # Can't rewrite — return as-is

        owner, repo = parsed
        return f"git@{identity.ssh_host_alias}:{owner}/{repo}.git"

    # ------------------------------------------------------------------
    # Environment
    # ------------------------------------------------------------------

    def get_git_env(self, identity: GitIdentity) -> dict[str, str]:
        """Return environment variables for ``subprocess`` git calls.

        Sets ``GIT_SSH_COMMAND`` to force the correct key (most reliable
        approach — works even if ~/.ssh/config is incomplete) and sets
        author/committer identity.
        """
        env: dict[str, str] = {
            "GIT_AUTHOR_NAME": identity.github_username,
            "GIT_AUTHOR_EMAIL": identity.email,
            "GIT_COMMITTER_NAME": identity.github_username,
            "GIT_COMMITTER_EMAIL": identity.email,
        }
        # Only set SSH command if a key path is configured
        key = identity.resolved_key_path
        if key and os.path.isfile(key):
            env["GIT_SSH_COMMAND"] = f"ssh -i {key} -o IdentitiesOnly=yes"
        return env

    async def get_token_for_identity(self, identity: GitIdentity, org_id: str) -> str | None:
        """Look up the GitHub PAT for an identity from the org_identities table.

        Returns ``None`` if the identity has no token stored or if running
        in local (YAML-only) mode.
        """
        try:
            from auth.secrets import list_org_identities, get_org_identity_token

            db_identities = await list_org_identities(org_id)
            for row in db_identities:
                if row["name"] == identity.name and row.get("has_github_token"):
                    return await get_org_identity_token(org_id, row["id"])
        except Exception:
            pass
        return None

    def get_token_env(self, token: str) -> dict[str, str]:
        """Return environment variables to use token-based HTTPS auth for git.

        Works with ``git clone https://github.com/...`` when paired with
        the GH_TOKEN or GITHUB_TOKEN env var.
        """
        return {
            "GH_TOKEN": token,
            "GITHUB_TOKEN": token,
        }

    # ------------------------------------------------------------------
    # SSH config generation
    # ------------------------------------------------------------------

    def generate_ssh_config_block(self, identity: GitIdentity) -> str:
        """Generate the ``~/.ssh/config`` Host block for an identity.

        Example output::

            Host github-dk
                HostName github.com
                User git
                IdentityFile ~/.ssh/id_ed25519_dk
                IdentitiesOnly yes
        """
        return (
            f"Host {identity.ssh_host_alias}\n"
            f"    HostName github.com\n"
            f"    User git\n"
            f"    IdentityFile {identity.ssh_key_path}\n"
            f"    IdentitiesOnly yes\n"
        )

    def generate_full_ssh_config(self) -> str:
        """Generate SSH config blocks for all identities."""
        blocks: list[str] = []
        for ident in self._identities:
            # Skip if the alias is plain github.com — user's existing config
            # already handles that.
            if ident.ssh_host_alias == "github.com":
                blocks.append(f"# [{ident.name}] uses default github.com Host")
                continue
            blocks.append(
                f"# [{ident.name}]\n{self.generate_ssh_config_block(ident)}"
            )
        return "\n".join(blocks)

    # ------------------------------------------------------------------
    # Setup / test
    # ------------------------------------------------------------------

    def setup_identity(self, identity: GitIdentity) -> dict:
        """Verify an identity's SSH key and test the GitHub connection.

        Returns a dict with ``key_exists``, ``connection_ok``,
        ``github_user``, and ``error`` fields.
        """
        result: dict = {
            "name": identity.name,
            "key_exists": False,
            "connection_ok": False,
            "github_user": None,
            "error": None,
        }

        key_path = identity.resolved_key_path
        if not os.path.isfile(key_path):
            result["error"] = f"SSH key not found: {key_path}"
            return result
        result["key_exists"] = True

        # Test connection using GIT_SSH_COMMAND (most reliable)
        env = {**os.environ, **self.get_git_env(identity)}
        try:
            proc = subprocess.run(
                ["ssh", "-T", "git@github.com", "-o", "StrictHostKeyChecking=accept-new"],
                capture_output=True,
                text=True,
                timeout=15,
                env=env,
            )
            # GitHub always returns exit code 1 for `ssh -T` but prints the
            # username in stderr: "Hi <user>! You've successfully authenticated"
            output = proc.stderr + proc.stdout
            if "successfully authenticated" in output.lower():
                result["connection_ok"] = True
                # Extract username from "Hi <user>!"
                m = re.search(r"Hi (\S+?)!", output)
                if m:
                    result["github_user"] = m.group(1)
            else:
                result["error"] = output.strip()[:200]
        except subprocess.TimeoutExpired:
            result["error"] = "SSH connection timed out (15s)"
        except FileNotFoundError:
            result["error"] = "ssh command not found on PATH"
        except OSError as exc:
            result["error"] = str(exc)

        return result

    # ------------------------------------------------------------------
    # Add / remove
    # ------------------------------------------------------------------

    def add_identity(self, identity: GitIdentity) -> None:
        """Add or replace an identity and persist to disk."""
        # Remove existing identity with the same name
        self._identities = [
            i for i in self._identities if i.name != identity.name
        ]
        # If this is marked default, unset default on others
        if identity.default:
            for i in self._identities:
                i.default = False
        self._identities.append(identity)
        self._save()

    def remove_identity(self, name: str) -> bool:
        """Remove an identity by name.  Returns True if found."""
        before = len(self._identities)
        self._identities = [
            i for i in self._identities if i.name != name
        ]
        if len(self._identities) < before:
            self._save()
            return True
        return False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _cmd_list(mgr: GitIdentityManager, _args: argparse.Namespace) -> int:
    identities = mgr.list_identities()
    if not identities:
        print("No identities configured.")
        print(f"  Config file: {mgr._config_path}")
        print("  Run: python -m integrations.git_identity add")
        return 0

    print(f"{'Name':<20} {'Username':<20} {'Org':<18} {'SSH Alias':<22} {'Default'}")
    print("-" * 100)
    for ident in identities:
        default_mark = "*" if ident.default else ""
        org = ident.github_org or "-"
        print(
            f"{ident.name:<20} {ident.github_username:<20} {org:<18} "
            f"{ident.ssh_host_alias:<22} {default_mark}"
        )
    return 0


def _cmd_test(mgr: GitIdentityManager, args: argparse.Namespace) -> int:
    if args.all:
        identities = mgr.list_identities()
    else:
        ident = mgr.get_identity(args.name)
        if ident is None:
            print(f"Identity not found: {args.name}")
            return 1
        identities = [ident]

    if not identities:
        print("No identities configured.")
        return 1

    all_ok = True
    for ident in identities:
        result = mgr.setup_identity(ident)
        key_icon = "OK" if result["key_exists"] else "MISSING"
        conn_icon = "OK" if result["connection_ok"] else "FAIL"

        print(f"\n  {ident.name}")
        print(f"    SSH key:     [{key_icon}] {ident.ssh_key_path}")
        print(f"    Connection:  [{conn_icon}]", end="")
        if result["github_user"]:
            print(f" authenticated as {result['github_user']}")
        elif result["error"]:
            print(f" {result['error']}")
            all_ok = False
        else:
            print()
            all_ok = False

    return 0 if all_ok else 1


def _cmd_resolve(mgr: GitIdentityManager, args: argparse.Namespace) -> int:
    try:
        ident = mgr.resolve_identity(args.url)
    except ValueError as exc:
        print(f"Error: {exc}")
        return 1

    ssh_url = mgr.get_ssh_url(args.url, ident)
    env = mgr.get_git_env(ident)

    print(f"  Identity:    {ident.name}")
    print(f"  Username:    {ident.github_username}")
    print(f"  Email:       {ident.email}")
    print(f"  SSH URL:     {ssh_url}")
    print(f"  SSH key:     {ident.ssh_key_path}")
    print(f"  GIT_SSH_COMMAND: {env['GIT_SSH_COMMAND']}")
    return 0


def _cmd_ssh_config(mgr: GitIdentityManager, _args: argparse.Namespace) -> int:
    config = mgr.generate_full_ssh_config()
    if not config:
        print("No identities configured.")
        return 1

    print("# --- Forge git identity SSH config ---")
    print("# Add the following to ~/.ssh/config\n")
    print(config)
    return 0


def _cmd_add(mgr: GitIdentityManager, _args: argparse.Namespace) -> int:
    print("Add a new GitHub identity\n")

    name = input("  Short name (e.g. personal, draftkings): ").strip()
    if not name:
        print("Aborted — name is required.")
        return 1

    username = input("  GitHub username: ").strip()
    email = input("  Email address: ").strip()
    ssh_key = input("  SSH key path [~/.ssh/id_ed25519]: ").strip() or "~/.ssh/id_ed25519"
    alias = input(f"  SSH host alias [github-{name}]: ").strip() or f"github-{name}"
    org = input("  GitHub org (blank if personal): ").strip() or None
    is_default = input("  Make default? [y/N]: ").strip().lower() == "y"

    ident = GitIdentity(
        name=name,
        github_username=username,
        email=email,
        ssh_key_path=ssh_key,
        ssh_host_alias=alias,
        github_org=org,
        default=is_default,
    )

    mgr.add_identity(ident)
    print(f"\n  Identity '{name}' saved to {mgr._config_path}")

    # Show SSH config block
    if alias != "github.com":
        print("\n  Add this to ~/.ssh/config:\n")
        for line in mgr.generate_ssh_config_block(ident).splitlines():
            print(f"    {line}")

    return 0


def _cmd_remove(mgr: GitIdentityManager, args: argparse.Namespace) -> int:
    if mgr.remove_identity(args.name):
        print(f"Removed identity: {args.name}")
        return 0
    print(f"Identity not found: {args.name}")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m integrations.git_identity",
        description="Manage multiple GitHub identities and SSH keys.",
    )
    parser.add_argument(
        "--config",
        default=_DEFAULT_CONFIG_PATH,
        help=f"Path to identities YAML (default: {_DEFAULT_CONFIG_PATH})",
    )
    sub = parser.add_subparsers(dest="command")

    # list
    sub.add_parser("list", help="List all configured identities")

    # test
    p_test = sub.add_parser("test", help="Test SSH connectivity for an identity")
    p_test.add_argument("name", nargs="?", default=None, help="Identity name")
    p_test.add_argument("--all", action="store_true", help="Test all identities")

    # resolve
    p_resolve = sub.add_parser("resolve", help="Resolve identity for a repo URL")
    p_resolve.add_argument("url", help="GitHub repo URL")

    # ssh-config
    sub.add_parser("ssh-config", help="Print SSH config blocks for all identities")

    # add
    sub.add_parser("add", help="Interactively add a new identity")

    # remove
    p_remove = sub.add_parser("remove", help="Remove an identity")
    p_remove.add_argument("name", help="Identity name to remove")

    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    mgr = GitIdentityManager(config_path=args.config)

    dispatch = {
        "list": _cmd_list,
        "test": _cmd_test,
        "resolve": _cmd_resolve,
        "ssh-config": _cmd_ssh_config,
        "add": _cmd_add,
        "remove": _cmd_remove,
    }
    return dispatch[args.command](mgr, args)


if __name__ == "__main__":
    sys.exit(main())
