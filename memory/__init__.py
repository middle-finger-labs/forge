"""Forge memory layer — persistent state and cross-pipeline learning.

Provides singletons for the two memory backends:

- ``get_state_store()`` — PostgreSQL-backed durable state (pipeline runs,
  events, ticket executions).
- ``get_working_memory()`` — Redis-backed ephemeral state (ticket locks,
  active agents, artifact caching, event pub/sub).
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memory.state_store import StateStore
    from memory.working_memory import WorkingMemory

_instance: StateStore | None = None
_wm_instance: WorkingMemory | None = None


def get_state_store() -> StateStore:
    """Return the process-wide StateStore singleton.

    Reads ``DATABASE_URL`` from the environment on first invocation.
    The underlying asyncpg connection pool is created lazily when the
    first async method is called.
    """
    global _instance  # noqa: PLW0603
    if _instance is None:
        from memory.state_store import StateStore

        dsn = os.environ.get(
            "DATABASE_URL",
            "postgresql://forge:forge_dev_password@localhost:5432/forge_app",
        )
        _instance = StateStore(dsn)
    return _instance


def get_working_memory() -> WorkingMemory:
    """Return the process-wide WorkingMemory singleton.

    Reads ``REDIS_URL`` from the environment on first invocation.
    """
    global _wm_instance  # noqa: PLW0603
    if _wm_instance is None:
        from memory.working_memory import WorkingMemory

        redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
        _wm_instance = WorkingMemory(redis_url)
    return _wm_instance


__all__ = ["get_state_store", "get_working_memory"]
