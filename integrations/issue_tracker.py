"""Read GitHub Issues as pipeline input and report status back.

Converts GitHub Issues into business specs for the BA agent, tracks
pipeline progress via status comments, creates sub-issues for PRD
tickets, and polls for new "forge"-labelled issues to trigger runs
automatically.

Usage::

    from integrations.github_client import GitHubClient
    from integrations.issue_tracker import IssueTracker

    async with GitHubClient(identity) as gh:
        tracker = IssueTracker(gh, "DraftKings", "lottery")

        # Single issue → BA-ready spec
        spec = await tracker.get_issue_as_spec(42)

        # Batch fetch for pipeline
        issues = await tracker.get_issues_for_pipeline(labels=["forge"])

        # Report progress
        await tracker.update_issue_status(42, "Coding in progress")
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from integrations.github_client import GitHubClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Priority ordering (higher weight → processed first)
# ---------------------------------------------------------------------------

_PRIORITY_WEIGHT: dict[str, int] = {
    "critical": 40,
    "p0": 40,
    "urgent": 40,
    "high": 30,
    "p1": 30,
    "medium": 20,
    "p2": 20,
    "low": 10,
    "p3": 10,
}

# Maps issue labels to a semantic prefix the BA agent can understand.
_LABEL_CONTEXT: dict[str, str] = {
    "bug": "Bug fix",
    "fix": "Bug fix",
    "feature": "New feature request",
    "enhancement": "Enhancement to existing functionality",
    "refactor": "Code refactoring",
    "infrastructure": "Infrastructure / DevOps change",
    "documentation": "Documentation update",
    "security": "Security issue",
    "performance": "Performance improvement",
    "test": "Test coverage improvement",
}

# Status emoji + text pairs
_STATUS_EMOJI: dict[str, str] = {
    "Pipeline started": "\U0001f525",      # 🔥
    "Spec analysis complete": "\U0001f4cb", # 📋
    "Architecture approved": "\U0001f3d7",  # 🏗
    "Coding in progress": "\U0001f4bb",     # 💻
    "QA review": "\U0001f50d",              # 🔍
    "PR created": "\u2705",                 # ✅
    "Pipeline failed": "\u274c",            # ❌
}

_POLL_INTERVAL = 60  # seconds


# ---------------------------------------------------------------------------
# IssueTracker
# ---------------------------------------------------------------------------


class IssueTracker:
    """Reads GitHub Issues as pipeline input and writes status back."""

    def __init__(
        self,
        github_client: GitHubClient,
        owner: str,
        repo: str,
    ) -> None:
        self._gh = github_client
        self._owner = owner
        self._repo = repo

    # ------------------------------------------------------------------
    # get_issue_as_spec
    # ------------------------------------------------------------------

    async def get_issue_as_spec(self, issue_number: int) -> str:
        """Fetch an issue and format it as a BA-ready business spec.

        Includes the title, body, label context, and comment thread
        so the BA agent has full context when generating a ProductSpec.
        """
        issue = await self._gh._api(
            "GET",
            f"/repos/{self._owner}/{self._repo}/issues/{issue_number}",
        )

        title: str = issue.get("title", "")
        body: str = issue.get("body", "") or ""
        labels: list[str] = [
            lb["name"] for lb in issue.get("labels", [])
        ]

        # --- Build the spec string ---
        parts: list[str] = []

        # 1. Label-derived context line
        context_prefix = _label_context_line(labels)
        if context_prefix:
            parts.append(context_prefix)
            parts.append("")

        # 2. Title + body
        parts.append(f"# {title}")
        parts.append("")
        if body.strip():
            parts.append(body.strip())
            parts.append("")

        # 3. Labels as metadata
        if labels:
            parts.append(
                f"**Labels:** {', '.join(labels)}"
            )
            parts.append("")

        # 4. Comments (additional context / discussion)
        comments = await self._fetch_comments(issue_number)
        if comments:
            parts.append("## Additional Context (from discussion)")
            parts.append("")
            for comment in comments:
                author = comment.get("author", "unknown")
                comment_body = comment.get("body", "")
                if comment_body.strip():
                    parts.append(f"**{author}:**")
                    parts.append(comment_body.strip())
                    parts.append("")

        # 5. Source reference
        html_url = issue.get("html_url", "")
        parts.append(f"---\n*Source: GitHub Issue #{issue_number}*")
        if html_url:
            parts.append(f"*URL: {html_url}*")

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # get_issues_for_pipeline
    # ------------------------------------------------------------------

    async def get_issues_for_pipeline(
        self,
        labels: list[str] | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """Fetch open issues matching *labels*, sorted by priority.

        Parameters
        ----------
        labels:
            Filter labels.  Defaults to ``["forge"]``.
        limit:
            Maximum number of issues to return.

        Returns
        -------
        list[dict]
            Each dict has: ``number``, ``title``, ``body``, ``labels``,
            ``assignees``, ``priority_weight``, ``html_url``.
        """
        if labels is None:
            labels = ["forge"]

        raw_issues = await self._gh.list_issues(
            self._owner,
            self._repo,
            state="open",
            labels=labels,
            per_page=min(limit * 2, 100),  # over-fetch to account for PRs
        )

        enriched: list[dict] = []
        for issue in raw_issues:
            enriched.append({
                "number": issue["number"],
                "title": issue["title"],
                "body": await self._get_issue_body(issue["number"]),
                "labels": issue["labels"],
                "assignees": issue["assignees"],
                "priority_weight": _priority_weight(issue["labels"]),
                "html_url": issue["html_url"],
            })

        # Sort by priority descending, then by issue number ascending
        enriched.sort(
            key=lambda i: (-i["priority_weight"], i["number"]),
        )

        return enriched[:limit]

    # ------------------------------------------------------------------
    # update_issue_status
    # ------------------------------------------------------------------

    async def update_issue_status(
        self,
        issue_number: int,
        status: str,
        details: str = "",
    ) -> None:
        """Add a status comment to an issue.

        Parameters
        ----------
        issue_number:
            The GitHub issue to comment on.
        status:
            One of: ``"Pipeline started"``, ``"Spec analysis complete"``,
            ``"Architecture approved"``, ``"Coding in progress"``,
            ``"QA review"``, ``"PR created"``, ``"Pipeline failed"``.
        details:
            Optional extra information appended after the status line.
        """
        emoji = _STATUS_EMOJI.get(status, "\U0001f916")  # 🤖 default
        lines = [f"{emoji} **Forge: {status}**"]
        if details:
            lines.append("")
            lines.append(details)

        await self._gh.add_issue_comment(
            self._owner,
            self._repo,
            issue_number,
            "\n".join(lines),
        )
        logger.info(
            "Issue #%d status → %s", issue_number, status,
        )

    # ------------------------------------------------------------------
    # create_sub_issues
    # ------------------------------------------------------------------

    async def create_sub_issues(
        self,
        parent_issue: int,
        tickets: list[dict],
    ) -> list[int]:
        """Create a sub-issue for each PRD ticket.

        Each sub-issue body links back to the parent.  A checklist
        comment is also added to the parent issue summarising all
        created sub-issues.

        Parameters
        ----------
        parent_issue:
            The originating GitHub issue number.
        tickets:
            List of PRDTicket-like dicts, each with at least
            ``ticket_key``, ``title``, ``description``,
            ``acceptance_criteria``.

        Returns
        -------
        list[int]
            The issue numbers of the created sub-issues.
        """
        created: list[int] = []

        for ticket in tickets:
            key = ticket.get("ticket_key", "")
            title = f"[{key}] {ticket.get('title', 'Untitled')}"
            body = _format_sub_issue_body(ticket, parent_issue)
            labels = _ticket_type_labels(ticket)

            result = await self._gh.create_issue(
                self._owner,
                self._repo,
                title,
                body,
                labels=labels,
            )
            created.append(result["number"])
            logger.info(
                "Created sub-issue #%d for %s", result["number"], key,
            )

        # Add a checklist comment to the parent issue
        if created:
            checklist = _format_checklist(tickets, created)
            await self._gh.add_issue_comment(
                self._owner,
                self._repo,
                parent_issue,
                checklist,
            )

        return created

    # ------------------------------------------------------------------
    # watch_for_triggers
    # ------------------------------------------------------------------

    async def watch_for_triggers(
        self,
        callback: Callable[[dict], Coroutine[Any, Any, None]],
        *,
        labels: list[str] | None = None,
        poll_interval: int = _POLL_INTERVAL,
    ) -> None:
        """Poll for new ``forge``-labelled issues and invoke *callback*.

        Runs indefinitely.  Cancel the task to stop polling.

        Parameters
        ----------
        callback:
            Async callable receiving an issue dict (same shape as
            ``get_issues_for_pipeline`` items).
        labels:
            Labels to watch.  Defaults to ``["forge"]``.
        poll_interval:
            Seconds between polls.
        """
        if labels is None:
            labels = ["forge"]
        seen: set[int] = set()

        # Seed seen set with currently-open matching issues so we only
        # trigger on *new* issues created after the watcher starts.
        existing = await self._gh.list_issues(
            self._owner,
            self._repo,
            state="open",
            labels=labels,
            per_page=100,
        )
        for issue in existing:
            seen.add(issue["number"])

        logger.info(
            "Watching for new issues with labels=%s (seeded %d existing)",
            labels,
            len(seen),
        )

        while True:
            await asyncio.sleep(poll_interval)

            try:
                issues = await self._gh.list_issues(
                    self._owner,
                    self._repo,
                    state="open",
                    labels=labels,
                    per_page=100,
                )
            except Exception:
                logger.exception("Poll failed, will retry next cycle")
                continue

            for issue in issues:
                num = issue["number"]
                if num in seen:
                    continue
                seen.add(num)

                logger.info(
                    "New forge issue detected: #%d %s",
                    num,
                    issue["title"],
                )
                try:
                    enriched = {
                        **issue,
                        "body": await self._get_issue_body(num),
                        "priority_weight": _priority_weight(
                            issue["labels"],
                        ),
                    }
                    await callback(enriched)
                except Exception:
                    logger.exception(
                        "Callback failed for issue #%d", num,
                    )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _fetch_comments(
        self, issue_number: int,
    ) -> list[dict]:
        """Fetch all comments on an issue, returning simplified dicts."""
        data = await self._gh._api(
            "GET",
            f"/repos/{self._owner}/{self._repo}"
            f"/issues/{issue_number}/comments",
            params={"per_page": 50},
        )
        if not isinstance(data, list):
            return []
        return [
            {
                "author": c.get("user", {}).get("login", "unknown"),
                "body": c.get("body", ""),
                "created_at": c.get("created_at", ""),
            }
            for c in data
            if isinstance(c, dict) and not _is_bot_comment(c)
        ]

    async def _get_issue_body(self, issue_number: int) -> str:
        """Fetch full issue body (list_issues may truncate)."""
        data = await self._gh._api(
            "GET",
            f"/repos/{self._owner}/{self._repo}/issues/{issue_number}",
        )
        return data.get("body", "") or ""


# ---------------------------------------------------------------------------
# Helpers (pure functions)
# ---------------------------------------------------------------------------


def _label_context_line(labels: list[str]) -> str:
    """Produce a context sentence from issue labels for the BA agent."""
    for label in labels:
        lower = label.lower()
        for key, context in _LABEL_CONTEXT.items():
            if _label_matches(lower, key):
                return f"**Type:** {context}"
    return ""


def _label_matches(label: str, keyword: str) -> bool:
    """Check if *keyword* appears as a whole word in *label*.

    Splits on common separators (``-``, ``_``, ``/``, space) so that
    ``"fix"`` matches ``"bug-fix"`` but not ``"wontfix"``.
    """
    if label == keyword:
        return True
    parts = set(label.replace("-", " ").replace("_", " ").replace("/", " ").split())
    return keyword in parts


def _priority_weight(labels: list[str]) -> int:
    """Return the highest priority weight found in *labels*."""
    best = 0
    for label in labels:
        lower = label.lower()
        for keyword, weight in _PRIORITY_WEIGHT.items():
            if keyword in lower:
                best = max(best, weight)
    return best


def _is_bot_comment(comment: dict) -> bool:
    """Return True if the comment was posted by a bot or Forge itself."""
    user = comment.get("user", {})
    if user.get("type", "").lower() == "bot":
        return True
    body = comment.get("body", "")
    if body.startswith(("\U0001f525 **Forge:", "\u2705 **Forge:", "\u274c **Forge:")):
        return True
    return False


def _format_sub_issue_body(ticket: dict, parent_issue: int) -> str:
    """Format a PRD ticket as a GitHub issue body."""
    key = ticket.get("ticket_key", "")
    desc = ticket.get("description", "")
    criteria = ticket.get("acceptance_criteria", [])
    deps = ticket.get("dependencies", [])
    story_points = ticket.get("story_points", "")
    priority = ticket.get("priority", "")

    lines: list[str] = [
        f"> Part of #{parent_issue} | Forge ticket `{key}`",
        "",
    ]

    if priority:
        lines.append(f"**Priority:** {priority}")
    if story_points:
        lines.append(f"**Story points:** {story_points}")
    if priority or story_points:
        lines.append("")

    lines.append("## Description")
    lines.append("")
    lines.append(desc)
    lines.append("")

    if criteria:
        lines.append("## Acceptance Criteria")
        lines.append("")
        for ac in criteria:
            lines.append(f"- [ ] {ac}")
        lines.append("")

    if deps:
        lines.append(
            f"**Dependencies:** {', '.join(f'`{d}`' for d in deps)}"
        )
        lines.append("")

    lines.append(
        f"*Auto-created by Forge from #{parent_issue}*"
    )
    return "\n".join(lines)


def _ticket_type_labels(ticket: dict) -> list[str]:
    """Derive GitHub labels from a ticket's type and priority."""
    labels = ["forge-generated"]
    ticket_type = ticket.get("ticket_type", "").lower()
    if ticket_type in ("bug_fix", "bug"):
        labels.append("bug")
    elif ticket_type in ("feature",):
        labels.append("enhancement")
    elif ticket_type in ("infrastructure",):
        labels.append("infrastructure")
    elif ticket_type in ("test",):
        labels.append("test")
    elif ticket_type in ("documentation",):
        labels.append("documentation")
    return labels


def _format_checklist(
    tickets: list[dict], issue_numbers: list[int],
) -> str:
    """Build a Markdown checklist linking sub-issues to tickets."""
    lines = ["## Forge Sub-Issues", ""]
    for ticket, num in zip(tickets, issue_numbers):
        key = ticket.get("ticket_key", "?")
        title = ticket.get("title", "Untitled")
        lines.append(f"- [ ] #{num} — `{key}` {title}")
    return "\n".join(lines)
