"""Conversation API routes for the desktop app's Slack-like interface.

Provides REST endpoints for listing conversations, paginated message
retrieval, sending messages, and agent DM interactions.

Usage::

    from api.routes.conversations import conversations_router
    app.include_router(conversations_router)
"""

from __future__ import annotations

import json
import uuid

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from auth.middleware import get_current_user
from auth.types import ForgeUser

log = structlog.get_logger().bind(component="api.conversations")

conversations_router = APIRouter(prefix="/api", tags=["conversations"])

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# Agent roles that get auto-created DM conversations per org
AGENT_ROLES = (
    "product_manager",
    "research_analyst",
    "architect",
    "ticket_manager",
    "developer",
    "qa_engineer",
    "cto",
)

# Display names for agent roles (matches desktop app's AGENT_REGISTRY)
AGENT_DISPLAY_NAMES: dict[str, str] = {
    "product_manager": "Business Analyst",
    "research_analyst": "Researcher",
    "architect": "Architect",
    "ticket_manager": "PM",
    "developer": "Engineer",
    "qa_engineer": "QA",
    "cto": "CTO",
}


def _get_db() -> asyncpg.Pool:
    """Reuse the pool from the main server module."""
    from api.server import _get_db
    return _get_db()


def _get_redis():
    """Reuse Redis from the main server module."""
    from api.server import _get_redis
    return _get_redis()


def _row_to_dict(row: asyncpg.Record) -> dict:
    """Convert an asyncpg Record to a JSON-safe dict."""
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, uuid.UUID):
            d[k] = str(v)
        elif hasattr(v, "isoformat"):
            d[k] = v.isoformat()
    return d


# ---------------------------------------------------------------------------
# Auto-create agent DM conversations for an org
# ---------------------------------------------------------------------------


async def ensure_agent_dms(org_id: str) -> None:
    """Create agent DM conversations for the org if they don't exist yet.

    Uses INSERT ... ON CONFLICT DO NOTHING so this is safe to call
    multiple times.
    """
    pool = _get_db()
    for role in AGENT_ROLES:
        display_name = AGENT_DISPLAY_NAMES.get(role, role)
        try:
            await pool.execute(
                """
                INSERT INTO conversations (org_id, type, title, agent_role)
                VALUES ($1, 'agent_dm', $2, $3)
                ON CONFLICT (org_id, agent_role) DO NOTHING
                """,
                org_id,
                display_name,
                role,
            )
        except asyncpg.UndefinedTableError:
            log.warning("conversations table not yet created")
            return


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class SendMessageRequest(BaseModel):
    """Request body for sending a message to a conversation."""

    content: list[dict]  # Array of content blocks
    thread_id: str | None = None


class AgentDmRequest(BaseModel):
    """Request body for sending a DM to a specific agent."""

    message: str


# ---------------------------------------------------------------------------
# GET /api/conversations — list conversations
# ---------------------------------------------------------------------------


@conversations_router.get("/conversations")
async def list_conversations(user: ForgeUser = Depends(get_current_user)):
    """List all conversations for the user's org, ordered by last activity."""
    pool = _get_db()

    # Ensure agent DM conversations exist
    await ensure_agent_dms(user.org_id)

    try:
        rows = await pool.fetch(
            """
            SELECT c.id, c.org_id, c.type, c.title, c.agent_role,
                   c.pipeline_id, c.created_at, c.updated_at,
                   (
                       SELECT row_to_json(m.*)
                       FROM messages m
                       WHERE m.conversation_id = c.id
                       ORDER BY m.created_at DESC
                       LIMIT 1
                   ) AS last_message
            FROM conversations c
            WHERE c.org_id = $1
            ORDER BY c.updated_at DESC
            """,
            user.org_id,
        )
    except asyncpg.UndefinedTableError:
        return []

    results = []
    for row in rows:
        d = _row_to_dict(row)
        # Parse the last_message JSON sub-select
        lm = d.get("last_message")
        if isinstance(lm, str):
            try:
                d["last_message"] = json.loads(lm)
            except (json.JSONDecodeError, TypeError):
                pass
        results.append(d)

    return results


# ---------------------------------------------------------------------------
# GET /api/conversations/{conversation_id}/messages — paginated messages
# ---------------------------------------------------------------------------


@conversations_router.get("/conversations/{conversation_id}/messages")
async def get_messages(
    conversation_id: str,
    cursor: str | None = Query(None, description="ISO timestamp cursor for pagination"),
    limit: int = Query(50, ge=1, le=200),
    user: ForgeUser = Depends(get_current_user),
):
    """Get paginated messages for a conversation, oldest first.

    Returns ``{messages: [...], next_cursor: "..." | null}``.
    Pass ``cursor`` (an ISO timestamp) to load older messages.
    """
    pool = _get_db()

    # Verify conversation belongs to org
    try:
        conv = await pool.fetchrow(
            "SELECT id FROM conversations WHERE id = $1::uuid AND org_id = $2",
            conversation_id,
            user.org_id,
        )
    except asyncpg.UndefinedTableError:
        raise HTTPException(status_code=404, detail="Conversation not found")

    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    try:
        if cursor:
            rows = await pool.fetch(
                """
                SELECT id, conversation_id, org_id, author_type, author_id,
                       author_name, content, thread_id, created_at
                FROM messages
                WHERE conversation_id = $1::uuid
                  AND created_at < $2::timestamptz
                ORDER BY created_at DESC
                LIMIT $3
                """,
                conversation_id,
                cursor,
                limit + 1,  # fetch one extra to determine if there's a next page
            )
        else:
            rows = await pool.fetch(
                """
                SELECT id, conversation_id, org_id, author_type, author_id,
                       author_name, content, thread_id, created_at
                FROM messages
                WHERE conversation_id = $1::uuid
                ORDER BY created_at DESC
                LIMIT $2
                """,
                conversation_id,
                limit + 1,
            )
    except asyncpg.UndefinedTableError:
        return {"messages": [], "next_cursor": None}

    has_more = len(rows) > limit
    if has_more:
        rows = rows[:limit]

    # Reverse so messages are oldest-first
    messages = [_row_to_dict(r) for r in reversed(rows)]

    # Parse JSONB content blocks
    for msg in messages:
        if isinstance(msg.get("content"), str):
            try:
                msg["content"] = json.loads(msg["content"])
            except (json.JSONDecodeError, TypeError):
                pass

    next_cursor = messages[0]["created_at"] if has_more and messages else None

    return {"messages": messages, "next_cursor": next_cursor}


# ---------------------------------------------------------------------------
# POST /api/conversations/{conversation_id}/messages — send a message
# ---------------------------------------------------------------------------


@conversations_router.post("/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: str,
    body: SendMessageRequest,
    user: ForgeUser = Depends(get_current_user),
):
    """Send a message to a conversation. Persists and broadcasts via Redis."""
    pool = _get_db()

    # Verify conversation belongs to org
    conv = await pool.fetchrow(
        "SELECT id, type, agent_role FROM conversations WHERE id = $1::uuid AND org_id = $2",
        conversation_id,
        user.org_id,
    )
    if conv is None:
        raise HTTPException(status_code=404, detail="Conversation not found")

    content_json = json.dumps(body.content, default=str)

    row = await pool.fetchrow(
        """
        INSERT INTO messages (conversation_id, org_id, author_type, author_id,
                              author_name, content, thread_id)
        VALUES ($1::uuid, $2, 'user', $3, $4, $5::jsonb, $6::uuid)
        RETURNING id, conversation_id, org_id, author_type, author_id,
                  author_name, content, thread_id, created_at
        """,
        conversation_id,
        user.org_id,
        user.user_id,
        user.name,
        content_json,
        body.thread_id,
    )

    msg = _row_to_dict(row)

    # Broadcast to WebSocket subscribers via Redis
    try:
        r = _get_redis()
        await r.publish(
            f"forge:conv:{conversation_id}",
            json.dumps({"type": "message", "payload": msg}, default=str),
        )
    except Exception:
        pass  # Non-critical — REST response confirms persistence

    # If this is an agent DM, trigger async agent invocation
    if conv["type"] == "agent_dm" and conv["agent_role"]:
        await _trigger_agent_response(
            conversation_id=str(conv["id"]),
            org_id=user.org_id,
            agent_role=conv["agent_role"],
            user_message=body.content,
        )

    return msg


# ---------------------------------------------------------------------------
# POST /api/agents/{role}/message — send DM to agent
# ---------------------------------------------------------------------------


@conversations_router.post("/agents/{role}/message")
async def send_agent_dm(
    role: str,
    body: AgentDmRequest,
    user: ForgeUser = Depends(get_current_user),
):
    """Send a direct message to a specific agent.

    Auto-creates the DM conversation if it doesn't exist. Returns the
    persisted user message. The agent response arrives asynchronously
    via WebSocket.
    """
    if role not in AGENT_ROLES:
        raise HTTPException(status_code=400, detail=f"Unknown agent role: {role}")

    pool = _get_db()

    # Ensure DM conversation exists
    await ensure_agent_dms(user.org_id)

    # Find the DM conversation
    conv = await pool.fetchrow(
        """
        SELECT id FROM conversations
        WHERE org_id = $1 AND type = 'agent_dm' AND agent_role = $2
        """,
        user.org_id,
        role,
    )
    if conv is None:
        raise HTTPException(status_code=500, detail="Failed to create agent DM")

    conversation_id = str(conv["id"])

    # Persist the user's message
    content = [{"type": "text", "text": body.message}]
    content_json = json.dumps(content, default=str)

    row = await pool.fetchrow(
        """
        INSERT INTO messages (conversation_id, org_id, author_type, author_id,
                              author_name, content)
        VALUES ($1::uuid, $2, 'user', $3, $4, $5::jsonb)
        RETURNING id, conversation_id, org_id, author_type, author_id,
                  author_name, content, thread_id, created_at
        """,
        conversation_id,
        user.org_id,
        user.user_id,
        user.name,
        content_json,
    )

    msg = _row_to_dict(row)

    # Broadcast via Redis
    try:
        r = _get_redis()
        await r.publish(
            f"forge:conv:{conversation_id}",
            json.dumps({"type": "message", "payload": msg}, default=str),
        )
    except Exception:
        pass

    # Trigger async agent response
    await _trigger_agent_response(
        conversation_id=conversation_id,
        org_id=user.org_id,
        agent_role=role,
        user_message=content,
    )

    return msg


# ---------------------------------------------------------------------------
# GET /api/agents/status — get all agent statuses
# ---------------------------------------------------------------------------


@conversations_router.get("/agents/status")
async def get_agent_statuses(user: ForgeUser = Depends(get_current_user)):
    """Return current status of all agents for the user's org.

    Agent status is tracked in Redis for real-time updates. Falls back
    to a default 'idle' status if no data exists.
    """
    try:
        r = _get_redis()
        statuses = []
        for role in AGENT_ROLES:
            raw = await r.get(f"forge:agent_status:{user.org_id}:{role}")
            if raw:
                status_data = json.loads(raw)
            else:
                status_data = {
                    "role": role,
                    "displayName": AGENT_DISPLAY_NAMES.get(role, role),
                    "status": "idle",
                }
            statuses.append(status_data)
        return statuses
    except Exception:
        # Fallback: return all agents as idle
        return [
            {
                "role": role,
                "displayName": AGENT_DISPLAY_NAMES.get(role, role),
                "status": "idle",
            }
            for role in AGENT_ROLES
        ]


# ---------------------------------------------------------------------------
# Async agent invocation
# ---------------------------------------------------------------------------


async def _trigger_agent_response(
    conversation_id: str,
    org_id: str,
    agent_role: str,
    user_message: list[dict],
) -> None:
    """Trigger an asynchronous agent response via a background task.

    The agent processes the user's message and posts its response back
    to the conversation. The response is broadcast to WebSocket
    subscribers in real-time.

    This uses asyncio.create_task for fire-and-forget invocation. In
    production, this could be backed by Temporal for reliability.
    """
    import asyncio

    asyncio.create_task(
        _run_agent_response(conversation_id, org_id, agent_role, user_message)
    )


async def _run_agent_response(
    conversation_id: str,
    org_id: str,
    agent_role: str,
    user_message: list[dict],
) -> None:
    """Execute the agent and post its response to the conversation."""
    pool = _get_db()

    # Update agent status to 'working'
    await _set_agent_status(org_id, agent_role, "working", "Processing message...")

    try:
        # Extract text from content blocks for the agent prompt
        prompt_parts = []
        for block in user_message:
            if isinstance(block, dict) and block.get("type") == "text":
                prompt_parts.append(block["text"])
        prompt = "\n".join(prompt_parts) if prompt_parts else str(user_message)

        # Invoke the LangGraph agent
        try:
            from agents.langgraph_runner import run_agent
            from pydantic import BaseModel as _BM

            class _DmResponse(_BM):
                """Simple response schema for agent DM conversations."""
                response: str

            system_prompt = (
                f"You are the {AGENT_DISPLAY_NAMES.get(agent_role, agent_role)} agent "
                f"in the Forge software engineering pipeline. Respond helpfully and "
                f"concisely to the user's message. Use markdown formatting."
            )

            result, _cost = await run_agent(
                system_prompt=system_prompt,
                human_prompt=prompt,
                output_model=_DmResponse,
                agent_role=agent_role,
            )
            response_text = result["response"] if result and "response" in result else str(result)
        except ImportError:
            # LangGraph not available — return a placeholder
            display_name = AGENT_DISPLAY_NAMES.get(agent_role, agent_role)
            response_text = (
                f"*{display_name}* received your message. "
                f"Agent invocation will be available when the LangGraph runner is connected."
            )
        except Exception as exc:
            log.error(
                "agent invocation failed",
                agent_role=agent_role,
                error=str(exc),
            )
            response_text = f"I encountered an error processing your request: {exc}"

        # Persist the agent's response
        content = [{"type": "markdown", "markdown": response_text}]
        content_json = json.dumps(content, default=str)
        display_name = AGENT_DISPLAY_NAMES.get(agent_role, agent_role)

        row = await pool.fetchrow(
            """
            INSERT INTO messages (conversation_id, org_id, author_type, author_id,
                                  author_name, content)
            VALUES ($1::uuid, $2, 'agent', $3, $4, $5::jsonb)
            RETURNING id, conversation_id, org_id, author_type, author_id,
                      author_name, content, thread_id, created_at
            """,
            conversation_id,
            org_id,
            agent_role,
            display_name,
            content_json,
        )

        msg = _row_to_dict(row)

        # Broadcast agent response via Redis
        try:
            r = _get_redis()
            await r.publish(
                f"forge:conv:{conversation_id}",
                json.dumps({"type": "message", "payload": msg}, default=str),
            )
        except Exception:
            pass

    finally:
        # Reset agent status to idle
        await _set_agent_status(org_id, agent_role, "idle")


async def _set_agent_status(
    org_id: str,
    agent_role: str,
    status: str,
    current_task: str | None = None,
) -> None:
    """Update agent status in Redis and broadcast to WebSocket subscribers."""
    import datetime

    display_name = AGENT_DISPLAY_NAMES.get(agent_role, agent_role)
    status_data = {
        "role": agent_role,
        "displayName": display_name,
        "status": status,
        "currentTask": current_task,
        "lastActive": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    }

    try:
        r = _get_redis()
        # Persist in Redis
        await r.set(
            f"forge:agent_status:{org_id}:{agent_role}",
            json.dumps(status_data, default=str),
            ex=3600,  # 1 hour TTL
        )
        # Broadcast status change to all connected clients
        await r.publish(
            f"forge:org:{org_id}:events",
            json.dumps({"type": "agent_status", "payload": status_data}, default=str),
        )
    except Exception as exc:
        log.warning("failed to update agent status", error=str(exc))


# ---------------------------------------------------------------------------
# Pipeline conversation helper
# ---------------------------------------------------------------------------


async def ensure_pipeline_conversation(
    org_id: str,
    pipeline_id: str,
    title: str,
) -> str:
    """Create or find the conversation for a pipeline. Returns conversation ID."""
    pool = _get_db()

    # Check if conversation already exists
    row = await pool.fetchrow(
        """
        SELECT id FROM conversations
        WHERE org_id = $1 AND type = 'pipeline' AND pipeline_id = $2
        """,
        org_id,
        pipeline_id,
    )
    if row:
        return str(row["id"])

    # Create new pipeline conversation
    row = await pool.fetchrow(
        """
        INSERT INTO conversations (org_id, type, title, pipeline_id)
        VALUES ($1, 'pipeline', $2, $3)
        RETURNING id
        """,
        org_id,
        title,
        pipeline_id,
    )
    return str(row["id"])


async def post_system_message(
    conversation_id: str,
    org_id: str,
    content: list[dict],
) -> dict:
    """Post a system message to a conversation (e.g., pipeline events)."""
    pool = _get_db()
    content_json = json.dumps(content, default=str)

    row = await pool.fetchrow(
        """
        INSERT INTO messages (conversation_id, org_id, author_type, author_name, content)
        VALUES ($1::uuid, $2, 'system', 'System', $3::jsonb)
        RETURNING id, conversation_id, org_id, author_type, author_id,
                  author_name, content, thread_id, created_at
        """,
        conversation_id,
        org_id,
        content_json,
    )

    msg = _row_to_dict(row)

    # Broadcast via Redis
    try:
        r = _get_redis()
        await r.publish(
            f"forge:conv:{conversation_id}",
            json.dumps({"type": "message", "payload": msg}, default=str),
        )
    except Exception:
        pass

    return msg


async def post_agent_message(
    conversation_id: str,
    org_id: str,
    agent_role: str,
    content: list[dict],
) -> dict:
    """Post an agent message to a conversation (e.g., pipeline stage output)."""
    pool = _get_db()
    content_json = json.dumps(content, default=str)
    display_name = AGENT_DISPLAY_NAMES.get(agent_role, agent_role)

    row = await pool.fetchrow(
        """
        INSERT INTO messages (conversation_id, org_id, author_type, author_id,
                              author_name, content)
        VALUES ($1::uuid, $2, 'agent', $3, $4, $5::jsonb)
        RETURNING id, conversation_id, org_id, author_type, author_id,
                  author_name, content, thread_id, created_at
        """,
        conversation_id,
        org_id,
        agent_role,
        display_name,
        content_json,
    )

    msg = _row_to_dict(row)

    # Broadcast via Redis
    try:
        r = _get_redis()
        await r.publish(
            f"forge:conv:{conversation_id}",
            json.dumps({"type": "message", "payload": msg}, default=str),
        )
    except Exception:
        pass

    return msg
