"""Automatic connection actions triggered at pipeline lifecycle events.

These hooks run in addition to whatever agents do with tools directly.
They provide structured, predictable integrations (e.g. "always create
Linear tickets from PM output") that don't depend on the LLM deciding
to call a tool.

All hooks are best-effort — failures are logged but never block the
pipeline.  Each hook checks whether the relevant connection exists,
is enabled, and has the automation flag turned on before executing.

Usage::

    from connections.pipeline_hooks import get_pipeline_hooks

    hooks = get_pipeline_hooks()
    await hooks.on_pipeline_start(pipeline_id, org_id, spec)
    # ... pipeline stages run ...
    await hooks.on_stage_complete(pipeline_id, org_id, "business_analysis", output)
    await hooks.on_pipeline_complete(pipeline_id, org_id, result)
"""

from __future__ import annotations

import json
from typing import Any

import structlog

log = structlog.get_logger().bind(component="connections.pipeline_hooks")

# Default automation flags — all on by default
DEFAULT_AUTOMATION = {
    "auto_search_context": True,     # Search for context on pipeline start
    "auto_create_spec_page": True,   # Create Notion spec page after BA
    "auto_create_tickets": True,     # Create Linear/Jira tickets after PM
    "auto_update_tickets": True,     # Update ticket status on completion
    "auto_create_bug_tickets": True, # Create bug tickets from QA findings
}


class ConnectionPipelineHooks:
    """Automatic connection actions triggered at pipeline lifecycle events."""

    def __init__(self) -> None:
        self._manager = None
        self._registry = None

    def _get_manager(self):
        if self._manager is None:
            try:
                from connections.client_manager import get_client_manager
                self._manager = get_client_manager()
            except Exception:
                pass
        return self._manager

    def _get_registry(self):
        if self._registry is None:
            try:
                from connections.registry import ConnectionRegistry
                self._registry = ConnectionRegistry()
            except Exception:
                pass
        return self._registry

    async def _get_connections(self, org_id: str, service: str | None = None):
        """Get enabled connections for an org, optionally filtered by service."""
        registry = self._get_registry()
        if not registry:
            return []
        try:
            connections = await registry.list_connections(org_id)
            result = [c for c in connections if c.enabled]
            if service:
                result = [c for c in result if c.service.value == service]
            return result
        except Exception as exc:
            log.debug("failed to list connections", error=str(exc))
            return []

    def _get_automation(self, conn, key: str) -> bool:
        """Check if an automation flag is enabled for a connection."""
        automation = getattr(conn, "automation_config", None) or {}
        return automation.get(key, DEFAULT_AUTOMATION.get(key, True))

    async def _call_tool_safe(
        self,
        connection_id: str,
        tool_name: str,
        arguments: dict,
        *,
        org_id: str | None = None,
        pipeline_id: str | None = None,
        agent_role: str = "system",
    ) -> dict | None:
        """Call an MCP tool, returning None on failure."""
        manager = self._get_manager()
        if not manager:
            return None
        try:
            return await manager.call_tool(
                connection_id,
                tool_name,
                arguments,
                org_id=org_id,
                agent_role=agent_role,
                pipeline_id=pipeline_id,
            )
        except Exception as exc:
            log.warning(
                "hook tool call failed",
                connection_id=connection_id,
                tool_name=tool_name,
                error=str(exc),
            )
            return None

    async def _log_hook_event(
        self,
        pipeline_id: str,
        event_type: str,
        service: str,
        summary: str,
    ) -> None:
        """Stream a hook event to the pipeline log."""
        try:
            from memory.agent_log import stream_agent_log
            from connections.agent_tools import _SERVICE_ICONS

            icon = _SERVICE_ICONS.get(service, "\U0001f527")
            await stream_agent_log(
                pipeline_id,
                "mcp.hook",
                agent_role="system",
                payload={
                    "icon": icon,
                    "service": service,
                    "hook": event_type,
                    "summary": f"{icon} {summary}",
                },
            )
        except Exception:
            pass

    # ── Pipeline Start ────────────────────────────────────

    async def on_pipeline_start(
        self,
        pipeline_id: str,
        org_id: str,
        spec: str,
    ) -> dict[str, Any]:
        """Search connected services for context related to the spec.

        Returns a dict of context findings to attach to the BA's input.
        """
        context: dict[str, Any] = {"notion_pages": [], "related_tickets": []}

        # Search Notion for related docs
        notion_conns = await self._get_connections(org_id, "notion")
        for conn in notion_conns:
            if not self._get_automation(conn, "auto_search_context"):
                continue
            # Extract key terms from spec for search
            search_query = spec[:200].strip()
            result = await self._call_tool_safe(
                conn.id, "search", {"query": search_query},
                org_id=org_id, pipeline_id=pipeline_id,
            )
            if result and not result.get("is_error"):
                content = result.get("content", [])
                text = content[0].get("text", "") if content else ""
                if text:
                    context["notion_pages"].append({
                        "source": conn.display_name,
                        "content": text[:2000],
                    })
                    await self._log_hook_event(
                        pipeline_id, "pipeline_start",
                        "notion",
                        f"Searched {conn.display_name} for related docs",
                    )

        # Search Linear/Jira for related tickets
        for service in ("linear", "jira"):
            conns = await self._get_connections(org_id, service)
            for conn in conns:
                if not self._get_automation(conn, "auto_search_context"):
                    continue
                search_query = spec[:100].strip()
                result = await self._call_tool_safe(
                    conn.id, "search_issues",
                    {"query": search_query},
                    org_id=org_id, pipeline_id=pipeline_id,
                )
                if result and not result.get("is_error"):
                    content = result.get("content", [])
                    text = content[0].get("text", "") if content else ""
                    if text:
                        context["related_tickets"].append({
                            "source": f"{conn.display_name} ({service})",
                            "content": text[:2000],
                        })
                        await self._log_hook_event(
                            pipeline_id, "pipeline_start",
                            service,
                            f"Found related tickets in {conn.display_name}",
                        )

        return context

    # ── Stage Complete ────────────────────────────────────

    async def on_stage_complete(
        self,
        pipeline_id: str,
        org_id: str,
        stage: str,
        output: dict,
    ) -> None:
        """Run post-stage automation based on which stage completed."""
        if stage == "business_analysis":
            await self._on_ba_complete(pipeline_id, org_id, output)
        elif stage == "pm" or stage == "task_breakdown":
            await self._on_pm_complete(pipeline_id, org_id, output)
        elif stage == "qa_review":
            await self._on_qa_complete(pipeline_id, org_id, output)

    async def _on_ba_complete(
        self, pipeline_id: str, org_id: str, spec: dict,
    ) -> None:
        """After BA: create/update Notion spec page."""
        notion_conns = await self._get_connections(org_id, "notion")
        for conn in notion_conns:
            if not self._get_automation(conn, "auto_create_spec_page"):
                continue

            product_name = spec.get("product_name", "Unnamed Spec")
            vision = spec.get("product_vision", "")
            stories = spec.get("user_stories", [])

            # Build page content
            content_parts = [f"# {product_name}\n\n{vision}\n"]
            if stories:
                content_parts.append("\n## User Stories\n")
                for story in stories:
                    sid = story.get("id", "")
                    action = story.get("action", "")
                    content_parts.append(f"- **{sid}**: {action}")

            result = await self._call_tool_safe(
                conn.id, "create_page",
                {
                    "title": f"[Pipeline] {product_name}",
                    "content": "\n".join(content_parts),
                },
                org_id=org_id, pipeline_id=pipeline_id,
            )
            if result and not result.get("is_error"):
                await self._log_hook_event(
                    pipeline_id, "ba_complete",
                    "notion",
                    f"Created spec page '{product_name}' in {conn.display_name}",
                )

    async def _on_pm_complete(
        self, pipeline_id: str, org_id: str, board: dict,
    ) -> None:
        """After PM: create tickets in Linear/Jira."""
        tickets = board.get("tickets", [])
        if not tickets:
            return

        for service in ("linear", "jira"):
            conns = await self._get_connections(org_id, service)
            for conn in conns:
                if not self._get_automation(conn, "auto_create_tickets"):
                    continue

                created = 0
                for ticket in tickets:
                    title = ticket.get("title", "Untitled")
                    description = ticket.get("description", "")
                    ticket_key = ticket.get("ticket_key", "")
                    priority = ticket.get("priority", "medium")

                    result = await self._call_tool_safe(
                        conn.id, "create_issue",
                        {
                            "title": f"[{ticket_key}] {title}",
                            "description": description,
                            "priority": priority,
                        },
                        org_id=org_id, pipeline_id=pipeline_id,
                        agent_role="pm",
                    )
                    if result and not result.get("is_error"):
                        created += 1

                if created > 0:
                    await self._log_hook_event(
                        pipeline_id, "pm_complete",
                        service,
                        f"Created {created} ticket(s) in {conn.display_name}",
                    )

    async def _on_qa_complete(
        self, pipeline_id: str, org_id: str, review: dict,
    ) -> None:
        """After QA: create bug tickets for error/critical findings."""
        verdict = review.get("verdict", "")
        if verdict == "approved":
            return

        comments = review.get("comments", [])
        bugs = [c for c in comments if c.get("severity") in ("error", "critical")]
        if not bugs:
            return

        for service in ("linear", "jira"):
            conns = await self._get_connections(org_id, service)
            for conn in conns:
                if not self._get_automation(conn, "auto_create_bug_tickets"):
                    continue

                ticket_key = review.get("ticket_key", "")
                created = 0
                for bug in bugs:
                    file_path = bug.get("file_path", "")
                    line = bug.get("line", "")
                    comment = bug.get("comment", "")
                    severity = bug.get("severity", "error")

                    title = f"[QA/{ticket_key}] {comment[:80]}"
                    desc = (
                        f"**Found by QA review of {ticket_key}**\n\n"
                        f"File: `{file_path}`"
                        f"{f' (line {line})' if line else ''}\n"
                        f"Severity: {severity}\n\n"
                        f"{comment}"
                    )

                    result = await self._call_tool_safe(
                        conn.id, "create_issue",
                        {"title": title, "description": desc, "priority": "high"},
                        org_id=org_id, pipeline_id=pipeline_id,
                        agent_role="qa",
                    )
                    if result and not result.get("is_error"):
                        created += 1

                if created > 0:
                    await self._log_hook_event(
                        pipeline_id, "qa_complete",
                        service,
                        f"Created {created} bug ticket(s) in {conn.display_name}",
                    )

    # ── Pipeline Complete ─────────────────────────────────

    async def on_pipeline_complete(
        self,
        pipeline_id: str,
        org_id: str,
        result: dict,
    ) -> None:
        """Update tickets to Done and update Notion project status."""
        # Update Linear/Jira tickets
        for service in ("linear", "jira"):
            conns = await self._get_connections(org_id, service)
            for conn in conns:
                if not self._get_automation(conn, "auto_update_tickets"):
                    continue

                completed_tickets = result.get("completed_tickets", [])
                updated = 0
                for ticket_key in completed_tickets:
                    res = await self._call_tool_safe(
                        conn.id, "update_issue",
                        {"issue_id": ticket_key, "status": "done"},
                        org_id=org_id, pipeline_id=pipeline_id,
                    )
                    if res and not res.get("is_error"):
                        updated += 1

                if updated > 0:
                    await self._log_hook_event(
                        pipeline_id, "pipeline_complete",
                        service,
                        f"Marked {updated} ticket(s) as Done in {conn.display_name}",
                    )

        # Update Notion project page
        notion_conns = await self._get_connections(org_id, "notion")
        for conn in notion_conns:
            if not self._get_automation(conn, "auto_create_spec_page"):
                continue

            total_cost = result.get("total_cost_usd", 0.0)
            ticket_count = len(result.get("completed_tickets", []))

            await self._call_tool_safe(
                conn.id, "create_page",
                {
                    "title": f"[Pipeline Complete] {result.get('name', pipeline_id)}",
                    "content": (
                        f"Pipeline completed successfully.\n\n"
                        f"- Tickets: {ticket_count}\n"
                        f"- Cost: ${total_cost:.2f}\n"
                    ),
                },
                org_id=org_id, pipeline_id=pipeline_id,
            )
            await self._log_hook_event(
                pipeline_id, "pipeline_complete",
                "notion",
                f"Updated project status in {conn.display_name}",
            )

    # ── Pipeline Failure ──────────────────────────────────

    async def on_pipeline_failure(
        self,
        pipeline_id: str,
        org_id: str,
        error: dict,
    ) -> None:
        """Create a bug ticket and update Notion on pipeline failure."""
        error_msg = error.get("message", "Unknown error")
        stage = error.get("stage", "unknown")

        # Create bug ticket
        for service in ("linear", "jira"):
            conns = await self._get_connections(org_id, service)
            for conn in conns:
                if not self._get_automation(conn, "auto_create_bug_tickets"):
                    continue

                await self._call_tool_safe(
                    conn.id, "create_issue",
                    {
                        "title": f"[Pipeline Failed] Error in {stage}",
                        "description": (
                            f"Pipeline `{pipeline_id}` failed at stage `{stage}`.\n\n"
                            f"**Error:** {error_msg}\n\n"
                            f"**Details:**\n```\n{json.dumps(error, indent=2, default=str)[:1000]}\n```"
                        ),
                        "priority": "urgent",
                    },
                    org_id=org_id, pipeline_id=pipeline_id,
                )
                await self._log_hook_event(
                    pipeline_id, "pipeline_failure",
                    service,
                    f"Created failure ticket in {conn.display_name}",
                )

        # Update Notion
        notion_conns = await self._get_connections(org_id, "notion")
        for conn in notion_conns:
            if not self._get_automation(conn, "auto_create_spec_page"):
                continue

            await self._call_tool_safe(
                conn.id, "create_page",
                {
                    "title": f"[Pipeline BLOCKED] Error in {stage}",
                    "content": f"Pipeline failed at stage `{stage}`.\n\nError: {error_msg}",
                },
                org_id=org_id, pipeline_id=pipeline_id,
            )
            await self._log_hook_event(
                pipeline_id, "pipeline_failure",
                "notion",
                f"Updated project status to Blocked in {conn.display_name}",
            )


# Module-level singleton
_hooks: ConnectionPipelineHooks | None = None


def get_pipeline_hooks() -> ConnectionPipelineHooks:
    global _hooks  # noqa: PLW0603
    if _hooks is None:
        _hooks = ConnectionPipelineHooks()
    return _hooks
