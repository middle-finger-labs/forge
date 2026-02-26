"""Magic link authentication routes.

Handles org invitations, invite completion, and team management.
Standard magic link sign-in and verification are handled directly
by Better Auth; this module provides the invite-specific logic
and team endpoints that wrap BA's primitives.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timedelta, timezone

import asyncpg
import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr

from auth.middleware import get_current_user, require_org_admin
from auth.types import ForgeUser

log = structlog.get_logger().bind(component="magic_link")

auth_router = APIRouter(prefix="/api/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SERVER_PUBLIC_URL = os.environ.get("FORGE_PUBLIC_URL", "http://localhost:8000")
AUTH_SERVICE_URL = os.environ.get("AUTH_SERVICE_URL", "http://forge-auth:3100")
MAGIC_LINK_TTL_MINUTES = 15
MAGIC_LINK_RATE_LIMIT = 3  # max links per email per TTL window
# Deep link scheme for the desktop/mobile app
DEEP_LINK_SCHEME = "forge"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_db(request: Request) -> asyncpg.Pool:
    """Retrieve the shared DB pool from app state."""
    from api.server import _get_db
    return _get_db()


async def _check_rate_limit(pool: asyncpg.Pool, email: str) -> bool:
    """Return True if the email has exceeded the rate limit."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=MAGIC_LINK_TTL_MINUTES)
    count = await pool.fetchval(
        """
        SELECT COUNT(*) FROM magic_links
        WHERE email = $1 AND created_at > $2
        """,
        email.lower(),
        cutoff,
    )
    return (count or 0) >= MAGIC_LINK_RATE_LIMIT


async def _create_pending_magic_link(
    pool: asyncpg.Pool,
    *,
    email: str,
    purpose: str,
    org_id: str | None = None,
    invite_by: str | None = None,
) -> None:
    """Create a magic_links record with a __pending__ placeholder token.

    BA's sendMagicLink callback will update this record with the real
    token via the internal endpoint.
    """
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=MAGIC_LINK_TTL_MINUTES)

    await pool.execute(
        """
        INSERT INTO magic_links (email, token, server_url, org_id, invite_by, purpose, expires_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        """,
        email.lower(),
        "__pending__",
        SERVER_PUBLIC_URL,
        org_id,
        invite_by,
        purpose,
        expires_at,
    )


async def _request_ba_magic_link(email: str) -> bool:
    """Ask Better Auth to generate a magic link token for the given email.

    BA will call our internal endpoint (sendMagicLink callback) to
    deliver the token and trigger email sending.

    Returns True on success, False on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{AUTH_SERVICE_URL}/api/auth/sign-in/magic-link",
                json={"email": email},
            )
            if resp.status_code == 200:
                return True
            log.warning(
                "BA magic-link request failed",
                status=resp.status_code,
                body=resp.text[:200],
            )
            return False
    except httpx.RequestError as exc:
        log.error("BA magic-link request error", error=str(exc))
        return False


def _build_links(token: str) -> tuple[str, str]:
    """Return (deep_link, web_link) for a magic link token."""
    deep_link = f"{DEEP_LINK_SCHEME}://auth?token={token}&server={SERVER_PUBLIC_URL}"
    web_link = f"{SERVER_PUBLIC_URL}/auth/magic?token={token}"
    return deep_link, web_link


async def _send_magic_email(
    *,
    to: str,
    purpose: str,
    token: str,
    inviter_name: str | None = None,
    org_name: str | None = None,
) -> None:
    """Render and send the magic link email."""
    from api.emails.sender import render_template, send_email

    deep_link, web_link = _build_links(token)

    if purpose == "invite":
        subject = f"{inviter_name or 'Someone'} invited you to Forge"
        heading = f"You've been invited to join {org_name or 'a workspace'} on Forge"
        body_text = (
            f"{inviter_name or 'A team member'} invited you to join the "
            f"{org_name or ''} workspace on Forge. Click the button below to "
            f"accept the invitation. This link expires in {MAGIC_LINK_TTL_MINUTES} minutes."
        )
        cta_text = f"Join {org_name or 'Forge'}"
    else:
        subject = "Sign in to Forge"
        heading = "Sign in to Forge"
        body_text = (
            f"Click the button below to sign in. "
            f"This link expires in {MAGIC_LINK_TTL_MINUTES} minutes."
        )
        cta_text = "Sign in to Forge"

    html = render_template(
        "magic_link.html",
        subject=subject,
        heading=heading,
        body_text=body_text,
        cta_text=cta_text,
        deep_link=deep_link,
        web_link=web_link,
    )

    await send_email(to, subject, html)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class InviteRequest(BaseModel):
    email: EmailStr
    role: str = "member"


# ---------------------------------------------------------------------------
# POST /api/auth/magic-link/complete-invite  — Finalise invite membership
# ---------------------------------------------------------------------------


@auth_router.post("/magic-link/complete-invite")
async def complete_invite(
    request: Request,
    user: ForgeUser = Depends(get_current_user),
):
    """Complete an invite after BA verification.

    Called by the desktop app after a magic link verify succeeds.  Looks up
    the most recent unused invite for the authenticated user's email, adds
    org membership if needed, and marks the invite as used.

    Non-critical — the desktop client wraps this in try/catch.
    """
    pool = _get_db(request)
    now = datetime.now(timezone.utc)
    email = user.email.lower()

    # Find the most recent pending invite for this email
    row = await pool.fetchrow(
        """
        SELECT id, org_id, invite_by
        FROM magic_links
        WHERE email = $1
          AND purpose = 'invite'
          AND used_at IS NULL
          AND expires_at > $2
        ORDER BY created_at DESC
        LIMIT 1
        """,
        email,
        now,
    )

    if row is None:
        # No pending invite — nothing to do (normal for regular logins)
        return {"status": "no_invite"}

    org_id = str(row["org_id"]) if row["org_id"] else None
    if not org_id:
        return {"status": "no_invite"}

    # Add user to org if not already a member
    existing_member = await pool.fetchval(
        """
        SELECT id FROM "member"
        WHERE "userId" = $1 AND "organizationId" = $2
        """,
        user.user_id,
        org_id,
    )

    if not existing_member:
        await pool.execute(
            """
            INSERT INTO "member" (id, "userId", "organizationId", role, "createdAt")
            VALUES ($1, $2, $3, $4, $5)
            """,
            str(uuid.uuid4()),
            user.user_id,
            org_id,
            "member",
            now,
        )
        log.info("invite membership created", user_id=user.user_id, org_id=org_id)

    # Mark the invite as used
    await pool.execute(
        "UPDATE magic_links SET used_at = $1 WHERE id = $2",
        now,
        row["id"],
    )

    return {"status": "joined", "org_id": org_id}


# ---------------------------------------------------------------------------
# POST /api/auth/invite  — Send an org invitation (admin only)
# ---------------------------------------------------------------------------


@auth_router.post("/invite")
async def send_invite(
    body: InviteRequest,
    request: Request,
    user: ForgeUser = Depends(require_org_admin),
):
    """Send a magic link invitation to join the user's org."""
    pool = _get_db(request)
    email = body.email.lower()

    if body.role not in ("member", "admin"):
        raise HTTPException(status_code=400, detail="Role must be 'member' or 'admin'")

    # Rate limit applies to invites too
    if await _check_rate_limit(pool, email):
        raise HTTPException(status_code=429, detail="Too many invites sent to this email")

    # Create a pending record with invite context — BA's callback will
    # update with the real token and send an invite-flavored email.
    await _create_pending_magic_link(
        pool,
        email=email,
        purpose="invite",
        org_id=user.org_id,
        invite_by=user.user_id,
    )

    # Ask BA to generate a token — callback sends the email
    success = await _request_ba_magic_link(email)
    if not success:
        log.error("BA failed to generate invite magic link", email=email)
        raise HTTPException(status_code=500, detail="Failed to send invitation email")

    log.info("invite sent", email=email, org_id=user.org_id, invited_by=user.user_id)

    return {
        "message": "Invite sent",
        "email": email,
    }


# ---------------------------------------------------------------------------
# GET /api/auth/team/members  — List org members
# ---------------------------------------------------------------------------


@auth_router.get("/team/members")
async def team_members(
    request: Request,
    user: ForgeUser = Depends(get_current_user),
):
    """List all members of the user's organization."""
    pool = _get_db(request)

    rows = await pool.fetch(
        """
        SELECT u.id, u.email, u.name, m.role, m."createdAt" AS joined_at
        FROM "member" m
        JOIN "user" u ON u.id = m."userId"
        WHERE m."organizationId" = $1
        ORDER BY m."createdAt" ASC
        """,
        user.org_id,
    )

    return [
        {
            "id": r["id"],
            "email": r["email"],
            "name": r["name"],
            "role": r["role"],
            "joined_at": r["joined_at"].isoformat() if r["joined_at"] else None,
        }
        for r in rows
    ]


# ---------------------------------------------------------------------------
# GET /api/auth/team/invites  — List pending invites
# ---------------------------------------------------------------------------


@auth_router.get("/team/invites")
async def team_invites(
    request: Request,
    user: ForgeUser = Depends(get_current_user),
):
    """List pending (unused, unexpired) invites for the user's organization."""
    pool = _get_db(request)
    now = datetime.now(timezone.utc)

    rows = await pool.fetch(
        """
        SELECT ml.email, ml.created_at, ml.expires_at,
               u.name AS invited_by_name, u.email AS invited_by_email
        FROM magic_links ml
        LEFT JOIN "user" u ON u.id = ml.invite_by
        WHERE ml.org_id = $1
          AND ml.purpose = 'invite'
          AND ml.used_at IS NULL
          AND ml.expires_at > $2
        ORDER BY ml.created_at DESC
        """,
        user.org_id,
        now,
    )

    return [
        {
            "email": r["email"],
            "invited_by": r["invited_by_name"] or r["invited_by_email"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
            "expires_at": r["expires_at"].isoformat() if r["expires_at"] else None,
        }
        for r in rows
    ]
