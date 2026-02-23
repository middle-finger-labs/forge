"""Integration tests for the WorkingMemory Redis layer.

Requires a running Redis instance.  Tests are skipped automatically if
Redis is not available.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

from memory.working_memory import WorkingMemory

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _uid() -> str:
    return f"test-{uuid.uuid4().hex[:10]}"


@pytest.fixture
async def wm(redis_url):
    """Create a WorkingMemory instance and clean up after tests."""
    w = WorkingMemory(redis_url)
    keys_to_clean: list[str] = []

    # Track keys for cleanup
    _orig_set = w._redis.set

    async def _tracking_set(key, *args, **kwargs):
        keys_to_clean.append(key)
        return await _orig_set(key, *args, **kwargs)

    w._redis.set = _tracking_set  # type: ignore[assignment]

    yield w

    # Cleanup
    for key in keys_to_clean:
        try:
            await w._redis.delete(key)
        except Exception:
            pass
    await w.close()


# ---------------------------------------------------------------------------
# Active agent tracking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_get_active_agents(wm: WorkingMemory) -> None:
    """Store and retrieve active agent list."""
    pid = _uid()
    agents = [
        {"agent_id": "coder-1", "ticket_key": "FORGE-1"},
        {"agent_id": "coder-2", "ticket_key": "FORGE-2"},
    ]

    await wm.set_active_agents(pid, agents)
    result = await wm.get_active_agents(pid)

    assert len(result) == 2
    assert result[0]["agent_id"] == "coder-1"
    assert result[1]["ticket_key"] == "FORGE-2"


@pytest.mark.asyncio
async def test_get_active_agents_empty(wm: WorkingMemory) -> None:
    """Getting agents for a nonexistent pipeline returns empty list."""
    result = await wm.get_active_agents(_uid())
    assert result == []


# ---------------------------------------------------------------------------
# Ticket locks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ticket_lock_acquire_and_release(wm: WorkingMemory) -> None:
    """Lock acquisition returns True, and release makes the key available again."""
    pid = _uid()

    locked = await wm.set_ticket_lock(pid, "FORGE-1", "agent-a")
    assert locked is True

    await wm.release_ticket_lock(pid, "FORGE-1")

    # Should be acquirable again after release
    locked2 = await wm.set_ticket_lock(pid, "FORGE-1", "agent-b")
    assert locked2 is True

    # Cleanup
    await wm.release_ticket_lock(pid, "FORGE-1")


@pytest.mark.asyncio
async def test_ticket_lock_prevents_double_acquire(wm: WorkingMemory) -> None:
    """A second attempt to lock the same ticket must return False."""
    pid = _uid()

    first = await wm.set_ticket_lock(pid, "FORGE-2", "agent-a")
    assert first is True

    second = await wm.set_ticket_lock(pid, "FORGE-2", "agent-b")
    assert second is False

    # Cleanup
    await wm.release_ticket_lock(pid, "FORGE-2")


@pytest.mark.asyncio
async def test_ticket_lock_different_tickets(wm: WorkingMemory) -> None:
    """Locking different tickets should not interfere."""
    pid = _uid()

    lock1 = await wm.set_ticket_lock(pid, "FORGE-1", "agent-a")
    lock2 = await wm.set_ticket_lock(pid, "FORGE-2", "agent-b")

    assert lock1 is True
    assert lock2 is True

    # Cleanup
    await wm.release_ticket_lock(pid, "FORGE-1")
    await wm.release_ticket_lock(pid, "FORGE-2")


# ---------------------------------------------------------------------------
# Pub/sub events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_publish_subscribe_events(wm: WorkingMemory) -> None:
    """Published events should be received by the subscriber."""
    pid = _uid()
    received: list[dict] = []

    async def subscriber():
        async with wm.subscribe_events(pid) as events:
            async for event in events:
                received.append(event)
                if len(received) >= 2:
                    break

    # Start subscriber in background
    sub_task = asyncio.create_task(subscriber())

    # Give the subscriber time to connect
    await asyncio.sleep(0.3)

    # Publish two events
    await wm.publish_event(pid, {"event_type": "stage.started", "stage": "coding"})
    await wm.publish_event(pid, {"event_type": "stage.completed", "stage": "coding"})

    # Wait for subscriber to receive (with timeout)
    try:
        await asyncio.wait_for(sub_task, timeout=5.0)
    except TimeoutError:
        sub_task.cancel()
        try:
            await sub_task
        except asyncio.CancelledError:
            pass

    assert len(received) >= 2
    assert received[0]["event_type"] == "stage.started"
    assert received[1]["event_type"] == "stage.completed"


# ---------------------------------------------------------------------------
# Artifact caching
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cache_artifact_set_get(wm: WorkingMemory) -> None:
    """Cache and retrieve a stage artifact."""
    pid = _uid()
    artifact = {"product_name": "TestApp", "user_stories": ["US-1"]}

    await wm.cache_artifact(pid, "business_analysis", artifact)
    result = await wm.get_cached_artifact(pid, "business_analysis")

    assert result is not None
    assert result["product_name"] == "TestApp"
    assert len(result["user_stories"]) == 1


@pytest.mark.asyncio
async def test_cache_artifact_missing(wm: WorkingMemory) -> None:
    """Non-existent artifact returns None."""
    result = await wm.get_cached_artifact(_uid(), "nonexistent")
    assert result is None


@pytest.mark.asyncio
async def test_cache_artifact_expiry(wm: WorkingMemory) -> None:
    """Artifact with TTL=1 should expire quickly."""
    pid = _uid()
    await wm.cache_artifact(pid, "ephemeral", {"data": True}, ttl=1)

    # Should exist immediately
    result = await wm.get_cached_artifact(pid, "ephemeral")
    assert result is not None

    # Wait for expiry
    await asyncio.sleep(1.5)

    result = await wm.get_cached_artifact(pid, "ephemeral")
    assert result is None
