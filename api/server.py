"""Forge dashboard API — FastAPI backend.

Provides REST endpoints for managing pipelines, WebSocket streaming of
real-time events via Redis pub/sub, and Temporal workflow interaction.

Usage::

    python -m api.run          # starts uvicorn on port 8000
    uvicorn api.server:app     # or directly via uvicorn
"""

from __future__ import annotations

import json
import os
import uuid
from contextlib import asynccontextmanager

import asyncpg
import redis.asyncio as aioredis
import structlog
from fastapi import Depends, FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from temporalio.client import Client as TemporalClient
from temporalio.service import RPCError

from auth.middleware import get_current_user, require_org_admin, require_org_member
from auth.types import ForgeUser
from config.concurrency import get_monitor
from memory import get_working_memory
from workflows.pipeline import PIPELINE_QUEUE, ForgePipeline
from workflows.types import (
    ApprovalStatus,
    HumanApproval,
    PipelineInput,
    PipelineStage,
    RetryStageRequest,
)

log = structlog.get_logger().bind(component="api")

# ---------------------------------------------------------------------------
# Configuration (from environment)
# ---------------------------------------------------------------------------

DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://forge:forge@localhost:5432/forge_dev",
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
TEMPORAL_ADDRESS = os.environ.get("TEMPORAL_ADDRESS", "localhost:7233")

# ---------------------------------------------------------------------------
# Shared state (initialised in lifespan)
# ---------------------------------------------------------------------------

_db_pool: asyncpg.Pool | None = None
_redis: aioredis.Redis | None = None
_temporal: TemporalClient | None = None

# Runtime-configurable pipeline defaults (updated via POST /api/admin/config)
_pipeline_config_overrides: dict = {}


def _get_db() -> asyncpg.Pool:
    assert _db_pool is not None, "DB pool not initialised"
    return _db_pool


def _get_redis() -> aioredis.Redis:
    assert _redis is not None, "Redis not initialised"
    return _redis


def _get_temporal() -> TemporalClient:
    assert _temporal is not None, "Temporal client not initialised"
    return _temporal


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application startup and shutdown: connect to PostgreSQL, Redis, and Temporal."""
    global _db_pool, _redis, _temporal  # noqa: PLW0603

    log.info("connecting to PostgreSQL", dsn=DATABASE_URL.split("@")[-1])
    _db_pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)

    log.info("connecting to Redis", url=REDIS_URL)
    _redis = aioredis.from_url(REDIS_URL, decode_responses=True)

    log.info("connecting to Temporal", address=TEMPORAL_ADDRESS)
    _temporal = await TemporalClient.connect(TEMPORAL_ADDRESS)

    # Inject DB pool into the secrets module
    from auth.secrets import set_db_pool as _set_secrets_pool
    _set_secrets_pool(_db_pool)

    log.info("API ready")
    yield

    # Shutdown
    if _temporal:
        await _temporal.service_client.close()
    if _db_pool:
        await _db_pool.close()
    if _redis:
        await _redis.aclose()


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Forge Dashboard API", version="0.1.0", lifespan=lifespan)

_DEFAULT_CORS_ORIGINS = "http://localhost:5173,http://localhost:3000,http://localhost:3100"
_CORS_ORIGINS = os.environ.get("FORGE_CORS_ORIGINS", _DEFAULT_CORS_ORIGINS).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _CORS_ORIGINS if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# GitHub webhook receiver
from integrations.webhook_server import webhook_router  # noqa: E402

app.include_router(webhook_router)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class StartPipelineRequest(BaseModel):
    """Request body for starting a new pipeline workflow."""

    business_spec: str
    project_name: str = ""
    repo_url: str | None = None
    identity: str | None = None
    issue_number: int | None = None
    pr_strategy: str = "single_pr"


class ApprovalRequest(BaseModel):
    """Request body for approving or rejecting a pipeline stage."""

    stage: str
    notes: str = ""
    approved_by: str = "dashboard-user"


class AbortRequest(BaseModel):
    """Request body for aborting a running pipeline."""

    reason: str = "Aborted from dashboard"


class UpdateConfigRequest(BaseModel):
    """Request body for updating runtime pipeline configuration defaults."""

    max_concurrent_engineers: int | None = None
    max_qa_cycles: int | None = None
    auto_merge: bool | None = None
    model_overrides: dict[str, str] | None = None


class RetryStageApiRequest(BaseModel):
    """Request body for retrying a failed pipeline stage."""

    stage: str
    modified_input: dict | None = None
    requested_by: str = "dashboard-admin"


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------


@app.get("/api/health")
async def health_check():
    """Check connectivity to PostgreSQL, Redis, and Temporal."""
    status: dict[str, str] = {}

    # PostgreSQL
    try:
        pool = _get_db()
        await pool.fetchval("SELECT 1")
        status["postgresql"] = "ok"
    except Exception as exc:
        status["postgresql"] = f"error: {exc}"

    # Redis
    try:
        r = _get_redis()
        await r.ping()
        status["redis"] = "ok"
    except Exception as exc:
        status["redis"] = f"error: {exc}"

    # Temporal
    try:
        client = _get_temporal()
        await client.service_client.check_health()
        status["temporal"] = "ok"
    except RPCError as exc:
        status["temporal"] = f"error: {exc}"
    except Exception as exc:
        status["temporal"] = f"error: {exc}"

    all_ok = all(v == "ok" for v in status.values())
    return {"healthy": all_ok, "services": status}


# ---------------------------------------------------------------------------
# REST — Pipeline CRUD
# ---------------------------------------------------------------------------


@app.get("/api/pipelines")
async def list_pipelines(user: ForgeUser = Depends(get_current_user)):
    """List all pipeline runs scoped to the user's org."""
    pool = _get_db()
    try:
        rows = await pool.fetch(
            """
            SELECT id, pipeline_id, status, current_stage, created_at, total_cost_usd
            FROM pipeline_runs
            WHERE org_id = $1 OR org_id IS NULL
            ORDER BY created_at DESC
            """,
            user.org_id,
        )
        return [dict(r) for r in rows]
    except asyncpg.UndefinedTableError:
        log.warning("pipeline_runs table does not exist yet")
        return []


@app.get("/api/pipelines/{pipeline_id}")
async def get_pipeline(pipeline_id: str, user: ForgeUser = Depends(get_current_user)):
    """Get full pipeline details including artifacts."""
    pool = _get_db()
    try:
        row = await pool.fetchrow(
            """
            SELECT id, pipeline_id, status, current_stage, created_at, updated_at,
                   total_cost_usd, business_spec, project_name,
                   product_spec, enriched_spec, tech_spec, prd_board
            FROM pipeline_runs
            WHERE pipeline_id = $1 AND (org_id = $2 OR org_id IS NULL)
            """,
            pipeline_id,
            user.org_id,
        )
    except asyncpg.UndefinedTableError:
        raise HTTPException(status_code=404, detail="Pipeline not found (tables not initialised)")

    if row is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    result = dict(row)
    # Decode JSONB columns
    for col in ("product_spec", "enriched_spec", "tech_spec", "prd_board"):
        val = result.get(col)
        if isinstance(val, str):
            try:
                result[col] = json.loads(val)
            except (json.JSONDecodeError, TypeError):
                pass
    return result


@app.get("/api/pipelines/{pipeline_id}/events")
async def get_pipeline_events(pipeline_id: str, user: ForgeUser = Depends(get_current_user)):
    """Get recent agent events for a pipeline."""
    pool = _get_db()
    try:
        rows = await pool.fetch(
            """
            SELECT id, pipeline_id, event_type, stage, agent_role, agent_id,
                   payload, created_at
            FROM agent_events
            WHERE pipeline_id = $1 AND (org_id = $2 OR org_id IS NULL)
            ORDER BY created_at DESC
            LIMIT 200
            """,
            pipeline_id,
            user.org_id,
        )
    except asyncpg.UndefinedTableError:
        log.warning("agent_events table does not exist yet")
        return []

    results = []
    for r in rows:
        row_dict = dict(r)
        payload = row_dict.get("payload")
        if isinstance(payload, str):
            try:
                row_dict["payload"] = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                pass
        results.append(row_dict)
    return results


@app.get("/api/pipelines/{pipeline_id}/tickets")
async def get_pipeline_tickets(pipeline_id: str, user: ForgeUser = Depends(get_current_user)):
    """Get ticket execution statuses for a pipeline."""
    pool = _get_db()
    try:
        rows = await pool.fetch(
            """
            SELECT id, pipeline_id, ticket_key, status, verdict,
                   code_artifact, qa_review, attempts, created_at, updated_at
            FROM ticket_executions
            WHERE pipeline_id = $1 AND (org_id = $2 OR org_id IS NULL)
            ORDER BY created_at ASC
            """,
            pipeline_id,
            user.org_id,
        )
    except asyncpg.UndefinedTableError:
        log.warning("ticket_executions table does not exist yet")
        return []

    results = []
    for r in rows:
        row_dict = dict(r)
        for col in ("code_artifact", "qa_review"):
            val = row_dict.get(col)
            if isinstance(val, str):
                try:
                    row_dict[col] = json.loads(val)
                except (json.JSONDecodeError, TypeError):
                    pass
        results.append(row_dict)
    return results


# ---------------------------------------------------------------------------
# REST — Pipeline actions (Temporal interaction)
# ---------------------------------------------------------------------------


@app.post("/api/pipelines")
async def start_pipeline(req: StartPipelineRequest, user: ForgeUser = Depends(get_current_user)):
    """Start a new pipeline workflow via Temporal."""
    client = _get_temporal()
    pipeline_id = uuid.uuid4().hex[:12]
    wf_id = f"forge-pipeline-{pipeline_id}"

    # Parse repo owner/name from URL if provided
    repo_owner: str | None = None
    repo_name: str | None = None
    if req.repo_url:
        from integrations.git_identity import parse_github_url

        parsed = parse_github_url(req.repo_url)
        if parsed:
            repo_owner, repo_name = parsed

    pipeline_input = PipelineInput(
        pipeline_id=pipeline_id,
        business_spec=req.business_spec,
        project_name=req.project_name or repo_name or "ForgeProject",
        org_id=user.org_id,
        repo_url=req.repo_url,
        repo_owner=repo_owner,
        repo_name=repo_name,
        git_identity_name=req.identity,
        issue_number=req.issue_number,
        pr_strategy=req.pr_strategy,
    )

    await client.start_workflow(
        ForgePipeline.run,
        pipeline_input,
        id=wf_id,
        task_queue=PIPELINE_QUEUE,
    )

    log.info("pipeline started", pipeline_id=pipeline_id, workflow_id=wf_id)

    # Insert initial record into DB
    pool = _get_db()
    try:
        await pool.execute(
            """
            INSERT INTO pipeline_runs (pipeline_id, status, current_stage,
                                       business_spec, project_name, org_id)
            VALUES ($1, $2, $3, $4, $5, $6)
            """,
            pipeline_id,
            "running",
            "intake",
            req.business_spec,
            req.project_name or "ForgeProject",
            user.org_id,
        )
    except Exception as exc:
        log.warning("failed to insert pipeline_runs row", pipeline_id=pipeline_id, error=str(exc))

    return {
        "pipeline_id": pipeline_id,
        "workflow_id": wf_id,
        "status": "started",
    }


@app.post("/api/pipelines/{pipeline_id}/approve")
async def approve_pipeline(pipeline_id: str, req: ApprovalRequest, user: ForgeUser = Depends(get_current_user)):
    """Send approval signal to the Temporal workflow."""
    client = _get_temporal()
    wf_id = f"forge-pipeline-{pipeline_id}"

    try:
        stage = PipelineStage(req.stage)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid stage: {req.stage}")

    handle = client.get_workflow_handle(wf_id)
    await handle.signal(
        ForgePipeline.human_approval,
        HumanApproval(
            stage=stage,
            status=ApprovalStatus.APPROVED,
            notes=req.notes,
            approved_by=req.approved_by,
        ),
    )

    log.info("approval sent", pipeline_id=pipeline_id, stage=req.stage)
    return {"pipeline_id": pipeline_id, "action": "approved", "stage": req.stage}


@app.post("/api/pipelines/{pipeline_id}/reject")
async def reject_pipeline(pipeline_id: str, req: ApprovalRequest, user: ForgeUser = Depends(get_current_user)):
    """Send rejection signal to the Temporal workflow."""
    client = _get_temporal()
    wf_id = f"forge-pipeline-{pipeline_id}"

    try:
        stage = PipelineStage(req.stage)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid stage: {req.stage}")

    handle = client.get_workflow_handle(wf_id)
    await handle.signal(
        ForgePipeline.human_approval,
        HumanApproval(
            stage=stage,
            status=ApprovalStatus.REJECTED,
            notes=req.notes,
            approved_by=req.approved_by,
        ),
    )

    log.info("rejection sent", pipeline_id=pipeline_id, stage=req.stage)
    return {"pipeline_id": pipeline_id, "action": "rejected", "stage": req.stage}


@app.post("/api/pipelines/{pipeline_id}/abort")
async def abort_pipeline(pipeline_id: str, req: AbortRequest, user: ForgeUser = Depends(get_current_user)):
    """Send abort signal to the Temporal workflow."""
    client = _get_temporal()
    wf_id = f"forge-pipeline-{pipeline_id}"

    handle = client.get_workflow_handle(wf_id)
    await handle.signal(ForgePipeline.abort, req.reason)

    log.info("abort sent", pipeline_id=pipeline_id, reason=req.reason)
    return {"pipeline_id": pipeline_id, "action": "aborted"}


@app.get("/api/pipelines/{pipeline_id}/state")
async def get_pipeline_state(pipeline_id: str, user: ForgeUser = Depends(get_current_user)):
    """Query the Temporal workflow for current state."""
    client = _get_temporal()
    wf_id = f"forge-pipeline-{pipeline_id}"

    try:
        handle = client.get_workflow_handle(wf_id)
        state = await handle.query(ForgePipeline.get_state)
    except Exception as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Could not query workflow {wf_id}: {exc}",
        )

    return state


# ---------------------------------------------------------------------------
# REST — Concurrency metrics
# ---------------------------------------------------------------------------


@app.get("/api/pipelines/{pipeline_id}/concurrency")
async def get_concurrency_metrics(pipeline_id: str, user: ForgeUser = Depends(get_current_user)):
    """Return concurrency metrics for a running pipeline."""
    monitor = await get_monitor(pipeline_id)
    return await monitor.get_metrics()


# ---------------------------------------------------------------------------
# WebSocket — room-based multiplayer event stream with presence
# ---------------------------------------------------------------------------

# In-memory room tracking: pipeline_id -> set of (user_id, websocket)
import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

_rooms: dict[str, dict[str, "RoomMember"]] = defaultdict(dict)
_rooms_lock = asyncio.Lock()

PRESENCE_TTL = 300  # seconds


@dataclass
class RoomMember:
    user_id: str
    user_name: str
    email: str
    websocket: WebSocket
    joined_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


async def _validate_ws_token(token: str) -> ForgeUser | None:
    """Validate a WebSocket token using the same auth middleware logic."""
    from auth.middleware import FORGE_AUTH_ENABLED, _DEV_USER, _get_cached_user, _validate_session, _cache_user

    if not FORGE_AUTH_ENABLED:
        return _DEV_USER

    if not token:
        return None

    # Check Redis cache first
    cached = await _get_cached_user(token)
    if cached is not None:
        return cached

    try:
        user = await _validate_session(token)
        await _cache_user(token, user)
        return user
    except Exception:
        return None


async def _broadcast_to_room(pipeline_id: str, message: dict, exclude_user: str | None = None):
    """Send a message to all WebSocket clients in a room."""
    room = _rooms.get(pipeline_id, {})
    payload = json.dumps(message, default=str)
    dead: list[str] = []
    for uid, member in room.items():
        if uid == exclude_user:
            continue
        try:
            await member.websocket.send_text(payload)
        except Exception:
            dead.append(uid)
    # Clean up dead connections
    for uid in dead:
        room.pop(uid, None)


async def _set_presence(pipeline_id: str, user: ForgeUser):
    """Update Redis presence hash for the room."""
    try:
        r = _get_redis()
        presence_data = json.dumps({
            "user_id": user.user_id,
            "user_name": user.name,
            "email": user.email,
            "status": "online",
            "joined_at": datetime.now(timezone.utc).isoformat(),
        })
        await r.hset(f"forge:presence:{pipeline_id}", user.user_id, presence_data)
        await r.expire(f"forge:presence:{pipeline_id}", PRESENCE_TTL)
    except Exception as exc:
        log.warning("presence set failed", error=str(exc))


async def _remove_presence(pipeline_id: str, user_id: str):
    """Remove a user from the Redis presence hash."""
    try:
        r = _get_redis()
        await r.hdel(f"forge:presence:{pipeline_id}", user_id)
    except Exception:
        pass


async def _get_presence(pipeline_id: str) -> list[dict]:
    """Get all online users in a pipeline room from Redis."""
    try:
        r = _get_redis()
        raw = await r.hgetall(f"forge:presence:{pipeline_id}")
        return [json.loads(v) for v in raw.values()]
    except Exception:
        return []


@app.websocket("/ws/pipeline/{pipeline_id}")
async def ws_pipeline_events(websocket: WebSocket, pipeline_id: str, token: str = ""):
    """Room-based multiplayer WebSocket with presence tracking.

    Query params:
        token: session token for authentication

    Incoming message types from clients:
        - {"type": "typing", "is_typing": true/false}
        - {"type": "heartbeat"}
        - {"type": "presence_update", "status": "online"|"away"}

    Outgoing message types to clients:
        - Pipeline events (AgentEvent shape from pub/sub)
        - {"type": "user_joined", "user": {...}, "online": [...]}
        - {"type": "user_left", "user_id": "...", "online": [...]}
        - {"type": "typing", "user_id": "...", "user_name": "...", "is_typing": bool}
        - {"type": "chat_message", "message": {...}}
        - {"type": "presence_sync", "online": [...]}
    """
    # Validate auth token
    user = await _validate_ws_token(token)
    if not user:
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()

    # Join room
    member = RoomMember(
        user_id=user.user_id,
        user_name=user.name,
        email=user.email,
        websocket=websocket,
    )

    async with _rooms_lock:
        _rooms[pipeline_id][user.user_id] = member

    await _set_presence(pipeline_id, user)

    # Get current presence and broadcast join
    online = await _get_presence(pipeline_id)
    user_info = {"user_id": user.user_id, "user_name": user.name, "email": user.email}

    await _broadcast_to_room(pipeline_id, {
        "type": "user_joined",
        "user": user_info,
        "online": online,
    }, exclude_user=user.user_id)

    # Send presence sync to the newly joined user
    await websocket.send_text(json.dumps({
        "type": "presence_sync",
        "online": online,
    }, default=str))

    wm = get_working_memory()

    # Create tasks for bidirectional communication
    async def listen_pipeline_events():
        """Forward pipeline events from Redis pub/sub to all room members."""
        try:
            async with wm.subscribe_events(pipeline_id) as events:
                async for event in events:
                    if isinstance(event, dict) and event.get("batch"):
                        for single_event in event.get("events", []):
                            await _broadcast_to_room(pipeline_id, single_event)
                    else:
                        await _broadcast_to_room(pipeline_id, event)
        except Exception:
            pass

    async def listen_room_messages():
        """Forward room-level messages (chat, typing) from Redis pub/sub."""
        try:
            r = _get_redis()
            pubsub = r.pubsub()
            await pubsub.subscribe(f"forge:room:{pipeline_id}")
            async for msg in pubsub.listen():
                if msg["type"] != "message":
                    continue
                data = json.loads(msg["data"])
                # Broadcast to all room members
                await _broadcast_to_room(pipeline_id, data)
            await pubsub.unsubscribe(f"forge:room:{pipeline_id}")
        except Exception:
            pass

    async def listen_client():
        """Handle incoming messages from this client."""
        try:
            while True:
                raw = await websocket.receive_text()
                data = json.loads(raw)
                msg_type = data.get("type")

                if msg_type == "typing":
                    await _broadcast_to_room(pipeline_id, {
                        "type": "typing",
                        "user_id": user.user_id,
                        "user_name": user.name,
                        "is_typing": data.get("is_typing", False),
                    }, exclude_user=user.user_id)

                elif msg_type == "heartbeat":
                    # Refresh presence TTL
                    await _set_presence(pipeline_id, user)

                elif msg_type == "presence_update":
                    await _set_presence(pipeline_id, user)
                    online = await _get_presence(pipeline_id)
                    await _broadcast_to_room(pipeline_id, {
                        "type": "presence_sync",
                        "online": online,
                    })

        except WebSocketDisconnect:
            pass
        except Exception:
            pass

    try:
        log.info("ws room joined", pipeline_id=pipeline_id, user_id=user.user_id)
        # Run all listeners concurrently — when client disconnects, cancel all
        tasks = [
            asyncio.create_task(listen_pipeline_events()),
            asyncio.create_task(listen_room_messages()),
            asyncio.create_task(listen_client()),
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for t in pending:
            t.cancel()
    except Exception as exc:
        log.warning("ws error", pipeline_id=pipeline_id, error=str(exc))
    finally:
        # Leave room
        async with _rooms_lock:
            _rooms[pipeline_id].pop(user.user_id, None)
            if not _rooms[pipeline_id]:
                del _rooms[pipeline_id]

        await _remove_presence(pipeline_id, user.user_id)
        online = await _get_presence(pipeline_id)
        await _broadcast_to_room(pipeline_id, {
            "type": "user_left",
            "user_id": user.user_id,
            "online": online,
        })
        log.info("ws room left", pipeline_id=pipeline_id, user_id=user.user_id)


# ---------------------------------------------------------------------------
# REST — Memory endpoints (org-scoped)
# ---------------------------------------------------------------------------


def _parse_memory_rows(rows: list) -> list[dict]:
    """Convert asyncpg memory_store rows into JSON-safe dicts."""
    results = []
    for r in rows:
        row_dict = dict(r)
        row_dict["id"] = str(row_dict["id"])
        meta = row_dict.get("metadata")
        if isinstance(meta, str):
            try:
                row_dict["metadata"] = json.loads(meta)
            except (json.JSONDecodeError, TypeError):
                pass
        results.append(row_dict)
    return results


@app.get("/api/memory/lessons")
async def list_lessons(
    agent_role: str | None = None,
    limit: int = 20,
    user: ForgeUser = Depends(get_current_user),
):
    """List stored lessons, optionally filtered by agent role (org-scoped)."""
    pool = _get_db()
    try:
        if agent_role:
            rows = await pool.fetch(
                """
                SELECT id, agent_role, pipeline_id, user_id, content, metadata, created_at
                FROM memory_store
                WHERE memory_type = 'lesson' AND agent_role = $1
                  AND (org_id = $3 OR org_id IS NULL)
                ORDER BY created_at DESC
                LIMIT $2
                """,
                agent_role,
                limit,
                user.org_id,
            )
        else:
            rows = await pool.fetch(
                """
                SELECT id, agent_role, pipeline_id, user_id, content, metadata, created_at
                FROM memory_store
                WHERE memory_type = 'lesson'
                  AND (org_id = $2 OR org_id IS NULL)
                ORDER BY created_at DESC
                LIMIT $1
                """,
                limit,
                user.org_id,
            )
    except asyncpg.UndefinedTableError:
        return []

    return _parse_memory_rows(rows)


class CreateLessonRequest(BaseModel):
    content: str
    agent_role: str = "manual"
    metadata: dict | None = None


@app.post("/api/memory/lessons")
async def create_lesson(
    body: CreateLessonRequest,
    user: ForgeUser = Depends(get_current_user),
):
    """Manually add a lesson to the org's shared memory (for seeding knowledge)."""
    pool = _get_db()
    meta_json = json.dumps(
        {**(body.metadata or {}), "source": "manual", "created_by_email": user.email},
        default=str,
    )
    try:
        row = await pool.fetchrow(
            """
            INSERT INTO memory_store
                (agent_role, pipeline_id, org_id, user_id, content, memory_type, metadata)
            VALUES ($1, NULL, $2, $3, $4, 'lesson', $5::jsonb)
            RETURNING id, agent_role, pipeline_id, user_id, content, metadata, created_at
            """,
            body.agent_role,
            user.org_id,
            user.user_id,
            body.content,
            meta_json,
        )
    except asyncpg.UndefinedTableError:
        raise HTTPException(status_code=500, detail="Memory table not initialised")

    result = dict(row)
    result["id"] = str(result["id"])
    return result


@app.get("/api/memory/decisions")
async def list_decisions(limit: int = 20, user: ForgeUser = Depends(get_current_user)):
    """List stored decisions (org-scoped)."""
    pool = _get_db()
    try:
        rows = await pool.fetch(
            """
            SELECT id, agent_role, pipeline_id, user_id, content, metadata, created_at
            FROM memory_store
            WHERE memory_type = 'decision'
              AND (org_id = $2 OR org_id IS NULL)
            ORDER BY created_at DESC
            LIMIT $1
            """,
            limit,
            user.org_id,
        )
    except asyncpg.UndefinedTableError:
        return []

    return _parse_memory_rows(rows)


@app.get("/api/memory/stats")
async def memory_stats(user: ForgeUser = Depends(get_current_user)):
    """Return org-scoped memory statistics with per-user contribution data."""
    pool = _get_db()
    org_filter = "(org_id = $1 OR org_id IS NULL)"
    try:
        total_lessons = await pool.fetchval(
            f"SELECT COUNT(*) FROM memory_store WHERE memory_type = 'lesson' AND {org_filter}",
            user.org_id,
        )
        total_decisions = await pool.fetchval(
            f"SELECT COUNT(*) FROM memory_store WHERE memory_type = 'decision' AND {org_filter}",
            user.org_id,
        )

        role_rows = await pool.fetch(
            f"""
            SELECT agent_role, COUNT(*) AS count
            FROM memory_store
            WHERE memory_type = 'lesson' AND agent_role IS NOT NULL
              AND {org_filter}
            GROUP BY agent_role
            ORDER BY count DESC
            """,
            user.org_id,
        )

        contributor_rows = await pool.fetch(
            f"""
            SELECT user_id, COUNT(*) AS count
            FROM memory_store
            WHERE user_id IS NOT NULL AND {org_filter}
            GROUP BY user_id
            ORDER BY count DESC
            LIMIT 20
            """,
            user.org_id,
        )

        recent_rows = await pool.fetch(
            f"""
            SELECT id, content, agent_role, user_id, created_at
            FROM memory_store
            WHERE memory_type = 'lesson' AND {org_filter}
            ORDER BY created_at DESC
            LIMIT 10
            """,
            user.org_id,
        )
    except asyncpg.UndefinedTableError:
        return {
            "total_lessons": 0,
            "total_decisions": 0,
            "lessons_per_role": {},
            "contributions_per_user": {},
            "recent_lessons": [],
        }

    return {
        "total_lessons": total_lessons or 0,
        "total_decisions": total_decisions or 0,
        "lessons_per_role": {r["agent_role"]: r["count"] for r in role_rows},
        "contributions_per_user": {
            r["user_id"]: r["count"] for r in contributor_rows
        },
        "recent_lessons": [
            {
                "id": str(r["id"]),
                "content": r["content"][:200],
                "agent_role": r["agent_role"],
                "user_id": r["user_id"],
                "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            }
            for r in recent_rows
        ],
    }


@app.delete("/api/memory/lessons/{lesson_id}")
async def delete_lesson(
    lesson_id: str,
    user: ForgeUser = Depends(require_org_admin),
):
    """Delete a specific lesson by UUID (admin only)."""
    pool = _get_db()
    try:
        result = await pool.execute(
            "DELETE FROM memory_store WHERE id = $1::uuid AND memory_type = 'lesson'"
            " AND (org_id = $2 OR org_id IS NULL)",
            lesson_id,
            user.org_id,
        )
    except asyncpg.UndefinedTableError:
        raise HTTPException(status_code=404, detail="Memory table not initialised")
    except asyncpg.DataError:
        raise HTTPException(status_code=400, detail="Invalid lesson ID format")

    if result == "DELETE 0":
        raise HTTPException(status_code=404, detail="Lesson not found")

    return {"deleted": lesson_id}


# ---------------------------------------------------------------------------
# REST — Pipeline messages (multiplayer chat)
# ---------------------------------------------------------------------------


class CreateMessageRequest(BaseModel):
    content: str
    message_type: str = "chat"  # 'chat', 'approval', 'rejection', 'system'


@app.post("/api/pipelines/{pipeline_id}/messages")
async def create_message(
    pipeline_id: str,
    body: CreateMessageRequest,
    user: ForgeUser = Depends(get_current_user),
):
    """Persist a chat message and broadcast it via Redis pub/sub."""
    pool = _get_db()
    row = await pool.fetchrow(
        """
        INSERT INTO pipeline_messages (pipeline_id, org_id, user_id, user_name, content, message_type)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id, pipeline_id, org_id, user_id, user_name, content, message_type, created_at
        """,
        pipeline_id,
        user.org_id,
        user.user_id,
        user.name,
        body.content,
        body.message_type,
    )

    msg = dict(row)
    msg["id"] = str(msg["id"])
    msg["created_at"] = msg["created_at"].isoformat()

    # Broadcast to WebSocket room via Redis
    try:
        r = _get_redis()
        await r.publish(
            f"forge:room:{pipeline_id}",
            json.dumps({"type": "chat_message", "message": msg}, default=str),
        )
    except Exception:
        pass  # Non-critical — the REST response already confirms persistence

    return msg


@app.get("/api/pipelines/{pipeline_id}/messages")
async def list_messages(
    pipeline_id: str,
    limit: int = 100,
    before: str | None = None,
    user: ForgeUser = Depends(get_current_user),
):
    """List chat messages for a pipeline, newest last."""
    pool = _get_db()
    if before:
        rows = await pool.fetch(
            """
            SELECT id, pipeline_id, org_id, user_id, user_name, content, message_type, created_at
            FROM pipeline_messages
            WHERE pipeline_id = $1 AND (org_id = $2 OR org_id IS NULL)
                  AND created_at < $3::timestamptz
            ORDER BY created_at ASC
            LIMIT $4
            """,
            pipeline_id,
            user.org_id,
            before,
            limit,
        )
    else:
        rows = await pool.fetch(
            """
            SELECT id, pipeline_id, org_id, user_id, user_name, content, message_type, created_at
            FROM pipeline_messages
            WHERE pipeline_id = $1 AND (org_id = $2 OR org_id IS NULL)
            ORDER BY created_at ASC
            LIMIT $3
            """,
            pipeline_id,
            user.org_id,
            limit,
        )

    return [
        {**dict(r), "id": str(r["id"]), "created_at": r["created_at"].isoformat()}
        for r in rows
    ]


# ---------------------------------------------------------------------------
# REST — Observability
# ---------------------------------------------------------------------------


@app.get("/api/observability/cost-summary/{pipeline_id}")
async def cost_summary(pipeline_id: str, user: ForgeUser = Depends(get_current_user)):
    """Return cost summary for a pipeline from state store."""
    pool = _get_db()

    try:
        pipeline = await pool.fetchrow(
            """
            SELECT pipeline_id, project_name, total_cost_usd, status, created_at
            FROM pipeline_runs
            WHERE pipeline_id = $1 AND (org_id = $2 OR org_id IS NULL)
            """,
            pipeline_id,
            user.org_id,
        )
    except asyncpg.UndefinedTableError:
        raise HTTPException(status_code=404, detail="Tables not initialised")

    if pipeline is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    # Get per-stage cost estimates from events
    try:
        stage_rows = await pool.fetch(
            """
            SELECT stage, COUNT(*) AS event_count
            FROM agent_events
            WHERE pipeline_id = $1 AND stage IS NOT NULL
            GROUP BY stage
            ORDER BY MIN(created_at)
            """,
            pipeline_id,
        )
    except asyncpg.UndefinedTableError:
        stage_rows = []

    # Get ticket-level costs
    try:
        ticket_rows = await pool.fetch(
            """
            SELECT ticket_key, status, attempts,
                   COALESCE(cost_usd, 0) AS cost_usd
            FROM ticket_executions
            WHERE pipeline_id = $1
            ORDER BY created_at
            """,
            pipeline_id,
        )
    except asyncpg.UndefinedTableError:
        ticket_rows = []

    total_cost = float(pipeline["total_cost_usd"] or 0)
    ticket_costs = [
        {
            "ticket_key": r["ticket_key"],
            "status": r["status"],
            "attempts": r["attempts"],
            "cost_usd": float(r["cost_usd"]),
        }
        for r in ticket_rows
    ]

    return {
        "pipeline_id": pipeline["pipeline_id"],
        "project_name": pipeline["project_name"],
        "total_cost_usd": total_cost,
        "status": pipeline["status"],
        "stages": [{"stage": r["stage"], "event_count": r["event_count"]} for r in stage_rows],
        "tickets": ticket_costs,
    }


# ---------------------------------------------------------------------------
# REST — Admin: system-wide stats
# ---------------------------------------------------------------------------


@app.get("/api/admin/stats")
async def admin_stats(user: ForgeUser = Depends(require_org_admin)):
    """System-wide statistics: totals, success rate, costs, failure stages."""
    pool = _get_db()

    try:
        totals = await pool.fetchrow(
            """
            SELECT
                COUNT(*)                                   AS total,
                COUNT(*) FILTER (WHERE status = 'completed') AS succeeded,
                COUNT(*) FILTER (WHERE status = 'failed')    AS failed,
                COALESCE(SUM(total_cost_usd), 0)             AS total_cost,
                COALESCE(AVG(total_cost_usd), 0)             AS avg_cost,
                COALESCE(
                    AVG(EXTRACT(EPOCH FROM (
                        COALESCE(completed_at, updated_at) - created_at
                    ))),
                    0
                ) AS avg_duration_seconds
            FROM pipeline_runs
            WHERE org_id = $1 OR org_id IS NULL
            """,
            user.org_id,
        )
    except asyncpg.UndefinedTableError:
        return {
            "total_pipelines": 0,
            "succeeded": 0,
            "failed": 0,
            "success_rate": 0.0,
            "total_cost_usd": 0.0,
            "avg_cost_usd": 0.0,
            "avg_duration_seconds": 0.0,
            "failure_stages": [],
            "model_usage": {},
        }

    total = totals["total"] or 0
    succeeded = totals["succeeded"] or 0
    success_rate = (succeeded / total * 100) if total > 0 else 0.0

    # Most common failure stages
    try:
        failure_rows = await pool.fetch(
            """
            SELECT current_stage, COUNT(*) AS count
            FROM pipeline_runs
            WHERE status = 'failed' AND current_stage IS NOT NULL
              AND (org_id = $1 OR org_id IS NULL)
            GROUP BY current_stage
            ORDER BY count DESC
            LIMIT 10
            """,
            user.org_id,
        )
    except asyncpg.UndefinedTableError:
        failure_rows = []

    # Model usage breakdown from agent events
    try:
        model_rows = await pool.fetch(
            """
            SELECT
                payload->>'model' AS model,
                COUNT(*)          AS call_count
            FROM agent_events
            WHERE payload->>'model' IS NOT NULL
              AND (org_id = $1 OR org_id IS NULL)
            GROUP BY payload->>'model'
            ORDER BY call_count DESC
            """,
            user.org_id,
        )
    except asyncpg.UndefinedTableError:
        model_rows = []

    total_model_calls = sum(r["call_count"] for r in model_rows) or 1
    model_usage = {
        r["model"]: {
            "calls": r["call_count"],
            "percentage": round(r["call_count"] / total_model_calls * 100, 1),
        }
        for r in model_rows
    }

    return {
        "total_pipelines": total,
        "succeeded": succeeded,
        "failed": totals["failed"] or 0,
        "success_rate": round(success_rate, 1),
        "total_cost_usd": round(float(totals["total_cost"] or 0), 2),
        "avg_cost_usd": round(float(totals["avg_cost"] or 0), 2),
        "avg_duration_seconds": round(
            float(totals["avg_duration_seconds"] or 0),
            1,
        ),
        "failure_stages": [
            {"stage": r["current_stage"], "count": r["count"]} for r in failure_rows
        ],
        "model_usage": model_usage,
    }


# ---------------------------------------------------------------------------
# REST — Admin: model health
# ---------------------------------------------------------------------------


@app.get("/api/admin/models")
async def admin_models(user: ForgeUser = Depends(require_org_admin)):
    """Model availability, latency, error rates, and token usage."""
    from config.agent_config import _PRICING, AGENT_CONFIGS
    from config.model_router import get_model_router

    router = get_model_router()
    local_available = await router.check_local_model_available()

    # Collect all configured models
    models_seen: set[str] = set()
    for cfg in AGENT_CONFIGS.values():
        models_seen.add(cfg.model.primary_model)
        if cfg.model.fallback_model:
            models_seen.add(cfg.model.fallback_model)

    # Query DB for per-model latency and token stats
    pool = _get_db()
    model_stats: dict[str, dict] = {}

    for model_id in models_seen:
        try:
            row = await pool.fetchrow(
                """
                SELECT
                    COUNT(*) AS total_calls,
                    COUNT(*) FILTER (
                        WHERE event_type LIKE 'error.%%'
                    ) AS error_count,
                    AVG(
                        (payload->>'latency_ms')::float
                    ) FILTER (
                        WHERE payload->>'latency_ms' IS NOT NULL
                    ) AS avg_latency_ms,
                    COALESCE(SUM(
                        (payload->>'input_tokens')::int
                    ) FILTER (
                        WHERE payload->>'input_tokens' IS NOT NULL
                    ), 0) AS total_input_tokens,
                    COALESCE(SUM(
                        (payload->>'output_tokens')::int
                    ) FILTER (
                        WHERE payload->>'output_tokens' IS NOT NULL
                    ), 0) AS total_output_tokens
                FROM agent_events
                WHERE payload->>'model' = $1
                   OR payload->>'model_used' = $1
                """,
                model_id,
            )
        except asyncpg.UndefinedTableError:
            row = None

        total_calls = (row["total_calls"] if row else 0) or 0
        error_count = (row["error_count"] if row else 0) or 0
        error_rate = round(error_count / total_calls * 100, 1) if total_calls > 0 else 0.0
        is_local = "ollama" in model_id or "qwen" in model_id
        pricing = _PRICING.get(model_id, (0.0, 0.0))

        model_stats[model_id] = {
            "available": local_available if is_local else True,
            "is_local": is_local,
            "avg_latency_ms": round(
                float(row["avg_latency_ms"] or 0),
                1,
            )
            if row
            else 0.0,
            "error_rate": error_rate,
            "total_calls": total_calls,
            "total_input_tokens": (row["total_input_tokens"] if row else 0) or 0,
            "total_output_tokens": (row["total_output_tokens"] if row else 0) or 0,
            "pricing_input_per_mtok": pricing[0],
            "pricing_output_per_mtok": pricing[1],
        }

    return {"models": model_stats, "local_model_available": local_available}


# ---------------------------------------------------------------------------
# REST — Admin: runtime config
# ---------------------------------------------------------------------------


@app.get("/api/admin/config")
async def get_admin_config(user: ForgeUser = Depends(require_org_admin)):
    """Return current pipeline config defaults (including runtime overrides)."""
    from config.agent_config import PIPELINE_CONFIG

    return {
        "max_concurrent_engineers": _pipeline_config_overrides.get(
            "max_concurrent_engineers",
            PIPELINE_CONFIG.max_concurrent_engineers,
        ),
        "max_qa_cycles": _pipeline_config_overrides.get(
            "max_qa_cycles",
            PIPELINE_CONFIG.max_qa_cycles,
        ),
        "auto_merge": _pipeline_config_overrides.get(
            "auto_merge",
            PIPELINE_CONFIG.auto_merge,
        ),
        "model_overrides": _pipeline_config_overrides.get(
            "model_overrides",
            {},
        ),
    }


@app.post("/api/admin/config")
async def update_admin_config(req: UpdateConfigRequest, user: ForgeUser = Depends(require_org_admin)):
    """Update pipeline defaults at runtime.

    Changes take effect on the next pipeline started — running
    pipelines are not affected.
    """
    if req.max_concurrent_engineers is not None:
        _pipeline_config_overrides["max_concurrent_engineers"] = req.max_concurrent_engineers
    if req.max_qa_cycles is not None:
        _pipeline_config_overrides["max_qa_cycles"] = req.max_qa_cycles
    if req.auto_merge is not None:
        _pipeline_config_overrides["auto_merge"] = req.auto_merge
    if req.model_overrides is not None:
        _pipeline_config_overrides["model_overrides"] = req.model_overrides

    log.info("admin config updated", overrides=_pipeline_config_overrides)
    return {
        "status": "updated",
        "config": _pipeline_config_overrides,
    }


# ---------------------------------------------------------------------------
# REST — Pipeline error log
# ---------------------------------------------------------------------------


@app.get("/api/pipelines/{pipeline_id}/errors")
async def get_pipeline_errors(pipeline_id: str, user: ForgeUser = Depends(get_current_user)):
    """Return error events for a pipeline with full context."""
    pool = _get_db()
    try:
        rows = await pool.fetch(
            """
            SELECT id, pipeline_id, event_type, stage, agent_role,
                   agent_id, payload, created_at
            FROM agent_events
            WHERE pipeline_id = $1
              AND (org_id = $2 OR org_id IS NULL)
              AND (event_type LIKE 'error.%%'
                   OR event_type = 'stage.error'
                   OR event_type = 'pipeline.failed'
                   OR event_type = 'group.failed')
            ORDER BY created_at DESC
            LIMIT 100
            """,
            pipeline_id,
            user.org_id,
        )
    except asyncpg.UndefinedTableError:
        return []

    results = []
    for r in rows:
        row_dict = dict(r)
        payload = row_dict.get("payload")
        if isinstance(payload, str):
            try:
                row_dict["payload"] = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                pass
        results.append(row_dict)
    return results


# ---------------------------------------------------------------------------
# REST — Pipeline cost breakdown
# ---------------------------------------------------------------------------


@app.get("/api/pipelines/{pipeline_id}/cost-breakdown")
async def get_pipeline_cost_breakdown(pipeline_id: str, user: ForgeUser = Depends(get_current_user)):
    """Detailed cost breakdown: per stage, per ticket, per model."""
    pool = _get_db()

    # Pipeline total
    try:
        pipeline = await pool.fetchrow(
            """
            SELECT pipeline_id, total_cost_usd, status, created_at
            FROM pipeline_runs WHERE pipeline_id = $1
              AND (org_id = $2 OR org_id IS NULL)
            """,
            pipeline_id,
            user.org_id,
        )
    except asyncpg.UndefinedTableError:
        raise HTTPException(status_code=404, detail="Tables not initialised")

    if pipeline is None:
        raise HTTPException(status_code=404, detail="Pipeline not found")

    # Per-stage costs from stage.completed events
    try:
        stage_rows = await pool.fetch(
            """
            SELECT
                stage,
                SUM((payload->>'cost_usd')::float) AS cost_usd,
                COUNT(*) AS event_count,
                AVG((payload->>'duration_seconds')::float) AS avg_duration
            FROM agent_events
            WHERE pipeline_id = $1
              AND event_type = 'stage.completed'
              AND payload->>'cost_usd' IS NOT NULL
            GROUP BY stage
            ORDER BY MIN(created_at)
            """,
            pipeline_id,
        )
    except asyncpg.UndefinedTableError:
        stage_rows = []

    # Per-ticket costs
    try:
        ticket_rows = await pool.fetch(
            """
            SELECT ticket_key, status, attempts,
                   COALESCE(cost_usd, 0) AS cost_usd
            FROM ticket_executions
            WHERE pipeline_id = $1
            ORDER BY created_at
            """,
            pipeline_id,
        )
    except asyncpg.UndefinedTableError:
        ticket_rows = []

    # Per-model costs
    try:
        model_rows = await pool.fetch(
            """
            SELECT
                COALESCE(
                    payload->>'model_used', payload->>'model'
                ) AS model,
                COUNT(*) AS calls,
                COALESCE(SUM((payload->>'cost_usd')::float), 0) AS cost_usd,
                COALESCE(SUM((payload->>'input_tokens')::int), 0)
                    AS input_tokens,
                COALESCE(SUM((payload->>'output_tokens')::int), 0)
                    AS output_tokens
            FROM agent_events
            WHERE pipeline_id = $1
              AND (payload->>'model_used' IS NOT NULL
                   OR payload->>'model' IS NOT NULL)
            GROUP BY COALESCE(
                payload->>'model_used', payload->>'model'
            )
            ORDER BY cost_usd DESC
            """,
            pipeline_id,
        )
    except asyncpg.UndefinedTableError:
        model_rows = []

    return {
        "pipeline_id": pipeline_id,
        "total_cost_usd": round(float(pipeline["total_cost_usd"] or 0), 4),
        "status": pipeline["status"],
        "by_stage": [
            {
                "stage": r["stage"],
                "cost_usd": round(float(r["cost_usd"] or 0), 4),
                "event_count": r["event_count"],
                "avg_duration_seconds": round(
                    float(r["avg_duration"] or 0),
                    1,
                ),
            }
            for r in stage_rows
        ],
        "by_ticket": [
            {
                "ticket_key": r["ticket_key"],
                "status": r["status"],
                "attempts": r["attempts"],
                "cost_usd": round(float(r["cost_usd"]), 4),
            }
            for r in ticket_rows
        ],
        "by_model": [
            {
                "model": r["model"],
                "calls": r["calls"],
                "cost_usd": round(float(r["cost_usd"]), 4),
                "input_tokens": r["input_tokens"],
                "output_tokens": r["output_tokens"],
            }
            for r in model_rows
        ],
    }


# ---------------------------------------------------------------------------
# REST — Retry failed stage
# ---------------------------------------------------------------------------


@app.post("/api/pipelines/{pipeline_id}/retry-stage")
async def retry_stage(pipeline_id: str, req: RetryStageApiRequest, user: ForgeUser = Depends(get_current_user)):
    """Send a retry-stage signal to a Temporal workflow."""
    client = _get_temporal()
    wf_id = f"forge-pipeline-{pipeline_id}"

    try:
        stage = PipelineStage(req.stage)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid stage: {req.stage}",
        )

    handle = client.get_workflow_handle(wf_id)

    try:
        await handle.signal(
            ForgePipeline.retry_stage,
            RetryStageRequest(
                stage=stage,
                modified_input=req.modified_input or {},
                requested_by=req.requested_by,
            ),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=404,
            detail=f"Could not signal workflow {wf_id}: {exc}",
        )

    log.info(
        "retry-stage signal sent",
        pipeline_id=pipeline_id,
        stage=req.stage,
        requested_by=req.requested_by,
    )
    return {
        "pipeline_id": pipeline_id,
        "action": "retry_stage",
        "stage": req.stage,
    }


# ---------------------------------------------------------------------------
# REST — Org Settings
# ---------------------------------------------------------------------------


@app.get("/api/settings")
async def get_settings(user: ForgeUser = Depends(get_current_user)):
    """Get the current org's settings."""
    from auth.secrets import get_org_settings
    settings = await get_org_settings(user.org_id)
    if settings is None:
        # Return defaults
        return {
            "org_id": user.org_id,
            "max_pipeline_cost_usd": 50.0,
            "max_concurrent_pipelines": 3,
            "auto_approve_stages": [],
            "default_model_tier": "strong",
            "pr_strategy": "single_pr",
            "memory_sharing_mode": "shared",
        }
    return settings


class UpdateSettingsRequest(BaseModel):
    max_pipeline_cost_usd: float | None = None
    max_concurrent_pipelines: int | None = None
    auto_approve_stages: list[str] | None = None
    default_model_tier: str | None = None
    pr_strategy: str | None = None
    memory_sharing_mode: str | None = None


@app.put("/api/settings")
async def update_settings(
    body: UpdateSettingsRequest,
    user: ForgeUser = Depends(require_org_admin),
):
    """Update org settings (admin only)."""
    from auth.secrets import upsert_org_settings

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = await upsert_org_settings(user.org_id, updates)
    return result


# ---------------------------------------------------------------------------
# REST — Org Secrets
# ---------------------------------------------------------------------------


@app.get("/api/secrets")
async def list_secrets(user: ForgeUser = Depends(get_current_user)):
    """List secret key names for the org (no values returned)."""
    from auth.secrets import list_org_secret_keys
    keys = await list_org_secret_keys(user.org_id)
    return {"org_id": user.org_id, "keys": keys}


class SetSecretRequest(BaseModel):
    value: str


@app.put("/api/secrets/{key}")
async def set_secret(
    key: str,
    body: SetSecretRequest,
    user: ForgeUser = Depends(require_org_admin),
):
    """Set (create or update) an org secret (admin only)."""
    from auth.secrets import set_org_secret
    await set_org_secret(user.org_id, key, body.value, user.user_id)
    return {"org_id": user.org_id, "key": key, "status": "stored"}


@app.delete("/api/secrets/{key}")
async def delete_secret(
    key: str,
    user: ForgeUser = Depends(require_org_admin),
):
    """Delete an org secret (admin only)."""
    from auth.secrets import delete_org_secret
    deleted = await delete_org_secret(user.org_id, key)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Secret '{key}' not found")
    return {"org_id": user.org_id, "key": key, "status": "deleted"}


# ---------------------------------------------------------------------------
# REST — Org Identities (GitHub)
# ---------------------------------------------------------------------------


@app.get("/api/identities")
async def list_identities(user: ForgeUser = Depends(get_current_user)):
    """List GitHub identities for the org."""
    from auth.secrets import list_org_identities
    identities = await list_org_identities(user.org_id)
    return {"org_id": user.org_id, "identities": identities}


class CreateIdentityRequest(BaseModel):
    name: str
    github_username: str
    email: str
    github_org: str | None = None
    ssh_key: str | None = None
    github_token: str | None = None
    is_default: bool = False


@app.post("/api/identities")
async def create_identity(
    body: CreateIdentityRequest,
    user: ForgeUser = Depends(require_org_admin),
):
    """Add a GitHub identity (admin only)."""
    from auth.secrets import create_org_identity
    identity = await create_org_identity(
        org_id=user.org_id,
        name=body.name,
        github_username=body.github_username,
        email=body.email,
        github_org=body.github_org,
        ssh_key=body.ssh_key,
        github_token=body.github_token,
        is_default=body.is_default,
    )
    return identity


@app.delete("/api/identities/{identity_id}")
async def delete_identity(
    identity_id: str,
    user: ForgeUser = Depends(require_org_admin),
):
    """Remove a GitHub identity (admin only)."""
    from auth.secrets import delete_org_identity
    deleted = await delete_org_identity(user.org_id, identity_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Identity not found")
    return {"status": "deleted", "id": identity_id}


@app.post("/api/identities/{identity_id}/test")
async def test_identity(
    identity_id: str,
    user: ForgeUser = Depends(get_current_user),
):
    """Test a GitHub identity's token/SSH connection."""
    from auth.secrets import get_org_identity, get_org_identity_token

    identity = await get_org_identity(user.org_id, identity_id)
    if identity is None:
        raise HTTPException(status_code=404, detail="Identity not found")

    result = {
        "identity_id": identity_id,
        "name": identity["name"],
        "github_username": identity["github_username"],
        "token_configured": identity.get("has_github_token", False),
        "ssh_key_configured": identity.get("has_ssh_key", False),
        "token_valid": False,
        "error": None,
    }

    # Test GitHub token if available
    token = await get_org_identity_token(user.org_id, identity_id)
    if token:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    "https://api.github.com/user",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github.v3+json",
                    },
                )
                if resp.status_code == 200:
                    gh_user = resp.json()
                    result["token_valid"] = True
                    result["github_user"] = gh_user.get("login")
                    result["github_name"] = gh_user.get("name")
                else:
                    result["error"] = f"GitHub API returned {resp.status_code}"
        except httpx.RequestError as exc:
            result["error"] = f"Connection failed: {exc}"
    else:
        result["error"] = "No GitHub token configured for this identity"

    return result
