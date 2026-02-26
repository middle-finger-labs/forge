"""Internal service-to-service endpoints.

These endpoints are called by the auth service (Better Auth's sendMagicLink
callback) and are protected by a shared secret, not user sessions.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone

import asyncpg
import structlog
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

log = structlog.get_logger().bind(component="internal")

internal_router = APIRouter(prefix="/api/internal", tags=["internal"])

INTERNAL_API_SECRET = os.environ.get("INTERNAL_API_SECRET", "")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_db(request: Request) -> asyncpg.Pool:
    from api.server import _get_db
    return _get_db()


def _validate_internal_secret(request: Request) -> None:
    """Validate the X-Internal-Secret header."""
    if not INTERNAL_API_SECRET:
        log.warning("INTERNAL_API_SECRET not configured, rejecting request")
        raise HTTPException(status_code=403, detail="Internal endpoint not configured")
    secret = request.headers.get("X-Internal-Secret", "")
    if secret != INTERNAL_API_SECRET:
        raise HTTPException(status_code=403, detail="Invalid internal secret")


# ---------------------------------------------------------------------------
# Request model
# ---------------------------------------------------------------------------


class SendMagicEmailRequest(BaseModel):
    email: str
    token: str
    url: str


# ---------------------------------------------------------------------------
# POST /api/internal/send-magic-email
# ---------------------------------------------------------------------------


@internal_router.post("/send-magic-email")
async def send_magic_email(body: SendMagicEmailRequest, request: Request):
    """Receive BA's sendMagicLink callback, update the pending magic_links
    record with BA's token, and dispatch the email.

    Called by the auth service, NOT by end users.
    """
    _validate_internal_secret(request)

    pool = _get_db(request)
    email = body.email.lower()

    # Update the most recent __pending__ record for this email with BA's token
    updated = await pool.execute(
        """
        UPDATE magic_links
        SET token = $1
        WHERE id = (
            SELECT id FROM magic_links
            WHERE email = $2 AND token = '__pending__'
            ORDER BY created_at DESC
            LIMIT 1
        )
        """,
        body.token,
        email,
    )

    if updated == "UPDATE 0":
        log.info(
            "no pending magic_link found, inserting record for BA-direct flow",
            email=email,
        )
        # BA-direct flow: the client called BA's sign-in/magic-link endpoint
        # directly, so no __pending__ record exists.  Insert one to maintain
        # the audit trail and keep the web landing page working.
        from api.routes.auth import MAGIC_LINK_TTL_MINUTES, SERVER_PUBLIC_URL

        expires_at = datetime.now(timezone.utc) + timedelta(minutes=MAGIC_LINK_TTL_MINUTES)
        await pool.execute(
            """
            INSERT INTO magic_links (email, token, server_url, purpose, expires_at)
            VALUES ($1, $2, $3, $4, $5)
            """,
            email,
            body.token,
            SERVER_PUBLIC_URL,
            "login",
            expires_at,
        )

    # Read invite context from magic_links (purpose, org_id, invite_by)
    row = await pool.fetchrow(
        """
        SELECT purpose, org_id, invite_by
        FROM magic_links
        WHERE token = $1
        ORDER BY created_at DESC
        LIMIT 1
        """,
        body.token,
    )

    purpose = row["purpose"] if row else "login"
    inviter_name = None
    org_name = None

    if row and row["invite_by"]:
        inviter_row = await pool.fetchrow(
            'SELECT name FROM "user" WHERE id = $1',
            row["invite_by"],
        )
        if inviter_row:
            inviter_name = inviter_row["name"]

    if row and row["org_id"]:
        org_row = await pool.fetchrow(
            'SELECT name FROM "organization" WHERE id = $1',
            row["org_id"],
        )
        if org_row:
            org_name = org_row["name"]

    # Send the email using existing helper
    try:
        from api.routes.auth import _send_magic_email

        await _send_magic_email(
            to=email,
            purpose=purpose,
            token=body.token,
            inviter_name=inviter_name,
            org_name=org_name,
        )
    except Exception as exc:
        log.error("failed to send magic email via internal endpoint", error=str(exc))
        # Don't fail the callback — BA doesn't need to know about email errors

    return {"status": "ok"}
