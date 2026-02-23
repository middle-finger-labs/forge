"""Shared fixtures and markers for Forge tests.

Infrastructure tests (PostgreSQL, Redis) are marked with
``@pytest.mark.integration`` and are **automatically skipped** when the
corresponding service is not available.

Existing unit tests and Temporal integration tests continue to run
without any infrastructure.
"""

from __future__ import annotations

import os
import socket

import pytest

# ---------------------------------------------------------------------------
# Custom markers
# ---------------------------------------------------------------------------


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: mark test as requiring external infrastructure (PostgreSQL, Redis)",
    )
    config.addinivalue_line(
        "markers",
        "e2e: end-to-end tests requiring full production stack (set FORGE_E2E=1)",
    )


# ---------------------------------------------------------------------------
# Infrastructure availability probes
# ---------------------------------------------------------------------------


def _port_open(host: str, port: int, timeout: float = 2.0) -> bool:
    """Return True if a TCP connection can be established."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# Cache the results so we only probe once per session
_pg_ok: bool | None = None
_redis_ok: bool | None = None


def _check_pg() -> bool:
    global _pg_ok  # noqa: PLW0603
    if _pg_ok is None:
        _pg_ok = _port_open("localhost", 5432)
    return _pg_ok


def _check_redis() -> bool:
    global _redis_ok  # noqa: PLW0603
    if _redis_ok is None:
        _redis_ok = _port_open("localhost", 6379)
    return _redis_ok


# ---------------------------------------------------------------------------
# Fixtures for infrastructure tests
# ---------------------------------------------------------------------------


@pytest.fixture
def pg_dsn() -> str:
    """Return the PostgreSQL DSN, skipping if unavailable."""
    if not _check_pg():
        pytest.skip("PostgreSQL not available")
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://forge:forge_dev_password@localhost:5432/forge_app",
    )


@pytest.fixture
def redis_url() -> str:
    """Return the Redis URL, skipping if unavailable."""
    if not _check_redis():
        pytest.skip("Redis not available")
    return os.environ.get("REDIS_URL", "redis://localhost:6379/0")
