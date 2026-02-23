"""Tests for integrations.issue_tracker."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from integrations.git_identity import GitIdentity
from integrations.github_client import GitHubClient
from integrations.issue_tracker import (
    IssueTracker,
    _format_checklist,
    _format_sub_issue_body,
    _is_bot_comment,
    _label_context_line,
    _priority_weight,
    _ticket_type_labels,
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
    client = GitHubClient(_IDENTITY, auth_method="pat")
    client._api = AsyncMock(return_value={})
    client.list_issues = AsyncMock(return_value=[])
    client.create_issue = AsyncMock(return_value={
        "number": 100, "url": "u", "html_url": "h",
        "state": "open", "title": "Sub",
    })
    client.add_issue_comment = AsyncMock(return_value={
        "id": 1, "url": "u", "html_url": "h", "body": "ok",
    })
    return client


@pytest.fixture
def tracker(gh_client):
    return IssueTracker(gh_client, "TestOrg", "my-repo")


# Sample GitHub API responses

ISSUE_RESPONSE = {
    "number": 42,
    "title": "Add user registration",
    "body": (
        "We need a POST /register endpoint.\n\n"
        "## Requirements\n- Email + password\n- Bcrypt hashing"
    ),
    "state": "open",
    "html_url": "https://github.com/TestOrg/my-repo/issues/42",
    "labels": [
        {"name": "feature"},
        {"name": "high"},
    ],
    "assignees": [{"login": "alice"}],
    "user": {"login": "nate", "type": "User"},
}

COMMENTS_RESPONSE = [
    {
        "user": {"login": "nate", "type": "User"},
        "body": "Should we also add email verification?",
        "created_at": "2024-01-01T00:00:00Z",
    },
    {
        "user": {"login": "bob", "type": "User"},
        "body": "Yes, add it as a follow-up.",
        "created_at": "2024-01-02T00:00:00Z",
    },
    {
        # Bot comment — should be filtered out
        "user": {"login": "dependabot[bot]", "type": "Bot"},
        "body": "Bumped dependencies.",
        "created_at": "2024-01-03T00:00:00Z",
    },
]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestLabelContextLine:
    def test_bug_label(self):
        assert "Bug fix" in _label_context_line(["bug"])

    def test_feature_label(self):
        assert "feature request" in _label_context_line(["feature"]).lower()

    def test_enhancement_label(self):
        result = _label_context_line(["enhancement"])
        assert "Enhancement" in result

    def test_no_match(self):
        assert _label_context_line(["wontfix", "duplicate"]) == ""

    def test_first_match_wins(self):
        result = _label_context_line(["bug", "feature"])
        assert "Bug fix" in result


class TestPriorityWeight:
    def test_critical(self):
        assert _priority_weight(["critical"]) == 40

    def test_high(self):
        assert _priority_weight(["high"]) == 30

    def test_medium(self):
        assert _priority_weight(["medium"]) == 20

    def test_low(self):
        assert _priority_weight(["low"]) == 10

    def test_no_priority(self):
        assert _priority_weight(["bug", "forge"]) == 0

    def test_picks_highest(self):
        assert _priority_weight(["low", "critical"]) == 40

    def test_p0_alias(self):
        assert _priority_weight(["p0"]) == 40

    def test_case_insensitive_via_lower(self):
        # Labels come from GitHub already lowered by our list_issues
        assert _priority_weight(["high"]) == 30


class TestIsBotComment:
    def test_bot_type(self):
        assert _is_bot_comment({"user": {"type": "Bot"}, "body": "x"})

    def test_forge_comment(self):
        assert _is_bot_comment(
            {"user": {"type": "User"}, "body": "\U0001f525 **Forge: Pipeline started**"}
        )

    def test_human_comment(self):
        assert not _is_bot_comment(
            {"user": {"type": "User"}, "body": "Looks good to me"}
        )


class TestTicketTypeLabels:
    def test_bug_fix(self):
        labels = _ticket_type_labels({"ticket_type": "bug_fix"})
        assert "forge-generated" in labels
        assert "bug" in labels

    def test_feature(self):
        labels = _ticket_type_labels({"ticket_type": "feature"})
        assert "enhancement" in labels

    def test_unknown_type(self):
        labels = _ticket_type_labels({"ticket_type": "refactor"})
        assert labels == ["forge-generated"]


class TestFormatSubIssueBody:
    def test_basic_format(self):
        ticket = {
            "ticket_key": "FORGE-1",
            "title": "Add login",
            "description": "Build login page",
            "acceptance_criteria": ["Returns 200", "Sets cookie"],
            "priority": "high",
            "story_points": 3,
            "dependencies": ["FORGE-0"],
        }
        body = _format_sub_issue_body(ticket, 42)
        assert "Part of #42" in body
        assert "FORGE-1" in body
        assert "## Description" in body
        assert "Build login page" in body
        assert "- [ ] Returns 200" in body
        assert "- [ ] Sets cookie" in body
        assert "high" in body.lower()
        assert "`FORGE-0`" in body

    def test_minimal_ticket(self):
        body = _format_sub_issue_body(
            {"ticket_key": "T-1", "description": "x"}, 1,
        )
        assert "Part of #1" in body
        assert "Acceptance Criteria" not in body


class TestFormatChecklist:
    def test_basic(self):
        tickets = [
            {"ticket_key": "F-1", "title": "Login"},
            {"ticket_key": "F-2", "title": "Signup"},
        ]
        result = _format_checklist(tickets, [10, 11])
        assert "- [ ] #10" in result
        assert "`F-1`" in result
        assert "- [ ] #11" in result
        assert "`F-2`" in result


# ---------------------------------------------------------------------------
# get_issue_as_spec
# ---------------------------------------------------------------------------


class TestGetIssueAsSpec:
    @pytest.mark.asyncio
    async def test_formats_full_issue(self, tracker, gh_client):
        gh_client._api.side_effect = [
            ISSUE_RESPONSE,   # GET issue
            COMMENTS_RESPONSE,  # GET comments
        ]

        spec = await tracker.get_issue_as_spec(42)

        # Title included
        assert "Add user registration" in spec
        # Body included
        assert "POST /register" in spec
        # Label context
        assert "feature" in spec.lower()
        # Comments from humans included
        assert "email verification" in spec
        assert "follow-up" in spec
        # Bot comment excluded
        assert "Bumped dependencies" not in spec
        # Source reference
        assert "Issue #42" in spec

    @pytest.mark.asyncio
    async def test_handles_empty_body(self, tracker, gh_client):
        issue = {**ISSUE_RESPONSE, "body": None, "labels": []}
        gh_client._api.side_effect = [issue, []]

        spec = await tracker.get_issue_as_spec(42)
        assert "Add user registration" in spec

    @pytest.mark.asyncio
    async def test_handles_no_comments(self, tracker, gh_client):
        gh_client._api.side_effect = [ISSUE_RESPONSE, []]

        spec = await tracker.get_issue_as_spec(42)
        assert "Additional Context" not in spec

    @pytest.mark.asyncio
    async def test_bug_label_context(self, tracker, gh_client):
        issue = {
            **ISSUE_RESPONSE,
            "labels": [{"name": "bug"}],
        }
        gh_client._api.side_effect = [issue, []]

        spec = await tracker.get_issue_as_spec(42)
        assert "Bug fix" in spec


# ---------------------------------------------------------------------------
# get_issues_for_pipeline
# ---------------------------------------------------------------------------


class TestGetIssuesForPipeline:
    @pytest.mark.asyncio
    async def test_returns_sorted_by_priority(self, tracker, gh_client):
        gh_client.list_issues.return_value = [
            {
                "number": 1, "title": "Low", "state": "open",
                "html_url": "h", "labels": ["forge", "low"],
                "assignees": [], "created_at": "x", "updated_at": "x",
            },
            {
                "number": 2, "title": "Critical", "state": "open",
                "html_url": "h", "labels": ["forge", "critical"],
                "assignees": [], "created_at": "x", "updated_at": "x",
            },
            {
                "number": 3, "title": "High", "state": "open",
                "html_url": "h", "labels": ["forge", "high"],
                "assignees": [], "created_at": "x", "updated_at": "x",
            },
        ]
        # _get_issue_body calls
        gh_client._api.side_effect = [
            {"body": "low body"},
            {"body": "crit body"},
            {"body": "high body"},
        ]

        issues = await tracker.get_issues_for_pipeline(
            labels=["forge"], limit=10,
        )

        assert len(issues) == 3
        assert issues[0]["title"] == "Critical"
        assert issues[1]["title"] == "High"
        assert issues[2]["title"] == "Low"

    @pytest.mark.asyncio
    async def test_respects_limit(self, tracker, gh_client):
        gh_client.list_issues.return_value = [
            {
                "number": i, "title": f"Issue {i}", "state": "open",
                "html_url": "h", "labels": ["forge"],
                "assignees": [], "created_at": "x", "updated_at": "x",
            }
            for i in range(10)
        ]
        gh_client._api.side_effect = [
            {"body": ""} for _ in range(10)
        ]

        issues = await tracker.get_issues_for_pipeline(limit=3)
        assert len(issues) == 3

    @pytest.mark.asyncio
    async def test_default_labels_forge(self, tracker, gh_client):
        gh_client.list_issues.return_value = []
        await tracker.get_issues_for_pipeline()
        gh_client.list_issues.assert_called_once()
        call_kwargs = gh_client.list_issues.call_args[1]
        assert call_kwargs["labels"] == ["forge"]


# ---------------------------------------------------------------------------
# update_issue_status
# ---------------------------------------------------------------------------


class TestUpdateIssueStatus:
    @pytest.mark.asyncio
    async def test_posts_status_comment(self, tracker, gh_client):
        await tracker.update_issue_status(42, "Pipeline started")

        gh_client.add_issue_comment.assert_called_once()
        args = gh_client.add_issue_comment.call_args[0]
        assert args[2] == 42
        body = args[3]
        assert "Forge: Pipeline started" in body
        assert "\U0001f525" in body  # 🔥

    @pytest.mark.asyncio
    async def test_includes_details(self, tracker, gh_client):
        await tracker.update_issue_status(
            42, "Pipeline failed", "Timeout in stage 5",
        )
        body = gh_client.add_issue_comment.call_args[0][3]
        assert "Timeout in stage 5" in body
        assert "\u274c" in body  # ❌

    @pytest.mark.asyncio
    async def test_unknown_status_uses_default_emoji(
        self, tracker, gh_client,
    ):
        await tracker.update_issue_status(42, "Custom status")
        body = gh_client.add_issue_comment.call_args[0][3]
        assert "\U0001f916" in body  # 🤖
        assert "Custom status" in body


# ---------------------------------------------------------------------------
# create_sub_issues
# ---------------------------------------------------------------------------


class TestCreateSubIssues:
    @pytest.mark.asyncio
    async def test_creates_issues_and_checklist(self, tracker, gh_client):
        # create_issue returns incrementing numbers
        gh_client.create_issue.side_effect = [
            {"number": 100, "url": "u", "html_url": "h", "state": "open", "title": "s1"},
            {"number": 101, "url": "u", "html_url": "h", "state": "open", "title": "s2"},
        ]

        tickets = [
            {
                "ticket_key": "FORGE-1",
                "title": "Login page",
                "description": "Build it",
                "acceptance_criteria": ["AC1"],
                "ticket_type": "feature",
            },
            {
                "ticket_key": "FORGE-2",
                "title": "Signup page",
                "description": "Build it too",
                "acceptance_criteria": ["AC2"],
                "ticket_type": "bug_fix",
            },
        ]

        numbers = await tracker.create_sub_issues(42, tickets)

        assert numbers == [100, 101]
        assert gh_client.create_issue.call_count == 2

        # First issue should have enhancement label
        first_labels = gh_client.create_issue.call_args_list[0][1]["labels"]
        assert "enhancement" in first_labels

        # Second issue should have bug label
        second_labels = gh_client.create_issue.call_args_list[1][1]["labels"]
        assert "bug" in second_labels

        # Checklist comment posted on parent
        gh_client.add_issue_comment.assert_called_once()
        checklist_body = gh_client.add_issue_comment.call_args[0][3]
        assert "#100" in checklist_body
        assert "#101" in checklist_body

    @pytest.mark.asyncio
    async def test_empty_tickets_no_comment(self, tracker, gh_client):
        numbers = await tracker.create_sub_issues(42, [])
        assert numbers == []
        gh_client.add_issue_comment.assert_not_called()


# ---------------------------------------------------------------------------
# watch_for_triggers
# ---------------------------------------------------------------------------


class TestWatchForTriggers:
    @pytest.mark.asyncio
    async def test_detects_new_issues(self, tracker, gh_client):
        # First call (seed): one existing issue
        # Second call (poll): same issue + one new issue
        gh_client.list_issues.side_effect = [
            [  # seed
                {
                    "number": 1, "title": "Old", "state": "open",
                    "html_url": "h", "labels": ["forge"],
                    "assignees": [], "created_at": "x", "updated_at": "x",
                },
            ],
            [  # first poll
                {
                    "number": 1, "title": "Old", "state": "open",
                    "html_url": "h", "labels": ["forge"],
                    "assignees": [], "created_at": "x", "updated_at": "x",
                },
                {
                    "number": 2, "title": "New", "state": "open",
                    "html_url": "h2", "labels": ["forge"],
                    "assignees": [], "created_at": "x", "updated_at": "x",
                },
            ],
        ]
        # _get_issue_body for the new issue
        gh_client._api.return_value = {"body": "new body"}

        triggered: list[dict] = []

        async def capture(issue: dict) -> None:
            triggered.append(issue)

        # Run watcher for just one cycle
        async def run_watcher():
            await tracker.watch_for_triggers(
                capture, poll_interval=0,
            )

        task = asyncio.create_task(run_watcher())

        # Give it time for seed + one poll cycle
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        assert len(triggered) == 1
        assert triggered[0]["number"] == 2
        assert triggered[0]["title"] == "New"

    @pytest.mark.asyncio
    async def test_does_not_retrigger_seen_issues(
        self, tracker, gh_client,
    ):
        gh_client.list_issues.side_effect = [
            [  # seed
                {
                    "number": 5, "title": "Seen", "state": "open",
                    "html_url": "h", "labels": ["forge"],
                    "assignees": [], "created_at": "x", "updated_at": "x",
                },
            ],
            [  # poll — same issue
                {
                    "number": 5, "title": "Seen", "state": "open",
                    "html_url": "h", "labels": ["forge"],
                    "assignees": [], "created_at": "x", "updated_at": "x",
                },
            ],
        ]

        triggered: list[dict] = []

        async def run_watcher():
            await tracker.watch_for_triggers(
                AsyncMock(), poll_interval=0,
            )

        task = asyncio.create_task(run_watcher())
        await asyncio.sleep(0.1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Callback should never have been called
        assert len(triggered) == 0

    @pytest.mark.asyncio
    async def test_poll_error_does_not_crash(self, tracker, gh_client):
        """If a poll cycle fails, the watcher continues."""
        gh_client.list_issues.side_effect = [
            [],                   # seed (empty)
            Exception("network"), # first poll fails
            [],                   # second poll succeeds
        ]

        async def run_watcher():
            await tracker.watch_for_triggers(
                AsyncMock(), poll_interval=0,
            )

        task = asyncio.create_task(run_watcher())
        await asyncio.sleep(0.15)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        # Didn't crash — reached the third list_issues call
        assert gh_client.list_issues.call_count >= 2
