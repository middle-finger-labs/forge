"""GitHub webhook receiver for Forge.

Provides a FastAPI router that handles GitHub webhook events to
automatically trigger and control pipelines:

- ``issues`` events  → start a pipeline when an issue is opened/labeled "forge"
- ``issue_comment`` events → /forge approve, /forge abort, /forge status
- ``pull_request_review`` events → (future) address review comments

Mount on the main API server::

    from integrations.webhook_server import webhook_router
    app.include_router(webhook_router)

**GitHub webhook setup:**

1. Go to repo **Settings → Webhooks → Add webhook**
2. Payload URL: ``https://{your-forge-host}/webhooks/github``
3. Content type: ``application/json``
4. Secret: value of ``GITHUB_WEBHOOK_SECRET`` env var
5. Events: *Issues*, *Issue comments*, *Pull request reviews*

For local development use `ngrok http 8000` or
`cloudflared tunnel --url http://localhost:8000` to expose the endpoint.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import uuid
from typing import Any

import structlog
from fastapi import APIRouter, Header, HTTPException, Request

log = structlog.get_logger().bind(component="webhook")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")
DASHBOARD_BASE_URL = os.environ.get(
    "FORGE_DASHBOARD_URL", "http://localhost:5173",
)

# Label that marks an issue as a Forge target
FORGE_LABEL = os.environ.get("FORGE_TRIGGER_LABEL", "forge")

# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

webhook_router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# ---------------------------------------------------------------------------
# In-memory issue → pipeline mapping
# ---------------------------------------------------------------------------

# Maps "owner/repo#issue_number" → pipeline_id.  Populated when a pipeline
# is started from a webhook event so that subsequent /forge commands on the
# same issue can locate the workflow.
_issue_pipeline_map: dict[str, str] = {}


def _issue_key(owner: str, repo: str, issue_number: int) -> str:
    return f"{owner}/{repo}#{issue_number}"


def get_pipeline_for_issue(
    owner: str, repo: str, issue_number: int,
) -> str | None:
    """Look up the pipeline_id for a tracked issue."""
    return _issue_pipeline_map.get(_issue_key(owner, repo, issue_number))


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


def _verify_signature(payload: bytes, signature_header: str | None) -> None:
    """Verify the GitHub HMAC-SHA256 webhook signature.

    Raises ``HTTPException(403)`` if the signature is missing or invalid.
    Silently passes if ``GITHUB_WEBHOOK_SECRET`` is not configured (dev mode).
    """
    if not WEBHOOK_SECRET:
        log.debug("webhook signature check skipped — GITHUB_WEBHOOK_SECRET not set")
        return

    if not signature_header:
        raise HTTPException(status_code=403, detail="Missing X-Hub-Signature-256 header")

    # Header format: "sha256=<hex>"
    if not signature_header.startswith("sha256="):
        raise HTTPException(status_code=403, detail="Malformed signature header")

    expected = hmac.new(
        WEBHOOK_SECRET.encode(), payload, hashlib.sha256,
    ).hexdigest()
    received = signature_header[7:]  # strip "sha256="

    if not hmac.compare_digest(expected, received):
        raise HTTPException(status_code=403, detail="Invalid webhook signature")


# ---------------------------------------------------------------------------
# Temporal helpers  (lazy imports to avoid circular deps at module load)
# ---------------------------------------------------------------------------


def _get_temporal():  # noqa: ANN202
    """Return the shared Temporal client from the API server."""
    from api.server import _get_temporal

    return _get_temporal()


async def _get_db():  # noqa: ANN202
    from api.server import _get_db

    return _get_db()


# ---------------------------------------------------------------------------
# Issue events
# ---------------------------------------------------------------------------

_COMMENT_APPROVE_RE = re.compile(
    r"/forge\s+approve\s+(\S+)", re.IGNORECASE,
)
_COMMENT_ABORT_RE = re.compile(r"/forge\s+abort", re.IGNORECASE)
_COMMENT_STATUS_RE = re.compile(r"/forge\s+status", re.IGNORECASE)


def _has_forge_label(labels: list[dict[str, Any]]) -> bool:
    """Check whether any label matches the forge trigger label."""
    return any(
        lbl.get("name", "").lower() == FORGE_LABEL.lower() for lbl in labels
    )


async def _start_pipeline_from_issue(payload: dict[str, Any]) -> dict[str, Any]:
    """Start a new Forge pipeline from a GitHub issue event."""
    issue = payload["issue"]
    repo = payload["repository"]

    owner = repo["owner"]["login"]
    repo_name = repo["name"]
    repo_url = repo.get("clone_url") or repo.get("html_url", "")
    issue_number = issue["number"]
    issue_title = issue.get("title", "")
    issue_body = issue.get("body") or ""

    # Build business spec from the issue
    business_spec = (
        f"# {issue_title}\n\n"
        f"{issue_body}\n\n"
        f"---\n"
        f"Source: {owner}/{repo_name}#{issue_number}"
    )

    # Check if already tracked
    key = _issue_key(owner, repo_name, issue_number)
    if key in _issue_pipeline_map:
        existing = _issue_pipeline_map[key]
        log.info(
            "issue already tracked — skipping duplicate",
            issue=key,
            pipeline_id=existing,
        )
        return {"action": "skipped", "pipeline_id": existing, "reason": "already tracked"}

    pipeline_id = uuid.uuid4().hex[:12]
    wf_id = f"forge-pipeline-{pipeline_id}"

    from workflows.pipeline import PIPELINE_QUEUE, ForgePipeline
    from workflows.types import PipelineInput

    pipeline_input = PipelineInput(
        pipeline_id=pipeline_id,
        business_spec=business_spec,
        project_name=repo_name,
        repo_url=repo_url,
        repo_owner=owner,
        repo_name=repo_name,
        issue_number=issue_number,
        pr_strategy="single_pr",
    )

    client = _get_temporal()
    await client.start_workflow(
        ForgePipeline.run,
        pipeline_input,
        id=wf_id,
        task_queue=PIPELINE_QUEUE,
    )

    # Track the mapping
    _issue_pipeline_map[key] = pipeline_id

    log.info(
        "pipeline started from issue",
        pipeline_id=pipeline_id,
        issue=key,
        workflow_id=wf_id,
    )

    # Insert initial DB record (best-effort)
    try:
        pool = await _get_db()
        await pool.execute(
            """
            INSERT INTO pipeline_runs (pipeline_id, status, current_stage,
                                       business_spec, project_name)
            VALUES ($1, $2, $3, $4, $5)
            """,
            pipeline_id,
            "running",
            "intake",
            business_spec,
            repo_name,
        )
    except Exception as exc:
        log.warning("failed to insert pipeline_runs row", error=str(exc))

    # Comment on the issue (best-effort)
    try:
        from integrations.git_identity import GitIdentityManager
        from integrations.github_client import GitHubClient

        mgr = GitIdentityManager()
        identity = mgr.resolve_identity(repo_url)
        async with GitHubClient(identity) as gh:
            dashboard_url = f"{DASHBOARD_BASE_URL}/pipeline/{pipeline_id}"
            await gh.add_issue_comment(
                owner,
                repo_name,
                issue_number,
                (
                    f"\U0001f525 **Forge pipeline started.**\n\n"
                    f"Tracking: {dashboard_url}\n\n"
                    f"Pipeline ID: `{pipeline_id}`\n\n"
                    f"Use `/forge status` to check progress, "
                    f"`/forge approve <stage>` to approve, "
                    f"or `/forge abort` to cancel."
                ),
            )
    except Exception as exc:
        log.warning("failed to comment on issue", error=str(exc))

    return {
        "action": "pipeline_started",
        "pipeline_id": pipeline_id,
        "workflow_id": wf_id,
    }


async def _handle_issues_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Handle ``issues`` webhook events."""
    action = payload.get("action", "")
    issue = payload.get("issue", {})
    labels = issue.get("labels", [])

    wh_log = log.bind(
        event="issues",
        action=action,
        issue=issue.get("number"),
    )

    # Trigger on: issue opened with forge label, or forge label added
    if action == "opened" and _has_forge_label(labels):
        wh_log.info("issue opened with forge label — starting pipeline")
        return await _start_pipeline_from_issue(payload)

    if action == "labeled":
        label_added = payload.get("label", {})
        if label_added.get("name", "").lower() == FORGE_LABEL.lower():
            wh_log.info("forge label added to issue — starting pipeline")
            return await _start_pipeline_from_issue(payload)

    wh_log.debug("ignoring issues event", action=action)
    return {"action": "ignored", "reason": f"unhandled issues action: {action}"}


# ---------------------------------------------------------------------------
# Issue comment events
# ---------------------------------------------------------------------------


async def _handle_issue_comment_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Handle ``issue_comment`` webhook events.

    Recognises slash commands in comments on forge-tracked issues:
    - ``/forge approve <stage>``
    - ``/forge abort``
    - ``/forge status``
    """
    action = payload.get("action", "")
    if action != "created":
        return {"action": "ignored", "reason": f"comment action={action}"}

    comment = payload.get("comment", {})
    body = comment.get("body", "")
    issue = payload.get("issue", {})
    repo = payload.get("repository", {})

    owner = repo.get("owner", {}).get("login", "")
    repo_name = repo.get("name", "")
    issue_number = issue.get("number", 0)
    commenter = comment.get("user", {}).get("login", "")

    wh_log = log.bind(
        event="issue_comment",
        issue=f"{owner}/{repo_name}#{issue_number}",
        commenter=commenter,
    )

    # Find tracked pipeline
    pipeline_id = get_pipeline_for_issue(owner, repo_name, issue_number)

    # --- /forge approve <stage> ---
    m = _COMMENT_APPROVE_RE.search(body)
    if m:
        stage_str = m.group(1)
        if not pipeline_id:
            wh_log.info("approve command but no tracked pipeline")
            return {"action": "ignored", "reason": "no tracked pipeline for approve"}

        from workflows.pipeline import ForgePipeline
        from workflows.types import ApprovalStatus, HumanApproval, PipelineStage

        try:
            stage = PipelineStage(stage_str)
        except ValueError:
            wh_log.warning("invalid stage in approve command", stage=stage_str)
            return {"action": "error", "reason": f"invalid stage: {stage_str}"}

        client = _get_temporal()
        wf_id = f"forge-pipeline-{pipeline_id}"
        handle = client.get_workflow_handle(wf_id)

        try:
            await handle.signal(
                ForgePipeline.human_approval,
                HumanApproval(
                    stage=stage,
                    status=ApprovalStatus.APPROVED,
                    notes=f"Approved via GitHub comment by @{commenter}",
                    approved_by=commenter,
                ),
            )
        except Exception as exc:
            wh_log.error("failed to send approval signal", error=str(exc))
            return {"action": "error", "reason": f"signal failed: {exc}"}

        wh_log.info("approval sent via comment", stage=stage_str)
        return {
            "action": "approved",
            "pipeline_id": pipeline_id,
            "stage": stage_str,
        }

    # --- /forge abort ---
    if _COMMENT_ABORT_RE.search(body):
        if not pipeline_id:
            wh_log.info("abort command but no tracked pipeline")
            return {"action": "ignored", "reason": "no tracked pipeline for abort"}

        from workflows.pipeline import ForgePipeline

        client = _get_temporal()
        wf_id = f"forge-pipeline-{pipeline_id}"
        handle = client.get_workflow_handle(wf_id)

        try:
            await handle.signal(
                ForgePipeline.abort,
                f"Aborted via GitHub comment by @{commenter}",
            )
        except Exception as exc:
            wh_log.error("failed to send abort signal", error=str(exc))
            return {"action": "error", "reason": f"signal failed: {exc}"}

        wh_log.info("abort sent via comment")
        return {"action": "aborted", "pipeline_id": pipeline_id}

    # --- /forge status ---
    if _COMMENT_STATUS_RE.search(body):
        if not pipeline_id:
            wh_log.info("status command but no tracked pipeline")
            return {"action": "ignored", "reason": "no tracked pipeline for status"}

        from workflows.pipeline import ForgePipeline

        client = _get_temporal()
        wf_id = f"forge-pipeline-{pipeline_id}"
        handle = client.get_workflow_handle(wf_id)

        try:
            state = await handle.query(ForgePipeline.get_state)
        except Exception as exc:
            wh_log.error("failed to query workflow state", error=str(exc))
            return {"action": "error", "reason": f"query failed: {exc}"}

        # Post status as a reply (best-effort)
        try:
            from integrations.git_identity import GitIdentityManager
            from integrations.github_client import GitHubClient

            repo_url = repo.get("clone_url", "")
            mgr = GitIdentityManager()
            identity = mgr.resolve_identity(repo_url)

            stage = state.get("current_stage", "unknown")
            cost = state.get("total_cost_usd", 0.0)
            aborted = state.get("aborted", False)
            pending = state.get("pending_approval")
            dashboard_url = f"{DASHBOARD_BASE_URL}/pipeline/{pipeline_id}"

            status_lines = [
                f"**Forge Pipeline Status** — `{pipeline_id}`\n",
                "| Field | Value |",
                "|-------|-------|",
                f"| Stage | `{stage}` |",
                f"| Cost | ${cost:.4f} |",
                f"| Aborted | {'Yes' if aborted else 'No'} |",
            ]
            if pending:
                status_lines.append(f"| Pending Approval | `{pending}` |")
            status_lines.append(f"\n[Dashboard]({dashboard_url})")

            async with GitHubClient(identity) as gh:
                await gh.add_issue_comment(
                    owner, repo_name, issue_number,
                    "\n".join(status_lines),
                )
        except Exception as exc:
            wh_log.warning("failed to post status comment", error=str(exc))

        wh_log.info("status queried via comment", stage=state.get("current_stage"))
        return {"action": "status", "pipeline_id": pipeline_id, "state": state}

    wh_log.debug("no forge command found in comment")
    return {"action": "ignored", "reason": "no /forge command in comment"}


# ---------------------------------------------------------------------------
# Pull request review events (future)
# ---------------------------------------------------------------------------


async def _handle_pr_review_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Handle ``pull_request_review`` webhook events.

    Placeholder for future implementation: when a forge-generated PR receives
    review comments, the QA agent could be triggered to address them.
    """
    log.debug(
        "pull_request_review event received (not yet implemented)",
        action=payload.get("action"),
        pr=payload.get("pull_request", {}).get("number"),
    )
    return {"action": "ignored", "reason": "pull_request_review not yet implemented"}


# ---------------------------------------------------------------------------
# Main endpoint
# ---------------------------------------------------------------------------

_EVENT_HANDLERS: dict[str, Any] = {
    "issues": _handle_issues_event,
    "issue_comment": _handle_issue_comment_event,
    "pull_request_review": _handle_pr_review_event,
}


@webhook_router.post("/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: str | None = Header(None),
    x_github_event: str | None = Header(None),
    x_github_delivery: str | None = Header(None),
):
    """Receive and process a GitHub webhook event.

    Verifies the HMAC-SHA256 signature, then dispatches to the appropriate
    handler based on the ``X-GitHub-Event`` header.
    """
    body = await request.body()
    _verify_signature(body, x_hub_signature_256)

    payload = await request.json()
    event_type = x_github_event or ""
    delivery_id = x_github_delivery or ""

    wh_log = log.bind(
        event=event_type,
        delivery=delivery_id,
    )
    wh_log.info("webhook received")

    handler = _EVENT_HANDLERS.get(event_type)
    if handler is None:
        wh_log.debug("unhandled event type")
        return {"status": "ignored", "event": event_type}

    try:
        result = await handler(payload)
    except HTTPException:
        raise
    except Exception as exc:
        wh_log.error("webhook handler failed", error=str(exc))
        raise HTTPException(status_code=500, detail=f"Handler error: {exc}") from exc

    return {"status": "ok", "event": event_type, "delivery": delivery_id, **result}
