"""Concurrency controls and backpressure for the Forge pipeline.

Provides:
- ``ConcurrencyConfig`` — tuneable limits for parallel agent execution
- ``ConcurrencyMonitor`` — real-time tracking of active agents, resource
  usage, ticket completion rates, and backpressure decisions

Usage::

    monitor = ConcurrencyMonitor(pipeline_id="abc123")
    if await monitor.should_spawn_agent("engineer"):
        # safe to launch another coding agent
    metrics = await monitor.get_metrics()
"""

from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass

import structlog

log = structlog.get_logger().bind(component="concurrency")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class ConcurrencyConfig:
    """Tuneable concurrency limits for a pipeline run."""

    max_concurrent_engineers: int = 4
    max_concurrent_qa: int = 2
    max_concurrent_groups: int = 1
    ticket_timeout_minutes: int = 15
    group_timeout_minutes: int = 60
    max_retries_per_ticket: int = 3
    backpressure_threshold: float = 0.8


# Singleton default — importable from config package
DEFAULT_CONCURRENCY = ConcurrencyConfig()


# ---------------------------------------------------------------------------
# Completion record for rolling-window stats
# ---------------------------------------------------------------------------


@dataclass
class _TicketCompletion:
    ticket_key: str
    duration_seconds: float
    completed_at: float  # time.monotonic()


# ---------------------------------------------------------------------------
# ConcurrencyMonitor
# ---------------------------------------------------------------------------


class ConcurrencyMonitor:
    """Track active agents, resource usage, and backpressure state."""

    def __init__(
        self,
        pipeline_id: str,
        config: ConcurrencyConfig | None = None,
    ) -> None:
        self.pipeline_id = pipeline_id
        self.config = config or DEFAULT_CONCURRENCY
        self._log = log.bind(pipeline_id=pipeline_id)

        # Active agent counters
        self._active_engineers: set[str] = set()
        self._active_qa: set[str] = set()
        self._active_groups: set[int] = set()

        # Rolling-window completion stats (last 50 tickets)
        self._completions: deque[_TicketCompletion] = deque(maxlen=50)

        # Group tracking for ETA
        self._current_group_index: int | None = None
        self._total_groups: int = 0
        self._group_start_time: float | None = None
        self._tickets_in_current_group: int = 0

        # Lock for thread-safe updates
        self._lock = asyncio.Lock()

    # -- Agent lifecycle tracking -------------------------------------------

    async def register_engineer(self, ticket_key: str) -> None:
        """Mark a coding agent as active."""
        async with self._lock:
            self._active_engineers.add(ticket_key)
            self._log.debug(
                "engineer registered",
                ticket_key=ticket_key,
                active=len(self._active_engineers),
            )

    async def unregister_engineer(
        self,
        ticket_key: str,
        duration_seconds: float = 0.0,
    ) -> None:
        """Mark a coding agent as finished."""
        async with self._lock:
            self._active_engineers.discard(ticket_key)
            if duration_seconds > 0:
                self._completions.append(
                    _TicketCompletion(
                        ticket_key=ticket_key,
                        duration_seconds=duration_seconds,
                        completed_at=time.monotonic(),
                    )
                )
            self._log.debug(
                "engineer unregistered",
                ticket_key=ticket_key,
                active=len(self._active_engineers),
            )

    async def register_qa(self, ticket_key: str) -> None:
        """Mark a QA review as active."""
        async with self._lock:
            self._active_qa.add(ticket_key)

    async def unregister_qa(self, ticket_key: str) -> None:
        """Mark a QA review as finished."""
        async with self._lock:
            self._active_qa.discard(ticket_key)

    async def register_group(
        self,
        group_index: int,
        total_groups: int,
        ticket_count: int,
    ) -> None:
        """Mark a group as actively executing."""
        async with self._lock:
            self._active_groups.add(group_index)
            self._current_group_index = group_index
            self._total_groups = total_groups
            self._group_start_time = time.monotonic()
            self._tickets_in_current_group = ticket_count

    async def unregister_group(self, group_index: int) -> None:
        """Mark a group as finished."""
        async with self._lock:
            self._active_groups.discard(group_index)
            if self._current_group_index == group_index:
                self._group_start_time = None

    # -- Backpressure decisions ---------------------------------------------

    async def should_spawn_agent(self, agent_type: str = "engineer") -> bool:
        """Return True if it's safe to spawn another agent.

        Checks concurrency limits and system resource usage.
        Returns False if limits are reached or backpressure threshold
        is exceeded.
        """
        async with self._lock:
            # Check concurrency limits
            if agent_type == "engineer":
                if len(self._active_engineers) >= self.config.max_concurrent_engineers:
                    self._log.info(
                        "backpressure: engineer limit reached",
                        active=len(self._active_engineers),
                        limit=self.config.max_concurrent_engineers,
                    )
                    return False
            elif agent_type == "qa":
                if len(self._active_qa) >= self.config.max_concurrent_qa:
                    self._log.info(
                        "backpressure: QA limit reached",
                        active=len(self._active_qa),
                        limit=self.config.max_concurrent_qa,
                    )
                    return False

            # Check system resource usage
            load = self._get_system_load()
            if load > self.config.backpressure_threshold:
                self._log.warning(
                    "backpressure: system load exceeded threshold",
                    load=round(load, 3),
                    threshold=self.config.backpressure_threshold,
                )
                return False

            return True

    def _get_system_load(self) -> float:
        """Return normalised system load (0.0 – 1.0).

        Uses psutil if available, otherwise falls back to
        os.getloadavg() / cpu_count.
        """
        try:
            import psutil

            cpu = psutil.cpu_percent(interval=0) / 100.0
            mem = psutil.virtual_memory().percent / 100.0
            # Weighted: 60% CPU, 40% memory
            return cpu * 0.6 + mem * 0.4
        except ImportError:
            pass

        try:
            import os

            load_1m = os.getloadavg()[0]
            cpus = os.cpu_count() or 1
            return min(1.0, load_1m / cpus)
        except (OSError, AttributeError):
            return 0.0

    # -- Metrics ------------------------------------------------------------

    async def get_metrics(self) -> dict:
        """Return current concurrency metrics for API / dashboard."""
        async with self._lock:
            avg_duration = self._avg_completion_time()
            eta = self._estimate_remaining()

            return {
                "pipeline_id": self.pipeline_id,
                "active_engineers": len(self._active_engineers),
                "active_qa": len(self._active_qa),
                "active_groups": len(self._active_groups),
                "max_concurrent_engineers": self.config.max_concurrent_engineers,
                "max_concurrent_qa": self.config.max_concurrent_qa,
                "max_concurrent_groups": self.config.max_concurrent_groups,
                "active_engineer_tickets": sorted(self._active_engineers),
                "active_qa_tickets": sorted(self._active_qa),
                "system_load": round(self._get_system_load(), 3),
                "backpressure_threshold": self.config.backpressure_threshold,
                "backpressure_active": (
                    self._get_system_load() > self.config.backpressure_threshold
                ),
                "avg_ticket_duration_seconds": round(avg_duration, 1) if avg_duration else None,
                "completed_tickets": len(self._completions),
                "current_group_index": self._current_group_index,
                "total_groups": self._total_groups,
                "estimated_remaining_seconds": round(eta) if eta else None,
                "ticket_timeout_minutes": self.config.ticket_timeout_minutes,
                "group_timeout_minutes": self.config.group_timeout_minutes,
                "max_retries_per_ticket": self.config.max_retries_per_ticket,
            }

    def _avg_completion_time(self) -> float | None:
        """Average ticket completion time from rolling window."""
        if not self._completions:
            return None
        return sum(c.duration_seconds for c in self._completions) / len(self._completions)

    def _estimate_remaining(self) -> float | None:
        """Estimate seconds remaining for the current group + future groups."""
        avg = self._avg_completion_time()
        if avg is None or self._current_group_index is None:
            return None

        # Time spent in current group so far
        elapsed_in_group = 0.0
        if self._group_start_time is not None:
            elapsed_in_group = time.monotonic() - self._group_start_time

        # Estimate: remaining tickets in current group * avg / concurrency
        active = max(1, len(self._active_engineers))
        remaining_in_group = max(
            0,
            self._tickets_in_current_group - len(self._completions),
        )
        group_eta = (remaining_in_group * avg / active) - elapsed_in_group

        # Future groups (rough: assume same ticket count)
        future_groups = max(0, self._total_groups - (self._current_group_index + 1))
        future_eta = future_groups * self._tickets_in_current_group * avg / active

        return max(0.0, group_eta + future_eta)


# ---------------------------------------------------------------------------
# Per-pipeline monitor registry (in-process singleton map)
# ---------------------------------------------------------------------------

_monitors: dict[str, ConcurrencyMonitor] = {}
_registry_lock = asyncio.Lock()


async def get_monitor(
    pipeline_id: str,
    config: ConcurrencyConfig | None = None,
) -> ConcurrencyMonitor:
    """Get or create a ConcurrencyMonitor for the given pipeline."""
    async with _registry_lock:
        if pipeline_id not in _monitors:
            _monitors[pipeline_id] = ConcurrencyMonitor(
                pipeline_id,
                config=config,
            )
        return _monitors[pipeline_id]


async def remove_monitor(pipeline_id: str) -> None:
    """Remove a monitor when the pipeline completes."""
    async with _registry_lock:
        _monitors.pop(pipeline_id, None)
