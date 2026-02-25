"""Magic link authentication routes.

Provides passwordless auth via email magic links and org invitations.
"""

from __future__ import annotations

import os
import secrets
from datetime import datetime, timedelta, timezone

import asyncpg
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
MAGIC_LINK_TTL_MINUTES = 15
MAGIC_LINK_RATE_LIMIT = 3  # max links per email per TTL window
RESEND_COOLDOWN_SECONDS = 60  # minimum seconds between magic links for same email

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


async def _check_resend_cooldown(pool: asyncpg.Pool, email: str) -> int | None:
    """Return remaining cooldown seconds if the email sent a link too recently, else None."""
    row = await pool.fetchrow(
        """
        SELECT created_at FROM magic_links
        WHERE email = $1
        ORDER BY created_at DESC
        LIMIT 1
        """,
        email.lower(),
    )
    if row is None:
        return None
    elapsed = (datetime.now(timezone.utc) - row["created_at"]).total_seconds()
    if elapsed < RESEND_COOLDOWN_SECONDS:
        return int(RESEND_COOLDOWN_SECONDS - elapsed)
    return None


async def _create_magic_link(
    pool: asyncpg.Pool,
    *,
    email: str,
    purpose: str,
    org_id: str | None = None,
    invite_by: str | None = None,
) -> str:
    """Create a magic link record and return the token."""
    token = secrets.token_urlsafe(48)
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=MAGIC_LINK_TTL_MINUTES)

    await pool.execute(
        """
        INSERT INTO magic_links (email, token, server_url, org_id, invite_by, purpose, expires_at)
        VALUES ($1, $2, $3, $4::uuid, $5::uuid, $6, $7)
        """,
        email.lower(),
        token,
        SERVER_PUBLIC_URL,
        org_id,
        invite_by,
        purpose,
        expires_at,
    )
    return token


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


class MagicLinkRequest(BaseModel):
    email: EmailStr


class MagicLinkVerifyRequest(BaseModel):
    token: str


class InviteRequest(BaseModel):
    email: EmailStr
    role: str = "member"


# ---------------------------------------------------------------------------
# POST /api/auth/magic-link  — Request a magic link
# ---------------------------------------------------------------------------


@auth_router.post("/magic-link")
async def request_magic_link(body: MagicLinkRequest, request: Request):
    """Send a magic link email for passwordless login.

    Always returns 200 with "check your email" to avoid revealing
    whether an account exists.
    """
    pool = _get_db(request)
    email = body.email.lower()

    # Rate limit
    if await _check_rate_limit(pool, email):
        # Still return 200 to not leak info, but don't send
        log.warning("magic link rate limited", email=email)
        return {"message": "If that email is registered, check your inbox."}

    # Resend cooldown — return remaining seconds so client can show timer
    cooldown = await _check_resend_cooldown(pool, email)
    if cooldown is not None:
        log.info("magic link resend cooldown active", email=email, remaining=cooldown)
        return {
            "message": "If that email is registered, check your inbox.",
            "cooldown_remaining": cooldown,
        }

    # Look up user in Better Auth's user table
    user_row = await pool.fetchrow(
        "SELECT id, email, name FROM \"user\" WHERE LOWER(email) = $1",
        email,
    )

    if user_row is None:
        # User doesn't exist — return same message but don't send email
        log.info("magic link requested for unknown email", email=email)
        return {"message": "If that email is registered, check your inbox."}

    # Find the user's org
    member_row = await pool.fetchrow(
        """
        SELECT m."organizationId" AS org_id, o.name AS org_name
        FROM "member" m
        JOIN "organization" o ON o.id = m."organizationId"
        WHERE m."userId" = $1
        LIMIT 1
        """,
        user_row["id"],
    )

    org_id = member_row["org_id"] if member_row else None

    token = await _create_magic_link(
        pool,
        email=email,
        purpose="login",
        org_id=org_id,
    )

    try:
        await _send_magic_email(to=email, purpose="login", token=token)
    except Exception as exc:
        log.error("failed to send magic link email", email=email, error=str(exc))
        # Don't expose email delivery errors to client

    return {"message": "If that email is registered, check your inbox."}


# ---------------------------------------------------------------------------
# POST /api/auth/magic-link/verify  — Consume a magic link token
# ---------------------------------------------------------------------------


@auth_router.post("/magic-link/verify")
async def verify_magic_link(body: MagicLinkVerifyRequest, request: Request):
    """Verify a magic link token, create a session, and return auth data.

    This is called by the desktop app after the user taps the magic link.
    """
    pool = _get_db(request)
    now = datetime.now(timezone.utc)

    # Find the magic link
    row = await pool.fetchrow(
        """
        SELECT id, email, token, server_url, org_id, invite_by, purpose, expires_at, used_at
        FROM magic_links
        WHERE token = $1
        """,
        body.token,
    )

    if row is None:
        raise HTTPException(status_code=400, detail="Invalid or expired link")

    if row["expires_at"] < now:
        raise HTTPException(status_code=400, detail="This link has expired")

    # Idempotent verify: if already consumed within the last 5 minutes, return
    # the existing session so polling clients can retrieve the result.
    if row["used_at"] is not None:
        consumed_ago = (now - row["used_at"]).total_seconds()
        if consumed_ago <= 300:
            # Find the existing session for this user
            email = row["email"]
            user_row = await pool.fetchrow(
                "SELECT id, email, name FROM \"user\" WHERE LOWER(email) = $1",
                email.lower(),
            )
            if user_row:
                session_row = await pool.fetchrow(
                    """
                    SELECT token, "expiresAt", "activeOrganizationId"
                    FROM "session"
                    WHERE "userId" = $1 AND "expiresAt" > $2
                    ORDER BY "createdAt" DESC LIMIT 1
                    """,
                    user_row["id"],
                    now,
                )
                if session_row:
                    org_data = None
                    org_id = str(session_row["activeOrganizationId"]) if session_row["activeOrganizationId"] else None
                    if org_id:
                        org_row = await pool.fetchrow(
                            "SELECT id, name, slug FROM \"organization\" WHERE id = $1",
                            org_id,
                        )
                        if org_row:
                            org_data = dict(org_row)
                    role = "member"
                    if org_id:
                        role_val = await pool.fetchval(
                            "SELECT role FROM \"member\" WHERE \"userId\" = $1 AND \"organizationId\" = $2",
                            user_row["id"],
                            org_id,
                        )
                        if role_val:
                            role = role_val
                    return {
                        "session_token": session_row["token"],
                        "user": {
                            "id": user_row["id"],
                            "email": user_row["email"],
                            "name": user_row["name"],
                            "role": role,
                        },
                        "org": org_data,
                        "server_url": row["server_url"],
                        "is_new_user": False,
                    }
        raise HTTPException(status_code=400, detail="This link has already been used")

    # Mark as used
    await pool.execute(
        "UPDATE magic_links SET used_at = $1 WHERE id = $2",
        now,
        row["id"],
    )

    email = row["email"]
    purpose = row["purpose"]
    is_new_user = False

    # Look up or create user
    user_row = await pool.fetchrow(
        "SELECT id, email, name FROM \"user\" WHERE LOWER(email) = $1",
        email.lower(),
    )

    if purpose == "invite":
        org_id = str(row["org_id"]) if row["org_id"] else None

        if user_row is None:
            # Create new user via Better Auth's user table
            import uuid
            new_user_id = str(uuid.uuid4())
            name = email.split("@")[0]
            await pool.execute(
                """
                INSERT INTO "user" (id, email, name, "emailVerified", "createdAt", "updatedAt")
                VALUES ($1, $2, $3, true, $4, $4)
                """,
                new_user_id,
                email,
                name,
                now,
            )
            user_row = {"id": new_user_id, "email": email, "name": name}
            is_new_user = True

        # Add to org if not already a member
        if org_id:
            existing_member = await pool.fetchval(
                """
                SELECT id FROM "member"
                WHERE "userId" = $1 AND "organizationId" = $2
                """,
                user_row["id"],
                org_id,
            )
            if not existing_member:
                import uuid
                await pool.execute(
                    """
                    INSERT INTO "member" (id, "userId", "organizationId", role, "createdAt")
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    str(uuid.uuid4()),
                    user_row["id"],
                    org_id,
                    "member",
                    now,
                )
    elif user_row is None:
        # Login purpose but user doesn't exist (shouldn't happen since we
        # only create login links for existing users, but handle gracefully)
        raise HTTPException(status_code=400, detail="Invalid or expired link")

    # Create a session (Better Auth session table)
    import uuid
    session_token = secrets.token_urlsafe(48)
    session_id = str(uuid.uuid4())
    session_expires = now + timedelta(days=7)

    await pool.execute(
        """
        INSERT INTO "session" (id, "userId", token, "expiresAt", "createdAt", "updatedAt",
                               "activeOrganizationId")
        VALUES ($1, $2, $3, $4, $5, $5, $6)
        """,
        session_id,
        user_row["id"],
        session_token,
        session_expires,
        now,
        str(row["org_id"]) if row["org_id"] else None,
    )

    # Fetch org details
    org_data = None
    org_id = str(row["org_id"]) if row["org_id"] else None
    if not org_id:
        # Try to find user's org
        member_row = await pool.fetchrow(
            """
            SELECT m."organizationId" AS org_id, o.name AS org_name, o.slug, m.role
            FROM "member" m
            JOIN "organization" o ON o.id = m."organizationId"
            WHERE m."userId" = $1
            LIMIT 1
            """,
            user_row["id"],
        )
        if member_row:
            org_id = member_row["org_id"]
            org_data = {
                "id": member_row["org_id"],
                "name": member_row["org_name"],
                "slug": member_row["slug"],
            }
            # Update session with org
            await pool.execute(
                "UPDATE \"session\" SET \"activeOrganizationId\" = $1 WHERE id = $2",
                org_id,
                session_id,
            )
    else:
        org_row = await pool.fetchrow(
            "SELECT id, name, slug FROM \"organization\" WHERE id = $1",
            org_id,
        )
        if org_row:
            org_data = dict(org_row)

    # Get user's role in org
    role = "member"
    if org_id:
        role_val = await pool.fetchval(
            "SELECT role FROM \"member\" WHERE \"userId\" = $1 AND \"organizationId\" = $2",
            user_row["id"],
            org_id,
        )
        if role_val:
            role = role_val

    return {
        "session_token": session_token,
        "user": {
            "id": user_row["id"],
            "email": user_row["email"],
            "name": user_row["name"],
            "role": role,
        },
        "org": org_data,
        "server_url": row["server_url"],
        "is_new_user": is_new_user,
    }


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

    # Get org name for the email
    org_row = await pool.fetchrow(
        "SELECT name FROM \"organization\" WHERE id = $1",
        user.org_id,
    )
    org_name = org_row["name"] if org_row else None

    token = await _create_magic_link(
        pool,
        email=email,
        purpose="invite",
        org_id=user.org_id,
        invite_by=user.user_id,
    )

    try:
        await _send_magic_email(
            to=email,
            purpose="invite",
            token=token,
            inviter_name=user.name,
            org_name=org_name,
        )
    except Exception as exc:
        log.error("failed to send invite email", email=email, error=str(exc))
        raise HTTPException(status_code=500, detail="Failed to send invitation email")

    log.info("invite sent", email=email, org_id=user.org_id, invited_by=user.user_id)

    return {
        "message": "Invite sent",
        "invite_id": token[:8] + "...",
        "email": email,
    }


# ---------------------------------------------------------------------------
# GET /api/auth/magic-link/status  — Poll magic link status
# ---------------------------------------------------------------------------


@auth_router.get("/magic-link/status")
async def magic_link_status(email: str, request: Request):
    """Check the status of the most recent magic link for an email.

    Used by the desktop app to poll for cross-device completion.
    Returns status: pending | consumed | expired | not_found.
    When consumed, includes the token so the client can call verify.
    """
    pool = _get_db(request)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=MAGIC_LINK_TTL_MINUTES)

    row = await pool.fetchrow(
        """
        SELECT token, expires_at, used_at
        FROM magic_links
        WHERE email = $1 AND created_at > $2
        ORDER BY created_at DESC
        LIMIT 1
        """,
        email.lower(),
        cutoff,
    )

    if row is None:
        return {"status": "not_found"}

    if row["used_at"] is not None:
        return {"status": "consumed", "token": row["token"]}

    if row["expires_at"] < now:
        return {"status": "expired"}

    return {"status": "pending"}


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
