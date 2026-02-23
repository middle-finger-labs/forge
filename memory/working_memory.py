"""Ephemeral cross-agent state backed by Redis.

Provides fast, TTL-based storage for runtime coordination that does not
need to survive restarts — active agent tracking, ticket locks, event
pub/sub, and artifact caching.

Usage::

    from memory.working_memory import WorkingMemory

    wm = WorkingMemory("redis://localhost:6379/0")
    locked = await wm.set_ticket_lock("pipeline-1", "FORGE-1", "agent-a")
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import redis.asyncio as aioredis
import structlog

log = structlog.get_logger().bind(component="working_memory")

# Key prefix — all keys live under ``forge:wm:``
_PREFIX = "forge:wm"

# Channel prefix for pub/sub (matches existing convention)
_EVENT_CHANNEL = "forge:events"

# Default TTLs (seconds)
_ACTIVE_AGENTS_TTL = 3600  # 1 hour
_TICKET_LOCK_TTL = 1800  # 30 minutes
_ARTIFACT_TTL = 3600  # 1 hour


class WorkingMemory:
    """Ephemeral Redis-backed working memory for cross-agent coordination."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url
        self._redis: aioredis.Redis = aioredis.from_url(
            redis_url,
            decode_responses=True,
            max_connections=20,
        )

    # ------------------------------------------------------------------
    # Active agent tracking
    # ------------------------------------------------------------------

    async def set_active_agents(
        self,
        pipeline_id: str,
        agents: list[dict],
    ) -> None:
        """Store the list of currently active agents with ticket assignments.

        TTL: 1 hour (auto-clears if pipeline stalls).
        """
        key = f"{_PREFIX}:agents:{pipeline_id}"
        await self._redis.set(key, json.dumps(agents), ex=_ACTIVE_AGENTS_TTL)

    async def get_active_agents(self, pipeline_id: str) -> list[dict]:
        """Retrieve the active agents for a pipeline."""
        key = f"{_PREFIX}:agents:{pipeline_id}"
        raw = await self._redis.get(key)
        if raw is None:
            return []
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return []

    # ------------------------------------------------------------------
    # Ticket locks (atomic, NX-based)
    # ------------------------------------------------------------------

    async def set_ticket_lock(
        self,
        pipeline_id: str,
        ticket_id: str,
        agent_id: str,
    ) -> bool:
        """Atomically lock a ticket to prevent duplicate assignment.

        Uses ``SET … NX`` so only the first caller wins.
        TTL: 30 minutes.

        Returns True if the lock was acquired, False if already held.
        """
        key = f"{_PREFIX}:lock:{pipeline_id}:{ticket_id}"
        result = await self._redis.set(
            key,
            agent_id,
            nx=True,
            ex=_TICKET_LOCK_TTL,
        )
        if result:
            log.debug(
                "ticket lock acquired",
                pipeline_id=pipeline_id,
                ticket_id=ticket_id,
                agent_id=agent_id,
            )
        return result is not None and bool(result)

    async def release_ticket_lock(
        self,
        pipeline_id: str,
        ticket_id: str,
    ) -> None:
        """Release a ticket lock."""
        key = f"{_PREFIX}:lock:{pipeline_id}:{ticket_id}"
        await self._redis.delete(key)
        log.debug(
            "ticket lock released",
            pipeline_id=pipeline_id,
            ticket_id=ticket_id,
        )

    # ------------------------------------------------------------------
    # Event pub/sub
    # ------------------------------------------------------------------

    async def publish_event(
        self,
        pipeline_id: str,
        event: dict,
    ) -> None:
        """Publish an event to the Redis pub/sub channel for a pipeline."""
        channel = f"{_EVENT_CHANNEL}:{pipeline_id}"
        payload = json.dumps(event, default=str)
        await self._redis.publish(channel, payload)

    @asynccontextmanager
    async def subscribe_events(
        self,
        pipeline_id: str,
    ) -> AsyncIterator[AsyncIterator[dict]]:
        """Context manager yielding an async iterator of events.

        Usage::

            async with wm.subscribe_events("pipe-1") as events:
                async for event in events:
                    print(event)
        """
        channel = f"{_EVENT_CHANNEL}:{pipeline_id}"
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(channel)
        log.debug("subscribed to events", pipeline_id=pipeline_id, channel=channel)

        async def _iter() -> AsyncIterator[dict]:
            try:
                while True:
                    msg = await pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0,
                    )
                    if msg and msg["type"] == "message":
                        data = msg["data"]
                        if isinstance(data, bytes):
                            data = data.decode()
                        try:
                            yield json.loads(data)
                        except (json.JSONDecodeError, TypeError):
                            yield {"raw": data}
                    else:
                        # Yield control to the event loop
                        await asyncio.sleep(0.05)
            except GeneratorExit:
                pass

        try:
            yield _iter()
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Artifact caching
    # ------------------------------------------------------------------

    async def cache_artifact(
        self,
        pipeline_id: str,
        stage: str,
        artifact: dict,
        ttl: int = _ARTIFACT_TTL,
    ) -> None:
        """Cache a stage artifact for fast dashboard retrieval."""
        key = f"{_PREFIX}:artifact:{pipeline_id}:{stage}"
        await self._redis.set(key, json.dumps(artifact, default=str), ex=ttl)

    async def get_cached_artifact(
        self,
        pipeline_id: str,
        stage: str,
    ) -> dict | None:
        """Retrieve a cached artifact, or None if expired/missing."""
        key = f"{_PREFIX}:artifact:{pipeline_id}:{stage}"
        raw = await self._redis.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Close the underlying Redis connection."""
        await self._redis.aclose()


# ---------------------------------------------------------------------------
# Batched event emitter
# ---------------------------------------------------------------------------


class BatchEventEmitter:
    """Buffer pipeline events and flush them to Redis in batches.

    Instead of publishing every event individually (one RTT per event),
    events are buffered per pipeline and flushed periodically as a single
    ``{"batch": True, "events": [...], "count": N}`` message.

    Usage::

        emitter = BatchEventEmitter(working_memory)
        emitter.start()
        await emitter.emit("pipeline-1", event_dict)
        ...
        await emitter.stop()  # flushes remaining events
    """

    def __init__(
        self,
        working_memory: WorkingMemory,
        flush_interval_ms: int = 500,
    ) -> None:
        self._wm = working_memory
        self._interval = flush_interval_ms / 1000.0
        self._buffer: dict[str, list[dict]] = {}
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None

    async def emit(self, pipeline_id: str, event: dict) -> None:
        """Append an event to the buffer for *pipeline_id*."""
        async with self._lock:
            self._buffer.setdefault(pipeline_id, []).append(event)

    async def flush(self) -> None:
        """Publish all buffered events and clear the buffer."""
        async with self._lock:
            snapshot = self._buffer
            self._buffer = {}

        for pipeline_id, events in snapshot.items():
            if not events:
                continue
            batch_payload = json.dumps(
                {"batch": True, "events": events, "count": len(events)},
                default=str,
            )
            channel = f"{_EVENT_CHANNEL}:{pipeline_id}"
            try:
                await self._wm._redis.publish(channel, batch_payload)
            except Exception:
                log.warning(
                    "batch event publish failed",
                    pipeline_id=pipeline_id,
                    count=len(events),
                )

    async def _flush_loop(self) -> None:
        """Background loop that flushes at a fixed interval."""
        try:
            while True:
                await asyncio.sleep(self._interval)
                await self.flush()
        except asyncio.CancelledError:
            # Final flush on shutdown
            await self.flush()

    def start(self) -> None:
        """Start the background flush loop."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._flush_loop())

    async def stop(self) -> None:
        """Stop the background flush loop and drain remaining events."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
