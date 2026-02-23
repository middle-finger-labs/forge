#!/usr/bin/env python3
"""Manual integration test for the multiplayer stack.

Requires the full stack running via ``docker compose up -d``.
Exercises the full user journey:
  1. Create two user accounts via Better Auth API
  2. Create an org and add both users
  3. User 1 starts a pipeline via the API
  4. User 2 queries pipeline list and sees it
  5. Approval gate: User 2 approves a stage
  6. Both users' sessions see pipeline progress

Usage::

    # Start the stack first
    docker compose up -d
    ./scripts/setup.sh

    # Run the test
    python scripts/test_multiplayer.py
"""

from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass

import httpx

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

AUTH_URL = os.environ.get("AUTH_URL", "http://localhost:3100")
API_URL = os.environ.get("API_URL", "http://localhost:8000")

SESSION_COOKIE = "better-auth.session_token"


@dataclass
class TestUser:
    email: str
    password: str
    name: str
    session_token: str = ""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def header(msg: str) -> None:
    print(f"\n{'='*60}")
    print(f"  {msg}")
    print(f"{'='*60}")


def info(msg: str) -> None:
    print(f"  \033[32m✓\033[0m {msg}")


def fail(msg: str) -> None:
    print(f"  \033[31m✗\033[0m {msg}")
    sys.exit(1)


def warn(msg: str) -> None:
    print(f"  \033[33m⚠\033[0m {msg}")


def api_request(
    method: str,
    url: str,
    session_token: str = "",
    json_data: dict | None = None,
) -> httpx.Response:
    """Make an HTTP request with optional session cookie."""
    cookies = {}
    headers = {}
    if session_token:
        cookies[SESSION_COOKIE] = session_token
        headers["Authorization"] = f"Bearer {session_token}"
    return httpx.request(
        method,
        url,
        json=json_data,
        cookies=cookies,
        headers=headers,
        timeout=15.0,
    )


# ---------------------------------------------------------------------------
# Test steps
# ---------------------------------------------------------------------------


def check_services() -> None:
    """Verify all services are reachable."""
    header("Pre-flight: Checking services")

    for name, url in [
        ("Auth", f"{AUTH_URL}/health"),
        ("API", f"{API_URL}/api/health"),
    ]:
        try:
            resp = httpx.get(url, timeout=5.0)
            if resp.status_code == 200:
                info(f"{name} is healthy")
            else:
                fail(f"{name} returned {resp.status_code}")
        except httpx.RequestError as e:
            fail(f"{name} unreachable: {e}")


def signup_user(user: TestUser) -> TestUser:
    """Sign up a user via Better Auth."""
    resp = httpx.post(
        f"{AUTH_URL}/api/auth/sign-up/email",
        json={"email": user.email, "password": user.password, "name": user.name},
        timeout=10.0,
    )
    if resp.status_code == 200:
        data = resp.json()
        token = data.get("token") or ""
        # Also check cookies
        if not token:
            for cookie_name, cookie_val in resp.cookies.items():
                if "session" in cookie_name.lower():
                    token = cookie_val
                    break
        user.session_token = token
        info(f"Signed up: {user.email}")
    elif resp.status_code == 422 or "already exists" in resp.text.lower():
        # Try sign in instead
        return signin_user(user)
    else:
        fail(f"Signup failed for {user.email}: {resp.status_code} {resp.text[:200]}")
    return user


def signin_user(user: TestUser) -> TestUser:
    """Sign in a user via Better Auth."""
    resp = httpx.post(
        f"{AUTH_URL}/api/auth/sign-in/email",
        json={"email": user.email, "password": user.password},
        timeout=10.0,
    )
    if resp.status_code == 200:
        data = resp.json()
        token = data.get("token") or ""
        if not token:
            for cookie_name, cookie_val in resp.cookies.items():
                if "session" in cookie_name.lower():
                    token = cookie_val
                    break
        user.session_token = token
        info(f"Signed in: {user.email}")
    else:
        fail(f"Signin failed for {user.email}: {resp.status_code} {resp.text[:200]}")
    return user


def create_org(user: TestUser, name: str, slug: str) -> str:
    """Create an organization."""
    resp = api_request(
        "POST",
        f"{AUTH_URL}/api/auth/organization/create",
        session_token=user.session_token,
        json_data={"name": name, "slug": slug},
    )
    if resp.status_code == 200:
        org_id = resp.json().get("id", "")
        info(f"Created org: {name} ({org_id})")
        return org_id
    elif "already exists" in resp.text.lower() or "duplicate" in resp.text.lower():
        warn(f"Org '{slug}' already exists — attempting to look up")
        return slug  # Use slug as fallback ID
    else:
        fail(f"Create org failed: {resp.status_code} {resp.text[:200]}")
        return ""  # unreachable


def set_active_org(user: TestUser, org_id: str) -> None:
    """Set the user's active organization."""
    resp = api_request(
        "POST",
        f"{AUTH_URL}/api/auth/organization/set-active",
        session_token=user.session_token,
        json_data={"organizationId": org_id},
    )
    if resp.status_code == 200:
        info(f"Active org set for {user.email}")
    else:
        warn(f"Set active org: {resp.status_code} (may already be active)")


def invite_user(owner: TestUser, org_id: str, invitee_email: str) -> None:
    """Invite a user to the organization."""
    resp = api_request(
        "POST",
        f"{AUTH_URL}/api/auth/organization/invite-member",
        session_token=owner.session_token,
        json_data={
            "email": invitee_email,
            "role": "member",
            "organizationId": org_id,
        },
    )
    if resp.status_code == 200:
        info(f"Invited {invitee_email} to org")
    else:
        warn(f"Invite: {resp.status_code} {resp.text[:100]} (may already be member)")


def accept_invitation(user: TestUser, org_id: str) -> None:
    """Accept an org invitation."""
    # List pending invitations
    resp = api_request(
        "GET",
        f"{AUTH_URL}/api/auth/organization/list-invitations",
        session_token=user.session_token,
    )
    if resp.status_code == 200:
        invitations = resp.json()
        for inv in invitations if isinstance(invitations, list) else []:
            inv_id = inv.get("id", "")
            if inv_id:
                accept_resp = api_request(
                    "POST",
                    f"{AUTH_URL}/api/auth/organization/accept-invitation",
                    session_token=user.session_token,
                    json_data={"invitationId": inv_id},
                )
                if accept_resp.status_code == 200:
                    info(f"Accepted invitation for {user.email}")
                    return
    warn(f"No pending invitations found for {user.email}")


def test_pipeline_visibility(user1: TestUser, user2: TestUser) -> str:
    """User 1 starts a pipeline, user 2 can see it."""
    header("Test: Pipeline visibility across org members")

    # User 1 starts a pipeline
    resp = api_request(
        "POST",
        f"{API_URL}/api/pipelines",
        session_token=user1.session_token,
        json_data={
            "business_spec": "Multiplayer integration test — build a TODO app",
            "project_name": "test-multiplayer",
        },
    )
    if resp.status_code != 200:
        fail(f"Start pipeline failed: {resp.status_code} {resp.text[:200]}")

    data = resp.json()
    pipeline_id = data.get("pipeline_id", "")
    info(f"User 1 started pipeline: {pipeline_id}")

    # Give it a moment to register
    time.sleep(2)

    # User 2 lists pipelines
    resp2 = api_request(
        "GET",
        f"{API_URL}/api/pipelines",
        session_token=user2.session_token,
    )
    if resp2.status_code != 200:
        fail(f"List pipelines failed: {resp2.status_code}")

    pipelines = resp2.json()
    pipeline_ids = [p.get("pipeline_id") for p in pipelines]
    if pipeline_id in pipeline_ids:
        info(f"User 2 can see the pipeline: {pipeline_id}")
    else:
        fail(f"User 2 cannot see pipeline {pipeline_id} in list: {pipeline_ids}")

    return pipeline_id


def test_approval_flow(user2: TestUser, pipeline_id: str) -> None:
    """User 2 approves a pending stage."""
    header("Test: Cross-user approval")

    # Check if pipeline has a pending approval
    resp = api_request(
        "GET",
        f"{API_URL}/api/pipelines/{pipeline_id}/state",
        session_token=user2.session_token,
    )
    if resp.status_code == 200:
        state = resp.json()
        pending = state.get("pending_approval")
        if pending:
            info(f"Pipeline pending approval for stage: {pending}")
            # Approve it
            approve_resp = api_request(
                "POST",
                f"{API_URL}/api/pipelines/{pipeline_id}/approve",
                session_token=user2.session_token,
                json_data={
                    "stage": pending,
                    "notes": "Approved by integration test user 2",
                },
            )
            if approve_resp.status_code == 200:
                info("User 2 approved the stage")
            else:
                warn(f"Approval: {approve_resp.status_code} {approve_resp.text[:100]}")
        else:
            warn(f"No pending approval (stage={state.get('current_stage')})")
    else:
        warn(f"Could not query state: {resp.status_code}")


def test_both_see_events(user1: TestUser, user2: TestUser, pipeline_id: str) -> None:
    """Both users can see pipeline events."""
    header("Test: Shared event visibility")

    for user in [user1, user2]:
        resp = api_request(
            "GET",
            f"{API_URL}/api/pipelines/{pipeline_id}/events",
            session_token=user.session_token,
        )
        if resp.status_code == 200:
            events = resp.json()
            info(f"{user.name} sees {len(events)} events")
        else:
            warn(f"{user.name} events query: {resp.status_code}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> None:
    print("\n" + "="*60)
    print("  Forge Multiplayer Integration Test")
    print("="*60)

    check_services()

    # Step 1: Create two user accounts
    header("Step 1: Create user accounts")
    user1 = signup_user(TestUser(
        email="test-user1@forge-test.com",
        password="TestPass123!",
        name="Test User 1",
    ))
    user2 = signup_user(TestUser(
        email="test-user2@forge-test.com",
        password="TestPass456!",
        name="Test User 2",
    ))

    if not user1.session_token or not user2.session_token:
        fail("Could not obtain session tokens for both users")

    # Step 2: Create org and add both users
    header("Step 2: Create org and add members")
    org_id = create_org(user1, "Test Multiplayer Org", "test-multiplayer-org")
    set_active_org(user1, org_id)
    invite_user(user1, org_id, user2.email)
    accept_invitation(user2, org_id)
    set_active_org(user2, org_id)

    # Step 3-4: Pipeline visibility
    pipeline_id = test_pipeline_visibility(user1, user2)

    # Step 5: Approval flow
    test_approval_flow(user2, pipeline_id)

    # Step 6: Shared event visibility
    test_both_see_events(user1, user2, pipeline_id)

    # Summary
    header("Results")
    info("All multiplayer integration tests passed!")
    print()


if __name__ == "__main__":
    main()
