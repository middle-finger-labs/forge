"""Push notification management and delivery.

Handles device token registration (APNs for iOS, FCM for Android) and
provides an internal ``send_push`` function used by the event pipeline
to deliver notifications when the app is backgrounded or closed.

Usage::

    from api.routes.push import push_router, send_push
    app.include_router(push_router)
"""

from __future__ import annotations

import json
import os
import time
import uuid
from typing import Any

import asyncpg
import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth.middleware import get_current_user
from auth.types import ForgeUser

log = structlog.get_logger().bind(component="api.push")

push_router = APIRouter(prefix="/api/push", tags=["push"])

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# APNs
APNS_KEY_ID = os.environ.get("APNS_KEY_ID", "")
APNS_TEAM_ID = os.environ.get("APNS_TEAM_ID", "")
APNS_KEY_PATH = os.environ.get("APNS_KEY_PATH", "")  # Path to .p8 file
APNS_BUNDLE_ID = os.environ.get("APNS_BUNDLE_ID", "com.middlefingerlabs.forge")
APNS_USE_SANDBOX = os.environ.get("APNS_USE_SANDBOX", "true").lower() == "true"

# FCM
FCM_SERVICE_ACCOUNT_PATH = os.environ.get("FCM_SERVICE_ACCOUNT_PATH", "")
FCM_PROJECT_ID = os.environ.get("FCM_PROJECT_ID", "")

# ---------------------------------------------------------------------------
# DB accessor (imported from server at runtime to avoid circular deps)
# ---------------------------------------------------------------------------


def _get_db() -> asyncpg.Pool:
    from api.server import _get_db as get_db

    return get_db()


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class RegisterTokenRequest(BaseModel):
    platform: str  # "ios" | "android"
    token: str
    device_name: str | None = None
    app_version: str | None = None


class RegisterTokenResponse(BaseModel):
    id: str
    platform: str
    registered: bool


class UnregisterTokenRequest(BaseModel):
    token: str


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@push_router.post("/register", response_model=RegisterTokenResponse)
async def register_device_token(
    body: RegisterTokenRequest,
    user: ForgeUser = Depends(get_current_user),
):
    """Register a device push token (APNs or FCM)."""
    if body.platform not in ("ios", "android"):
        raise HTTPException(status_code=400, detail="platform must be 'ios' or 'android'")

    if not body.token or len(body.token) < 10:
        raise HTTPException(status_code=400, detail="Invalid device token")

    db = _get_db()

    # Upsert: if token already exists, update user/org/metadata
    row = await db.fetchrow(
        """
        INSERT INTO push_tokens (id, user_id, org_id, platform, token, device_name, app_version, last_used_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, now())
        ON CONFLICT (token) DO UPDATE SET
            user_id = EXCLUDED.user_id,
            org_id = EXCLUDED.org_id,
            device_name = EXCLUDED.device_name,
            app_version = EXCLUDED.app_version,
            last_used_at = now()
        RETURNING id
        """,
        uuid.uuid4(),
        uuid.UUID(user.id),
        uuid.UUID(user.org_id),
        body.platform,
        body.token,
        body.device_name,
        body.app_version,
    )

    log.info(
        "push_token_registered",
        user_id=user.id,
        platform=body.platform,
        token_prefix=body.token[:12] + "...",
    )

    return RegisterTokenResponse(
        id=str(row["id"]),
        platform=body.platform,
        registered=True,
    )


@push_router.delete("/unregister")
async def unregister_device_token(
    body: UnregisterTokenRequest,
    user: ForgeUser = Depends(get_current_user),
):
    """Remove a device push token (e.g., on logout)."""
    db = _get_db()

    result = await db.execute(
        "DELETE FROM push_tokens WHERE token = $1 AND user_id = $2",
        body.token,
        uuid.UUID(user.id),
    )

    log.info(
        "push_token_unregistered",
        user_id=user.id,
        token_prefix=body.token[:12] + "...",
        deleted=result,
    )

    return {"unregistered": True}


# ---------------------------------------------------------------------------
# APNs JWT generation
# ---------------------------------------------------------------------------

_apns_jwt_cache: dict[str, Any] = {"token": None, "issued_at": 0}


def _get_apns_jwt() -> str:
    """Generate or return cached APNs JWT (valid for ~50 min, refresh at 45)."""
    import jwt as pyjwt

    now = int(time.time())
    if _apns_jwt_cache["token"] and now - _apns_jwt_cache["issued_at"] < 2700:
        return _apns_jwt_cache["token"]

    if not APNS_KEY_PATH or not APNS_KEY_ID or not APNS_TEAM_ID:
        raise RuntimeError("APNs credentials not configured")

    with open(APNS_KEY_PATH) as f:
        private_key = f.read()

    token = pyjwt.encode(
        {"iss": APNS_TEAM_ID, "iat": now},
        private_key,
        algorithm="ES256",
        headers={"kid": APNS_KEY_ID},
    )

    _apns_jwt_cache["token"] = token
    _apns_jwt_cache["issued_at"] = now
    return token


# ---------------------------------------------------------------------------
# FCM access token
# ---------------------------------------------------------------------------

_fcm_token_cache: dict[str, Any] = {"token": None, "expires_at": 0}


async def _get_fcm_access_token() -> str:
    """Get OAuth2 access token for FCM v1 API using service account."""
    import jwt as pyjwt

    now = int(time.time())
    if _fcm_token_cache["token"] and now < _fcm_token_cache["expires_at"] - 60:
        return _fcm_token_cache["token"]

    if not FCM_SERVICE_ACCOUNT_PATH:
        raise RuntimeError("FCM service account not configured")

    with open(FCM_SERVICE_ACCOUNT_PATH) as f:
        sa = json.load(f)

    # Create JWT for token exchange
    claim_set = {
        "iss": sa["client_email"],
        "scope": "https://www.googleapis.com/auth/firebase.messaging",
        "aud": sa["token_uri"],
        "iat": now,
        "exp": now + 3600,
    }

    signed_jwt = pyjwt.encode(claim_set, sa["private_key"], algorithm="RS256")

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            sa["token_uri"],
            data={
                "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer",
                "assertion": signed_jwt,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    _fcm_token_cache["token"] = data["access_token"]
    _fcm_token_cache["expires_at"] = now + data.get("expires_in", 3600)
    return data["access_token"]


# ---------------------------------------------------------------------------
# Push delivery
# ---------------------------------------------------------------------------


async def _send_apns(token: str, title: str, body: str, data: dict | None = None):
    """Send a push notification via APNs HTTP/2."""
    jwt_token = _get_apns_jwt()

    host = (
        "https://api.sandbox.push.apple.com"
        if APNS_USE_SANDBOX
        else "https://api.push.apple.com"
    )

    payload = {
        "aps": {
            "alert": {"title": title, "body": body},
            "sound": "default",
            "badge": 1,
        },
    }
    if data:
        payload["data"] = data

    async with httpx.AsyncClient(http2=True) as client:
        resp = await client.post(
            f"{host}/3/device/{token}",
            json=payload,
            headers={
                "authorization": f"bearer {jwt_token}",
                "apns-topic": APNS_BUNDLE_ID,
                "apns-push-type": "alert",
                "apns-priority": "10",
            },
        )

        if resp.status_code == 410:
            # Token is no longer valid — clean up
            db = _get_db()
            await db.execute("DELETE FROM push_tokens WHERE token = $1", token)
            log.info("apns_token_expired", token_prefix=token[:12] + "...")
        elif resp.status_code != 200:
            log.error(
                "apns_send_failed",
                status=resp.status_code,
                body=resp.text,
                token_prefix=token[:12] + "...",
            )


async def _send_fcm(token: str, title: str, body: str, data: dict | None = None):
    """Send a push notification via FCM v1 API."""
    access_token = await _get_fcm_access_token()

    message: dict[str, Any] = {
        "message": {
            "token": token,
            "notification": {"title": title, "body": body},
            "android": {
                "priority": "high",
                "notification": {"sound": "default"},
            },
        }
    }
    if data:
        message["message"]["data"] = {k: str(v) for k, v in data.items()}

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://fcm.googleapis.com/v1/projects/{FCM_PROJECT_ID}/messages:send",
            json=message,
            headers={"authorization": f"Bearer {access_token}"},
        )

        if resp.status_code == 404:
            # Token invalid — clean up
            db = _get_db()
            await db.execute("DELETE FROM push_tokens WHERE token = $1", token)
            log.info("fcm_token_expired", token_prefix=token[:12] + "...")
        elif resp.status_code != 200:
            log.error(
                "fcm_send_failed",
                status=resp.status_code,
                body=resp.text,
                token_prefix=token[:12] + "...",
            )


async def send_push(
    user_id: str,
    title: str,
    body: str,
    data: dict | None = None,
):
    """Send push notification to all devices registered for a user.

    This is the main entry point used by the event pipeline. It looks up
    all push tokens for the given user and dispatches via APNs or FCM.

    Args:
        user_id: Target user UUID string.
        title: Notification title.
        body: Notification body text.
        data: Optional payload for deep-link routing on tap.
    """
    db = _get_db()

    rows = await db.fetch(
        """
        SELECT platform, token FROM push_tokens
        WHERE user_id = $1
        ORDER BY last_used_at DESC NULLS LAST
        """,
        uuid.UUID(user_id),
    )

    if not rows:
        log.debug("send_push_no_tokens", user_id=user_id)
        return

    for row in rows:
        platform = row["platform"]
        token = row["token"]
        try:
            if platform == "ios":
                await _send_apns(token, title, body, data)
            elif platform == "android":
                await _send_fcm(token, title, body, data)
        except Exception:
            log.exception(
                "push_send_error",
                platform=platform,
                user_id=user_id,
                token_prefix=token[:12] + "...",
            )

    # Update last_used_at for the tokens we just sent to
    token_list = [row["token"] for row in rows]
    await db.execute(
        "UPDATE push_tokens SET last_used_at = now() WHERE token = ANY($1)",
        token_list,
    )


async def send_push_to_org(
    org_id: str,
    title: str,
    body: str,
    data: dict | None = None,
    exclude_user_id: str | None = None,
):
    """Send push notification to all members of an org.

    Args:
        org_id: Target org UUID string.
        title: Notification title.
        body: Notification body text.
        data: Optional deep-link payload.
        exclude_user_id: Optionally exclude a user (e.g., the sender).
    """
    db = _get_db()

    query = "SELECT DISTINCT user_id FROM push_tokens WHERE org_id = $1"
    params: list = [uuid.UUID(org_id)]

    if exclude_user_id:
        query += " AND user_id != $2"
        params.append(uuid.UUID(exclude_user_id))

    user_rows = await db.fetch(query, *params)

    for row in user_rows:
        await send_push(str(row["user_id"]), title, body, data)


# ---------------------------------------------------------------------------
# Push event helpers (called from the pipeline/conversation event handlers)
# ---------------------------------------------------------------------------


async def notify_pipeline_completed(
    org_id: str,
    pipeline_id: str,
    pipeline_name: str,
    success: bool,
):
    """Pipeline completed (success or failure)."""
    if success:
        title = f"Pipeline complete \u2705"
        body = f"{pipeline_name} finished successfully"
    else:
        title = f"Pipeline failed \u274C"
        body = f"{pipeline_name} failed — check the logs"

    await send_push_to_org(
        org_id,
        title,
        body,
        data={
            "type": "pipeline",
            "url": f"forge://pipeline/{pipeline_id}",
            "pipeline_id": pipeline_id,
        },
    )


async def notify_approval_requested(
    org_id: str,
    pipeline_id: str,
    pipeline_name: str,
    stage: str,
):
    """Approval requested (high priority)."""
    await send_push_to_org(
        org_id,
        "\U0001f514 Approval needed",
        f"{stage} stage on {pipeline_name}",
        data={
            "type": "approval",
            "url": f"forge://approve/{pipeline_id}/{stage}",
            "pipeline_id": pipeline_id,
            "stage": stage,
        },
    )


async def notify_agent_dm(
    user_id: str,
    agent_role: str,
    agent_name: str,
    preview: str,
):
    """Agent DM response."""
    await send_push(
        user_id,
        f"\U0001f4ac {agent_name}",
        preview[:200],
        data={
            "type": "dm",
            "url": f"forge://dm/{agent_role}",
            "agent_role": agent_role,
        },
    )


async def notify_budget_alert(
    org_id: str,
    pipeline_id: str,
    pipeline_name: str,
    percent_used: int,
    budget_limit: float,
):
    """Budget alert."""
    await send_push_to_org(
        org_id,
        "\u26A0\uFE0F Budget alert",
        f"{pipeline_name} at {percent_used}% of ${budget_limit:.0f} budget",
        data={
            "type": "pipeline",
            "url": f"forge://pipeline/{pipeline_id}",
            "pipeline_id": pipeline_id,
        },
    )


async def notify_pipeline_error(
    org_id: str,
    pipeline_id: str,
    pipeline_name: str,
    stage: str,
):
    """Pipeline error at a specific stage."""
    await send_push_to_org(
        org_id,
        f"\u274C Pipeline failed",
        f"{pipeline_name} failed at {stage} stage",
        data={
            "type": "pipeline",
            "url": f"forge://pipeline/{pipeline_id}",
            "pipeline_id": pipeline_id,
        },
    )
