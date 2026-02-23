"""Lightweight agent log streaming — publishes directly to Redis.

Bypasses Temporal activities to avoid full round-trip overhead for
high-frequency LLM-level events (10-20 per stage).  Events use the
same ``AgentEvent`` shape so the dashboard and WebSocket layer need
zero changes.

Usage::

    from memory.agent_log import stream_agent_log

    await stream_agent_log(
        pipeline_id,
        "llm.request_completed",
        agent_role="pm",
        stage="task_decomposition",
        payload={"model": "claude-sonnet-4-5", "latency_ms": 1200},
    )
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

import structlog

log = structlog.get_logger().bind(component="agent_log")

# Re-use the module-level BatchEventEmitter from pipeline_activities.
# Lazy import avoids circular dependencies at module load time.
_emitter_ref: Any = None


def _get_emitter() -> Any:
    """Return the BatchEventEmitter singleton from pipeline_activities."""
    global _emitter_ref
    if _emitter_ref is None:
        from activities.pipeline_activities import _get_batch_emitter

        _emitter_ref = _get_batch_emitter
    return _emitter_ref()


async def stream_agent_log(
    pipeline_id: str,
    event_type: str,
    *,
    agent_role: str | None = None,
    agent_id: str | None = None,
    stage: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    """Publish an ephemeral agent event to the Redis event stream.

    Best-effort — failures are logged but never raised.  No DB
    persistence; these are streaming-only logs for the dashboard.
    """
    now = datetime.now(timezone.utc).isoformat()
    event_dict = {
        "id": uuid.uuid4().hex,
        "pipeline_id": pipeline_id,
        "event_type": event_type,
        "stage": stage,
        "agent_role": agent_role,
        "agent_id": agent_id,
        "payload": payload or {},
        "timestamp": now,
        "created_at": now,
    }
    try:
        emitter = _get_emitter()
        await emitter.emit(pipeline_id, event_dict)
    except Exception as exc:
        log.debug("agent log stream failed", error=str(exc), event_type=event_type)
