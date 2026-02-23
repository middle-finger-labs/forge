"""Linear issue tracker integration (stub).

Linear uses a GraphQL API (https://studio.apollographql.com/public/Linear-API).
Authentication is via a personal API key or OAuth2 token passed in the
``Authorization: <token>`` header.

This module mirrors the :class:`~integrations.issue_tracker.IssueTracker`
interface so the pipeline can swap between GitHub Issues and Linear
without changing calling code.

Future implementation notes:

- Install ``httpx`` (already a dependency) — no special SDK needed.
- POST all requests to ``https://api.linear.app/graphql``.
- Issues in Linear are called "Issue" with fields like ``title``,
  ``description`` (Markdown), ``state`` (workflow state), ``labels``,
  ``priority`` (0-4 int: none/urgent/high/medium/low).
- Linear has native sub-issue support via ``parent { id }``.
- Webhooks are preferred over polling (``watch_for_triggers``).
  Subscribe to ``Issue`` events with a label filter.

Environment variables (expected when implemented)::

    LINEAR_API_KEY           — personal or OAuth token
    LINEAR_TEAM_ID           — default team for issue creation
    LINEAR_FORGE_LABEL_ID    — label ID to filter forge-managed issues

Usage (future)::

    from integrations.linear_client import LinearTracker

    tracker = LinearTracker(api_key="lin_api_...", team_id="TEAM-1")
    spec = await tracker.get_issue_as_spec("LIN-42")
    issues = await tracker.get_issues_for_pipeline(limit=5)
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Coroutine
from typing import Any

logger = logging.getLogger(__name__)


class LinearTracker:
    """Linear issue tracker — same interface as IssueTracker.

    All methods raise :class:`NotImplementedError` until the full
    GraphQL integration is built.
    """

    def __init__(
        self,
        api_key: str | None = None,
        team_id: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._team_id = team_id

    async def get_issue_as_spec(self, issue_id: str) -> str:
        """Fetch a Linear issue and format it as a BA-ready business spec.

        Parameters
        ----------
        issue_id:
            Linear issue identifier (e.g. ``"LIN-42"``).
        """
        # GraphQL query:
        #   query { issue(id: $id) { title description labels { nodes { name } }
        #           comments { nodes { body user { name } } } } }
        raise NotImplementedError(
            "Linear integration not yet implemented. "
            "See module docstring for GraphQL API notes."
        )

    async def get_issues_for_pipeline(
        self,
        labels: list[str] | None = None,
        limit: int = 5,
    ) -> list[dict]:
        """Fetch open Linear issues for pipeline processing.

        Parameters
        ----------
        labels:
            Label names to filter by.
        limit:
            Max issues to return.
        """
        # GraphQL query:
        #   query { issues(filter: { labels: { name: { in: $labels } },
        #           state: { type: { in: ["started","unstarted","backlog"] } } },
        #           orderBy: priorityLabel, first: $limit)
        #           { nodes { id identifier title description priority
        #                     labels { nodes { name } }
        #                     assignee { name } } } }
        raise NotImplementedError(
            "Linear integration not yet implemented."
        )

    async def update_issue_status(
        self,
        issue_id: str,
        status: str,
        details: str = "",
    ) -> None:
        """Add a status comment to a Linear issue.

        Parameters
        ----------
        issue_id:
            Linear issue identifier.
        status:
            Status string (e.g. ``"Coding in progress"``).
        details:
            Optional details appended to the comment.
        """
        # GraphQL mutation:
        #   mutation { commentCreate(input: { issueId: $id, body: $body }) { ... } }
        raise NotImplementedError(
            "Linear integration not yet implemented."
        )

    async def create_sub_issues(
        self,
        parent_issue_id: str,
        tickets: list[dict],
    ) -> list[str]:
        """Create sub-issues in Linear for each PRD ticket.

        Parameters
        ----------
        parent_issue_id:
            The parent Linear issue identifier.
        tickets:
            List of PRDTicket-like dicts.

        Returns
        -------
        list[str]
            Linear issue identifiers of created sub-issues.
        """
        # GraphQL mutation:
        #   mutation { issueCreate(input: { teamId: $team, title: $title,
        #              description: $desc, parentId: $parent,
        #              labelIds: [$forgeLabel] }) { issue { id identifier } } }
        raise NotImplementedError(
            "Linear integration not yet implemented."
        )

    async def watch_for_triggers(
        self,
        callback: Callable[[dict], Coroutine[Any, Any, None]],
        *,
        labels: list[str] | None = None,
        poll_interval: int = 60,
    ) -> None:
        """Watch for new Linear issues matching labels.

        The preferred approach for Linear is webhooks rather than
        polling.  When implemented, this method should register a
        webhook subscription for ``Issue`` create events filtered by
        the forge label, then long-poll or run a small HTTP server to
        receive payloads.

        Parameters
        ----------
        callback:
            Async callable invoked with each new issue dict.
        labels:
            Label names to filter.
        poll_interval:
            Seconds between polls (fallback if webhooks unavailable).
        """
        # Option A (webhook):  POST to /webhooks with resourceTypes=["Issue"]
        # Option B (poll):     query issues(filter: { createdAt: { gte: $last } })
        raise NotImplementedError(
            "Linear integration not yet implemented. "
            "Prefer webhooks over polling for Linear."
        )
