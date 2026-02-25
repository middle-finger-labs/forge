"""FastAPI auth middleware — validates Better Auth sessions.

Extracts session tokens from cookies (browser) or Authorization headers
(API/CLI), validates them against the Better Auth service, and caches
results in Redis for 60 seconds.

Usage::

    from auth.middleware import get_current_user, require_org_admin
    from auth.types import ForgeUser

    @app.get("/api/example")
    async def example(user: ForgeUser = Depends(get_current_user)):
        print(user.org_id)  # scoped to the user's active org
"""

from __future__ import annotations

import hashlib
import json
import os

import httpx
import redis.asyncio as aioredis
import structlog
from fastapi import Depends, HTTPException, Request

from auth.types import ForgeUser

log = structlog.get_logger().bind(component="auth_middleware")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FORGE_AUTH_URL = os.environ.get("FORGE_AUTH_URL", "http://localhost:3100")
FORGE_AUTH_ENABLED = os.environ.get("FORGE_AUTH_ENABLED", "true").lower() in (
    "true",
    "1",
    "yes",
)
REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")

_SESSION_CACHE_TTL = 60  # seconds

# Default user returned when auth is disabled (local dev)
_DEV_USER = ForgeUser(
    user_id="dev-user-000",
    email="dev@localhost",
    name="Dev User",
    org_id="dev-org-000",
    org_slug="dev",
    role="owner",
)

# Cookie name used by Better Auth (with __Secure- prefix when baseURL is HTTPS)
_SESSION_COOKIE = "better-auth.session_token"
_SESSION_COOKIE_SECURE = "__Secure-better-auth.session_token"

# ---------------------------------------------------------------------------
# Shared HTTP client (reused across requests)
# ---------------------------------------------------------------------------

_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    global _http_client  # noqa: PLW0603
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=5.0)
    return _http_client


# ---------------------------------------------------------------------------
# Redis cache helpers
# ---------------------------------------------------------------------------

_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis  # noqa: PLW0603
    if _redis is None:
        _redis = aioredis.from_url(REDIS_URL, decode_responses=True)
    return _redis


def _cache_key(token: str) -> str:
    """Hash the token so we don't store raw session tokens in Redis."""
    token_hash = hashlib.sha256(token.encode()).hexdigest()[:16]
    return f"forge:session:{token_hash}"


async def _get_cached_user(token: str) -> ForgeUser | None:
    """Return a cached ForgeUser or None."""
    try:
        r = _get_redis()
        raw = await r.get(_cache_key(token))
        if raw is None:
            return None
        data = json.loads(raw)
        return ForgeUser(**data)
    except Exception:
        # Cache miss on error — just validate against auth service
        return None


async def _cache_user(token: str, user: ForgeUser) -> None:
    """Store a validated ForgeUser in Redis."""
    try:
        r = _get_redis()
        await r.set(
            _cache_key(token),
            json.dumps({
                "user_id": user.user_id,
                "email": user.email,
                "name": user.name,
                "org_id": user.org_id,
                "org_slug": user.org_slug,
                "role": user.role,
            }),
            ex=_SESSION_CACHE_TTL,
        )
    except Exception as exc:
        log.warning("failed to cache session", error=str(exc))


# ---------------------------------------------------------------------------
# Token extraction
# ---------------------------------------------------------------------------


def _extract_token(request: Request) -> str | None:
    """Extract session token from cookie or Authorization header."""
    # 1. Cookie (browser requests — try __Secure- prefixed first, then plain)
    token = request.cookies.get(_SESSION_COOKIE_SECURE) or request.cookies.get(
        _SESSION_COOKIE
    )
    if token:
        return token

    # 2. Bearer token (API/CLI requests)
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:]

    return None


# ---------------------------------------------------------------------------
# Session validation via Better Auth
# ---------------------------------------------------------------------------


async def _validate_session(token: str) -> ForgeUser:
    """Call Better Auth's get-session endpoint and return a ForgeUser.

    Better Auth returns session + user data. The organization context
    comes from the active organization on the session.
    """
    client = _get_http_client()

    # Forward the token as both cookie variants so Better Auth
    # recognises it regardless of whether it expects the __Secure- prefix.
    headers = {
        "Authorization": f"Bearer {token}",
        "Cookie": (
            f"{_SESSION_COOKIE_SECURE}={token}; "
            f"{_SESSION_COOKIE}={token}"
        ),
    }

    try:
        resp = await client.get(
            f"{FORGE_AUTH_URL}/api/auth/get-session",
            headers=headers,
        )
    except httpx.RequestError as exc:
        log.error("auth service unreachable", error=str(exc))
        raise HTTPException(
            status_code=503,
            detail="Authentication service unavailable",
        )

    if resp.status_code != 200:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    data = resp.json()
    if not data:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    # Better Auth returns { session: {...}, user: {...} }
    session = data.get("session") or {}
    user_data = data.get("user") or {}

    user_id = user_data.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session payload")

    # Fetch the user's active organization membership
    org_id = session.get("activeOrganizationId") or ""
    org_slug = ""
    role = "member"

    if org_id:
        # Retrieve org details + membership for the active org
        try:
            org_resp = await client.get(
                f"{FORGE_AUTH_URL}/api/auth/organization/get-full-organization",
                headers=headers,
            )
            if org_resp.status_code == 200:
                org_data = org_resp.json()
                org_slug = org_data.get("slug", "")
                for member in org_data.get("members", []):
                    if member.get("userId") == user_id:
                        role = member.get("role", "member")
                        break
        except httpx.RequestError:
            log.warning("could not fetch org details, using defaults")
    else:
        # No active org on session — look up the user's org memberships
        # and use the first one as a default.
        try:
            orgs_resp = await client.get(
                f"{FORGE_AUTH_URL}/api/auth/organization/list-organizations",
                headers=headers,
            )
            if orgs_resp.status_code == 200:
                orgs = orgs_resp.json()
                if isinstance(orgs, list) and len(orgs) > 0:
                    first_org = orgs[0]
                    org_id = first_org.get("id", "")
                    org_slug = first_org.get("slug", "")
                    # Try to set as active org so subsequent requests work
                    try:
                        await client.post(
                            f"{FORGE_AUTH_URL}/api/auth/organization/set-active",
                            headers=headers,
                            json={"organizationId": org_id},
                        )
                    except httpx.RequestError:
                        pass
                    # Fetch full org to get role
                    try:
                        org_resp = await client.get(
                            f"{FORGE_AUTH_URL}/api/auth/organization/get-full-organization",
                            headers={
                                **headers,
                                "x-organization-id": org_id,
                            },
                        )
                        if org_resp.status_code == 200:
                            org_data = org_resp.json()
                            org_slug = org_data.get("slug", org_slug)
                            for member in org_data.get("members", []):
                                if member.get("userId") == user_id:
                                    role = member.get("role", "member")
                                    break
                    except httpx.RequestError:
                        pass
        except httpx.RequestError:
            log.warning("could not list user organizations")

    if not org_id:
        raise HTTPException(
            status_code=403,
            detail="User does not belong to any organization",
        )

    return ForgeUser(
        user_id=user_id,
        email=user_data.get("email", ""),
        name=user_data.get("name", ""),
        org_id=org_id,
        org_slug=org_slug,
        role=role,
    )


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------


async def get_current_user(request: Request) -> ForgeUser:
    """Validate session and return the authenticated user with org context.

    When ``FORGE_AUTH_ENABLED`` is False (local dev), returns a stub user
    so the API can run without the auth service.
    """
    if not FORGE_AUTH_ENABLED:
        return _DEV_USER

    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing session token")

    # Check Redis cache first
    cached = await _get_cached_user(token)
    if cached is not None:
        return cached

    # Validate against Better Auth
    user = await _validate_session(token)

    # Cache for subsequent requests
    await _cache_user(token, user)

    return user


async def require_org_admin(
    user: ForgeUser = Depends(get_current_user),
) -> ForgeUser:
    """Require owner or admin role within the org."""
    if not user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="Admin or owner role required",
        )
    return user


async def require_org_member(
    user: ForgeUser = Depends(get_current_user),
) -> ForgeUser:
    """Require any authenticated org member (owner, admin, or member)."""
    # get_current_user already ensures org membership (403 if no org_id),
    # so this is effectively the same — but exists as a semantic marker.
    return user
