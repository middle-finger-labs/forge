"""Onboarding checklist API.

Tracks first-time user onboarding progress: API key setup, GitHub connection,
team intro, and first pipeline. State is stored per-user in the onboarding table.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone

import asyncpg
import structlog
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from auth.middleware import get_current_user
from auth.types import ForgeUser

log = structlog.get_logger().bind(component="onboarding")

onboarding_router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

DEFAULT_STEPS = {
    "api_key": False,
    "github": False,
    "meet_team": False,
    "first_pipeline": False,
}


def _get_db(request: Request) -> asyncpg.Pool:
    from api.server import _get_db
    return _get_db()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _ensure_onboarding_table(pool: asyncpg.Pool) -> None:
    """Create the onboarding table if it doesn't exist."""
    await pool.execute("""
        CREATE TABLE IF NOT EXISTS onboarding (
            user_id TEXT PRIMARY KEY,
            org_id TEXT,
            completed BOOLEAN DEFAULT FALSE,
            steps JSONB DEFAULT '{}',
            dismissed_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            updated_at TIMESTAMPTZ DEFAULT NOW()
        )
    """)


async def _get_or_create_state(pool: asyncpg.Pool, user: ForgeUser) -> dict:
    """Get or create onboarding state for a user."""
    row = await pool.fetchrow(
        "SELECT * FROM onboarding WHERE user_id = $1",
        user.user_id,
    )

    if row is None:
        # Check if org already has API key and GitHub configured
        steps = dict(DEFAULT_STEPS)

        # If org already has ANTHROPIC_API_KEY, skip that step
        try:
            has_key = await pool.fetchval(
                "SELECT EXISTS(SELECT 1 FROM org_secrets WHERE org_id = $1 AND key = 'ANTHROPIC_API_KEY')",
                user.org_id,
            )
            if has_key:
                steps["api_key"] = True
        except asyncpg.UndefinedTableError:
            pass

        # If org already has a GitHub identity, skip that step
        try:
            has_github = await pool.fetchval(
                "SELECT EXISTS(SELECT 1 FROM org_identities WHERE org_id = $1)",
                user.org_id,
            )
            if has_github:
                steps["github"] = True
        except asyncpg.UndefinedTableError:
            pass

        await pool.execute(
            """
            INSERT INTO onboarding (user_id, org_id, steps)
            VALUES ($1, $2, $3::jsonb)
            ON CONFLICT (user_id) DO NOTHING
            """,
            user.user_id,
            user.org_id,
            json.dumps(steps),
        )

        row = await pool.fetchrow(
            "SELECT * FROM onboarding WHERE user_id = $1",
            user.user_id,
        )

    steps = json.loads(row["steps"]) if isinstance(row["steps"], str) else (row["steps"] or DEFAULT_STEPS)

    return {
        "completed": row["completed"],
        "steps": steps,
        "dismissed_at": row["dismissed_at"].isoformat() if row["dismissed_at"] else None,
        "completed_at": row["completed_at"].isoformat() if row["completed_at"] else None,
    }


# ---------------------------------------------------------------------------
# GET /api/onboarding — current state
# ---------------------------------------------------------------------------


@onboarding_router.get("")
async def get_onboarding(request: Request, user: ForgeUser = Depends(get_current_user)):
    """Get the current user's onboarding state."""
    pool = _get_db(request)
    await _ensure_onboarding_table(pool)
    return await _get_or_create_state(pool, user)


# ---------------------------------------------------------------------------
# PUT /api/onboarding/step/{step_name} — mark step complete
# ---------------------------------------------------------------------------


class StepUpdateRequest(BaseModel):
    completed: bool = True


@onboarding_router.put("/step/{step_name}")
async def update_step(
    step_name: str,
    body: StepUpdateRequest,
    request: Request,
    user: ForgeUser = Depends(get_current_user),
):
    """Mark an onboarding step as complete or incomplete."""
    if step_name not in DEFAULT_STEPS:
        raise HTTPException(status_code=400, detail=f"Unknown step: {step_name}")

    pool = _get_db(request)
    await _ensure_onboarding_table(pool)

    # Ensure state exists
    await _get_or_create_state(pool, user)

    now = datetime.now(timezone.utc)

    # Update the specific step
    row = await pool.fetchrow(
        "SELECT steps FROM onboarding WHERE user_id = $1",
        user.user_id,
    )
    steps = json.loads(row["steps"]) if isinstance(row["steps"], str) else (row["steps"] or dict(DEFAULT_STEPS))
    steps[step_name] = body.completed

    # Check if all steps are now complete
    all_complete = all(steps.values())

    await pool.execute(
        """
        UPDATE onboarding
        SET steps = $2::jsonb,
            completed = $3,
            completed_at = CASE WHEN $3 THEN $4 ELSE completed_at END,
            updated_at = $4
        WHERE user_id = $1
        """,
        user.user_id,
        json.dumps(steps),
        all_complete,
        now,
    )

    return await _get_or_create_state(pool, user)


# ---------------------------------------------------------------------------
# POST /api/onboarding/dismiss — skip setup
# ---------------------------------------------------------------------------


@onboarding_router.post("/dismiss")
async def dismiss_onboarding(
    request: Request,
    user: ForgeUser = Depends(get_current_user),
):
    """Dismiss the onboarding checklist (skip setup)."""
    pool = _get_db(request)
    await _ensure_onboarding_table(pool)
    await _get_or_create_state(pool, user)

    now = datetime.now(timezone.utc)
    await pool.execute(
        "UPDATE onboarding SET dismissed_at = $2, updated_at = $2 WHERE user_id = $1",
        user.user_id,
        now,
    )

    return await _get_or_create_state(pool, user)


# ---------------------------------------------------------------------------
# POST /api/onboarding/complete — all done
# ---------------------------------------------------------------------------


@onboarding_router.post("/complete")
async def complete_onboarding(
    request: Request,
    user: ForgeUser = Depends(get_current_user),
):
    """Mark onboarding as fully completed."""
    pool = _get_db(request)
    await _ensure_onboarding_table(pool)
    await _get_or_create_state(pool, user)

    now = datetime.now(timezone.utc)

    # Mark all steps complete
    steps = {k: True for k in DEFAULT_STEPS}

    await pool.execute(
        """
        UPDATE onboarding
        SET completed = TRUE, completed_at = $2, steps = $3::jsonb, updated_at = $2
        WHERE user_id = $1
        """,
        user.user_id,
        now,
        json.dumps(steps),
    )

    return await _get_or_create_state(pool, user)


# ---------------------------------------------------------------------------
# POST /api/onboarding/validate-api-key — test an Anthropic key
# ---------------------------------------------------------------------------


class ValidateApiKeyRequest(BaseModel):
    key: str


@onboarding_router.post("/validate-api-key")
async def validate_api_key(
    body: ValidateApiKeyRequest,
    request: Request,
    user: ForgeUser = Depends(get_current_user),
):
    """Validate an Anthropic API key by making a test call.

    If valid, stores it as the org's ANTHROPIC_API_KEY secret and
    marks the api_key onboarding step as complete.
    """
    import httpx

    key = body.key.strip()
    if not key.startswith("sk-ant-"):
        raise HTTPException(status_code=400, detail="Invalid key format — Anthropic keys start with sk-ant-")

    # Test the key with a lightweight API call
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.anthropic.com/v1/models",
                headers={
                    "x-api-key": key,
                    "anthropic-version": "2023-06-01",
                },
            )
            if resp.status_code == 401:
                raise HTTPException(
                    status_code=400,
                    detail="This key didn't work — check that it's correct and has credits",
                )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail=f"Anthropic API returned {resp.status_code} — the key may be invalid or rate limited",
                )
    except httpx.RequestError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Could not reach Anthropic API: {exc}",
        )

    # Store the key as an org secret
    from auth.secrets import set_org_secret
    await set_org_secret(user.org_id, "ANTHROPIC_API_KEY", key, user.user_id)

    # Mark onboarding step complete
    pool = _get_db(request)
    await _ensure_onboarding_table(pool)
    await _get_or_create_state(pool, user)

    now = datetime.now(timezone.utc)

    row = await pool.fetchrow(
        "SELECT steps FROM onboarding WHERE user_id = $1",
        user.user_id,
    )
    steps = json.loads(row["steps"]) if isinstance(row["steps"], str) else (row["steps"] or dict(DEFAULT_STEPS))
    steps["api_key"] = True
    all_complete = all(steps.values())

    await pool.execute(
        """
        UPDATE onboarding
        SET steps = $2::jsonb, completed = $3,
            completed_at = CASE WHEN $3 THEN $4 ELSE completed_at END,
            updated_at = $4
        WHERE user_id = $1
        """,
        user.user_id,
        json.dumps(steps),
        all_complete,
        now,
    )

    log.info("api key validated and stored", org_id=user.org_id)
    return {"valid": True, "message": "API key is valid and has been saved"}


# ---------------------------------------------------------------------------
# POST /api/onboarding/validate-github-token — test a GitHub PAT
# ---------------------------------------------------------------------------


class ValidateGitHubTokenRequest(BaseModel):
    token: str
    github_username: str | None = None


@onboarding_router.post("/validate-github-token")
async def validate_github_token(
    body: ValidateGitHubTokenRequest,
    request: Request,
    user: ForgeUser = Depends(get_current_user),
):
    """Validate a GitHub token and store it as an identity."""
    import httpx

    token = body.token.strip()

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=400,
                    detail="This token didn't work — check that it's correct and has the right scopes",
                )
            gh_user = resp.json()
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach GitHub API: {exc}")

    # Create an org identity with this token
    from auth.secrets import create_org_identity

    username = gh_user.get("login", body.github_username or "")
    email_val = gh_user.get("email") or f"{username}@users.noreply.github.com"

    identity = await create_org_identity(
        org_id=user.org_id,
        name=username,
        github_username=username,
        email=email_val,
        github_token=token,
        is_default=True,
    )

    log.info("github token validated", org_id=user.org_id, github_user=username)
    return {
        "valid": True,
        "github_user": username,
        "github_name": gh_user.get("name"),
        "identity_id": identity.get("id"),
    }


# ---------------------------------------------------------------------------
# GET /api/onboarding/github-repos — list repos for the connected GitHub user
# ---------------------------------------------------------------------------


@onboarding_router.get("/github-repos")
async def list_github_repos(
    request: Request,
    user: ForgeUser = Depends(get_current_user),
):
    """List GitHub repos accessible by the org's default GitHub identity."""
    import httpx
    from auth.secrets import get_default_identity_for_org, get_org_identity_token

    identity = await get_default_identity_for_org(user.org_id)
    if identity is None:
        raise HTTPException(status_code=404, detail="No GitHub identity configured")

    token = await get_org_identity_token(user.org_id, identity["id"])
    if not token:
        raise HTTPException(status_code=404, detail="No GitHub token found for identity")

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.github.com/user/repos?sort=pushed&per_page=30&type=all",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail="Failed to fetch repos from GitHub")

            repos = resp.json()
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"Could not reach GitHub: {exc}")

    return [
        {
            "full_name": r["full_name"],
            "name": r["name"],
            "owner": r["owner"]["login"],
            "description": r.get("description"),
            "stars": r.get("stargazers_count", 0),
            "default_branch": r.get("default_branch", "main"),
            "private": r.get("private", False),
            "html_url": r.get("html_url"),
        }
        for r in repos
    ]
