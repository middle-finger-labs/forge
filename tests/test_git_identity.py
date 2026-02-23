"""Tests for integrations.git_identity."""

from __future__ import annotations

import os

import pytest
import yaml

from integrations.git_identity import (
    GitIdentity,
    GitIdentityManager,
    parse_github_url,
)

# ---------------------------------------------------------------------------
# parse_github_url
# ---------------------------------------------------------------------------


class TestParseGithubUrl:
    def test_ssh_standard(self):
        assert parse_github_url("git@github.com:DraftKings/lottery.git") == (
            "DraftKings",
            "lottery",
        )

    def test_ssh_no_git_suffix(self):
        assert parse_github_url("git@github.com:Owner/repo") == ("Owner", "repo")

    def test_ssh_alias(self):
        assert parse_github_url("git@github-dk:DraftKings/svc.git") == (
            "DraftKings",
            "svc",
        )

    def test_https(self):
        assert parse_github_url("https://github.com/nate/project.git") == (
            "nate",
            "project",
        )

    def test_https_no_suffix(self):
        assert parse_github_url("https://github.com/nate/project") == (
            "nate",
            "project",
        )

    def test_https_trailing_slash(self):
        assert parse_github_url("https://github.com/nate/project/") == (
            "nate",
            "project",
        )

    def test_invalid(self):
        assert parse_github_url("not-a-url") is None

    def test_non_github_ssh_still_parses(self):
        # SSH regex intentionally matches any host (to support aliases like
        # github-dk).  gitlab.com is parseable — resolution just falls back
        # to the default identity.
        assert parse_github_url("git@gitlab.com:org/repo.git") == ("org", "repo")

    def test_hyphenated_names(self):
        assert parse_github_url(
            "git@github.com:First-Allegiance/my-repo.git"
        ) == ("First-Allegiance", "my-repo")


# ---------------------------------------------------------------------------
# GitIdentity
# ---------------------------------------------------------------------------


class TestGitIdentity:
    def test_resolved_key_path(self):
        ident = GitIdentity(
            name="test",
            github_username="user",
            email="u@test.com",
            ssh_key_path="~/.ssh/id_ed25519",
            ssh_host_alias="github.com",
        )
        assert ident.resolved_key_path == os.path.expanduser("~/.ssh/id_ed25519")

    def test_to_dict_minimal(self):
        ident = GitIdentity(
            name="t",
            github_username="u",
            email="e@e.com",
            ssh_key_path="~/.ssh/k",
            ssh_host_alias="gh",
        )
        d = ident.to_dict()
        assert d == {
            "name": "t",
            "github_username": "u",
            "email": "e@e.com",
            "ssh_key_path": "~/.ssh/k",
            "ssh_host_alias": "gh",
        }
        assert "github_org" not in d
        assert "default" not in d

    def test_to_dict_full(self):
        ident = GitIdentity(
            name="dk",
            github_username="u",
            email="e@e.com",
            ssh_key_path="~/.ssh/k",
            ssh_host_alias="gh-dk",
            github_org="DraftKings",
            default=True,
            extra_orgs=["DK-Labs"],
        )
        d = ident.to_dict()
        assert d["github_org"] == "DraftKings"
        assert d["default"] is True
        assert d["extra_orgs"] == ["DK-Labs"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_CONFIG = {
    "identities": [
        {
            "name": "personal",
            "github_username": "nate-personal",
            "email": "nate@personal.com",
            "ssh_key_path": "~/.ssh/id_ed25519",
            "ssh_host_alias": "github.com",
            "default": True,
        },
        {
            "name": "draftkings",
            "github_username": "nate-dk",
            "email": "nate@draftkings.com",
            "ssh_key_path": "~/.ssh/id_ed25519_dk",
            "ssh_host_alias": "github-dk",
            "github_org": "DraftKings",
        },
        {
            "name": "first-allegiance",
            "github_username": "nate-fa",
            "email": "nate@firstallegiance.com",
            "ssh_key_path": "~/.ssh/id_ed25519_fa",
            "ssh_host_alias": "github-fa",
            "github_org": "FirstAllegiance",
            "extra_orgs": ["FA-Internal"],
        },
    ]
}


@pytest.fixture
def config_file(tmp_path):
    """Write sample config to a temp file and return its path."""
    p = tmp_path / "identities.yaml"
    with open(p, "w") as f:
        yaml.dump(SAMPLE_CONFIG, f)
    return str(p)


@pytest.fixture
def mgr(config_file):
    return GitIdentityManager(config_path=config_file)


# ---------------------------------------------------------------------------
# GitIdentityManager — loading
# ---------------------------------------------------------------------------


class TestManagerLoad:
    def test_loads_all_identities(self, mgr):
        assert len(mgr.list_identities()) == 3

    def test_identity_fields(self, mgr):
        dk = mgr.get_identity("draftkings")
        assert dk is not None
        assert dk.github_username == "nate-dk"
        assert dk.github_org == "DraftKings"
        assert dk.ssh_host_alias == "github-dk"

    def test_get_default(self, mgr):
        default = mgr.get_default()
        assert default is not None
        assert default.name == "personal"

    def test_missing_config_file(self, tmp_path):
        m = GitIdentityManager(config_path=str(tmp_path / "nope.yaml"))
        assert m.list_identities() == []

    def test_empty_config(self, tmp_path):
        p = tmp_path / "empty.yaml"
        p.write_text("")
        m = GitIdentityManager(config_path=str(p))
        assert m.list_identities() == []

    def test_malformed_entry_skipped(self, tmp_path):
        p = tmp_path / "bad.yaml"
        with open(p, "w") as f:
            yaml.dump({"identities": [{"name": "broken"}]}, f)  # missing fields
        m = GitIdentityManager(config_path=str(p))
        assert m.list_identities() == []


# ---------------------------------------------------------------------------
# resolve_identity
# ---------------------------------------------------------------------------


class TestResolveIdentity:
    def test_org_match(self, mgr):
        ident = mgr.resolve_identity("git@github.com:DraftKings/lottery.git")
        assert ident.name == "draftkings"

    def test_org_case_insensitive(self, mgr):
        ident = mgr.resolve_identity("git@github.com:draftkings/lottery.git")
        assert ident.name == "draftkings"

    def test_extra_org_match(self, mgr):
        ident = mgr.resolve_identity("git@github.com:FA-Internal/tool.git")
        assert ident.name == "first-allegiance"

    def test_username_match(self, mgr):
        ident = mgr.resolve_identity("git@github.com:nate-personal/blog.git")
        assert ident.name == "personal"

    def test_fallback_to_default(self, mgr):
        ident = mgr.resolve_identity("git@github.com:UnknownOrg/thing.git")
        assert ident.name == "personal"  # the default

    def test_unparseable_url(self, mgr):
        ident = mgr.resolve_identity("not-a-url")
        assert ident.name == "personal"  # default

    def test_https_url(self, mgr):
        ident = mgr.resolve_identity(
            "https://github.com/FirstAllegiance/app.git"
        )
        assert ident.name == "first-allegiance"

    def test_no_identities_raises(self, tmp_path):
        p = tmp_path / "empty.yaml"
        p.write_text("")
        m = GitIdentityManager(config_path=str(p))
        with pytest.raises(ValueError, match="No identities configured"):
            m.resolve_identity("git@github.com:Org/repo.git")


# ---------------------------------------------------------------------------
# get_ssh_url
# ---------------------------------------------------------------------------


class TestGetSshUrl:
    def test_rewrites_host(self, mgr):
        dk = mgr.get_identity("draftkings")
        url = mgr.get_ssh_url("git@github.com:DraftKings/lottery.git", dk)
        assert url == "git@github-dk:DraftKings/lottery.git"

    def test_from_https(self, mgr):
        fa = mgr.get_identity("first-allegiance")
        url = mgr.get_ssh_url("https://github.com/FirstAllegiance/app.git", fa)
        assert url == "git@github-fa:FirstAllegiance/app.git"

    def test_passthrough_on_bad_url(self, mgr):
        dk = mgr.get_identity("draftkings")
        url = mgr.get_ssh_url("not-a-url", dk)
        assert url == "not-a-url"


# ---------------------------------------------------------------------------
# get_git_env
# ---------------------------------------------------------------------------


class TestGetGitEnv:
    def test_env_keys(self, mgr):
        dk = mgr.get_identity("draftkings")
        env = mgr.get_git_env(dk)
        assert "GIT_SSH_COMMAND" in env
        assert "id_ed25519_dk" in env["GIT_SSH_COMMAND"]
        assert "IdentitiesOnly=yes" in env["GIT_SSH_COMMAND"]
        assert env["GIT_AUTHOR_EMAIL"] == "nate@draftkings.com"
        assert env["GIT_COMMITTER_EMAIL"] == "nate@draftkings.com"
        assert env["GIT_AUTHOR_NAME"] == "nate-dk"


# ---------------------------------------------------------------------------
# SSH config generation
# ---------------------------------------------------------------------------


class TestSshConfig:
    def test_single_block(self, mgr):
        dk = mgr.get_identity("draftkings")
        block = mgr.generate_ssh_config_block(dk)
        assert "Host github-dk" in block
        assert "HostName github.com" in block
        assert "IdentityFile ~/.ssh/id_ed25519_dk" in block
        assert "IdentitiesOnly yes" in block

    def test_full_config_skips_default_alias(self, mgr):
        full = mgr.generate_full_ssh_config()
        # personal uses github.com alias — should be skipped
        assert "Host github.com" not in full
        assert "[personal] uses default" in full
        # Others should appear
        assert "Host github-dk" in full
        assert "Host github-fa" in full


# ---------------------------------------------------------------------------
# add / remove / save
# ---------------------------------------------------------------------------


class TestAddRemove:
    def test_add_and_persist(self, config_file):
        mgr1 = GitIdentityManager(config_path=config_file)
        mgr1.add_identity(
            GitIdentity(
                name="new-client",
                github_username="nate-nc",
                email="nate@nc.com",
                ssh_key_path="~/.ssh/id_nc",
                ssh_host_alias="github-nc",
                github_org="NewClient",
            )
        )
        assert len(mgr1.list_identities()) == 4

        # Reload from disk
        mgr2 = GitIdentityManager(config_path=config_file)
        assert len(mgr2.list_identities()) == 4
        assert mgr2.get_identity("new-client") is not None

    def test_add_replaces_same_name(self, config_file):
        mgr = GitIdentityManager(config_path=config_file)
        mgr.add_identity(
            GitIdentity(
                name="draftkings",
                github_username="new-user",
                email="new@dk.com",
                ssh_key_path="~/.ssh/id_new",
                ssh_host_alias="github-dk2",
            )
        )
        assert len(mgr.list_identities()) == 3  # replaced, not added
        dk = mgr.get_identity("draftkings")
        assert dk.github_username == "new-user"

    def test_add_default_unsets_others(self, config_file):
        mgr = GitIdentityManager(config_path=config_file)
        mgr.add_identity(
            GitIdentity(
                name="new-default",
                github_username="u",
                email="e@e.com",
                ssh_key_path="~/.ssh/k",
                ssh_host_alias="gh",
                default=True,
            )
        )
        defaults = [i for i in mgr.list_identities() if i.default]
        assert len(defaults) == 1
        assert defaults[0].name == "new-default"

    def test_remove(self, config_file):
        mgr = GitIdentityManager(config_path=config_file)
        assert mgr.remove_identity("draftkings") is True
        assert len(mgr.list_identities()) == 2
        assert mgr.get_identity("draftkings") is None

    def test_remove_nonexistent(self, config_file):
        mgr = GitIdentityManager(config_path=config_file)
        assert mgr.remove_identity("nope") is False
        assert len(mgr.list_identities()) == 3


# ---------------------------------------------------------------------------
# CLI (main function)
# ---------------------------------------------------------------------------


class TestCLI:
    def test_list(self, config_file, capsys):
        from integrations.git_identity import main

        rc = main(["--config", config_file, "list"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "personal" in out
        assert "draftkings" in out

    def test_resolve(self, config_file, capsys):
        from integrations.git_identity import main

        rc = main([
            "--config", config_file,
            "resolve", "git@github.com:DraftKings/svc.git",
        ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "draftkings" in out
        assert "github-dk" in out

    def test_ssh_config(self, config_file, capsys):
        from integrations.git_identity import main

        rc = main(["--config", config_file, "ssh-config"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Host github-dk" in out

    def test_remove_cli(self, config_file, capsys):
        from integrations.git_identity import main

        rc = main(["--config", config_file, "remove", "draftkings"])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Removed" in out
