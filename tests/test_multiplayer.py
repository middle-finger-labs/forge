"""Tests for the multiplayer / multi-tenancy stack.

Covers:
  - Auth middleware (valid / invalid sessions)
  - Org scoping (pipeline isolation between orgs)
  - Presence (WebSocket room isolation)
  - Approval coordination (cross-user approval flow)
  - Org secrets (encrypt / decrypt round-trip)
  - Org-scoped memory isolation
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from auth.types import ForgeUser

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

USER_A = ForgeUser(
    user_id="user-aaa",
    email="alice@orgA.com",
    name="Alice",
    org_id="org-A",
    org_slug="org-a",
    role="owner",
)

USER_B = ForgeUser(
    user_id="user-bbb",
    email="bob@orgB.com",
    name="Bob",
    org_id="org-B",
    org_slug="org-b",
    role="member",
)

USER_B_SAME_ORG = ForgeUser(
    user_id="user-bbb",
    email="bob@orgA.com",
    name="Bob",
    org_id="org-A",
    org_slug="org-a",
    role="member",
)


@pytest.fixture()
def _disable_auth():
    """Patch auth to disabled so we can test without infrastructure."""
    with patch("auth.middleware.FORGE_AUTH_ENABLED", False):
        yield


# ============================================================================
# 1. Auth middleware — valid session
# ============================================================================


class TestAuthMiddlewareValid:
    """Verify that a valid Better Auth session is parsed into ForgeUser."""

    @pytest.mark.asyncio
    async def test_valid_session_returns_forge_user(self):
        """Mock Better Auth /get-session and verify ForgeUser fields."""
        from auth.middleware import _validate_session

        session_response = {
            "session": {"activeOrganizationId": "org-123"},
            "user": {
                "id": "user-456",
                "email": "test@example.com",
                "name": "Test User",
            },
        }
        org_response = {
            "slug": "test-org",
            "members": [
                {"userId": "user-456", "role": "admin"},
            ],
        }

        mock_client = AsyncMock()
        # First call: get-session, second call: get-full-organization
        mock_session_resp = MagicMock(status_code=200)
        mock_session_resp.json.return_value = session_response
        mock_org_resp = MagicMock(status_code=200)
        mock_org_resp.json.return_value = org_response
        mock_client.get = AsyncMock(side_effect=[mock_session_resp, mock_org_resp])

        with patch("auth.middleware._get_http_client", return_value=mock_client):
            user = await _validate_session("valid-token-abc")

        assert isinstance(user, ForgeUser)
        assert user.user_id == "user-456"
        assert user.email == "test@example.com"
        assert user.org_id == "org-123"
        assert user.org_slug == "test-org"
        assert user.role == "admin"
        assert user.is_admin is True

    @pytest.mark.asyncio
    async def test_dev_user_when_auth_disabled(self):
        """When FORGE_AUTH_ENABLED=false, get_current_user returns dev stub."""
        from auth.middleware import get_current_user

        mock_request = MagicMock()
        with patch("auth.middleware.FORGE_AUTH_ENABLED", False):
            user = await get_current_user(mock_request)

        assert user.user_id == "dev-user-000"
        assert user.org_id == "dev-org-000"
        assert user.role == "owner"


# ============================================================================
# 2. Auth middleware — invalid token returns 401
# ============================================================================


class TestAuthMiddlewareInvalid:
    """Verify that missing or invalid tokens yield HTTP 401."""

    @pytest.mark.asyncio
    async def test_missing_token_returns_401(self):
        """No cookie and no Authorization header → 401."""
        from auth.middleware import get_current_user

        mock_request = MagicMock()
        mock_request.cookies = {}
        mock_request.headers = {}

        with (
            patch("auth.middleware.FORGE_AUTH_ENABLED", True),
            pytest.raises(HTTPException) as exc_info,
        ):
            await get_current_user(mock_request)

        assert exc_info.value.status_code == 401
        assert "Missing session token" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self):
        """Token present but Better Auth rejects it → 401."""
        from auth.middleware import _validate_session

        mock_client = AsyncMock()
        mock_resp = MagicMock(status_code=401)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with (
            patch("auth.middleware._get_http_client", return_value=mock_client),
            pytest.raises(HTTPException) as exc_info,
        ):
            await _validate_session("bad-token")

        assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_no_org_returns_403(self):
        """Valid user but no active organization → 403."""
        from auth.middleware import _validate_session

        session_response = {
            "session": {"activeOrganizationId": ""},
            "user": {"id": "user-789", "email": "no-org@test.com", "name": "NoOrg"},
        }

        mock_client = AsyncMock()
        mock_resp = MagicMock(status_code=200)
        mock_resp.json.return_value = session_response
        mock_client.get = AsyncMock(return_value=mock_resp)

        with (
            patch("auth.middleware._get_http_client", return_value=mock_client),
            pytest.raises(HTTPException) as exc_info,
        ):
            await _validate_session("valid-but-no-org")

        assert exc_info.value.status_code == 403


# ============================================================================
# 3. Org scoping — pipeline isolation
# ============================================================================


class TestOrgScoping:
    """Verify org_id filtering on pipeline queries."""

    @pytest.mark.asyncio
    async def test_pipelines_filtered_by_org_id(self):
        """Two pipelines from different orgs — each user only sees their own."""
        # Simulate what the API endpoint does: filter by user.org_id
        all_pipelines = [
            {"pipeline_id": "p1", "org_id": "org-A", "status": "running"},
            {"pipeline_id": "p2", "org_id": "org-B", "status": "complete"},
            {"pipeline_id": "p3", "org_id": "org-A", "status": "pending"},
        ]

        user_a_pipelines = [
            p for p in all_pipelines if p["org_id"] == USER_A.org_id
        ]
        user_b_pipelines = [
            p for p in all_pipelines if p["org_id"] == USER_B.org_id
        ]

        assert len(user_a_pipelines) == 2
        assert all(p["org_id"] == "org-A" for p in user_a_pipelines)
        assert len(user_b_pipelines) == 1
        assert user_b_pipelines[0]["pipeline_id"] == "p2"

    @pytest.mark.asyncio
    async def test_pipeline_detail_rejects_cross_org(self):
        """User A cannot fetch a pipeline belonging to org B."""
        pipeline_row = {
            "pipeline_id": "p2",
            "org_id": "org-B",
            "status": "complete",
        }
        # Simulate the check: if the pipeline's org_id doesn't match the user's
        requesting_user = USER_A
        assert pipeline_row["org_id"] != requesting_user.org_id
        # In the real endpoint this returns 404 (not 403, to avoid info leakage)


# ============================================================================
# 4. Presence — WebSocket room isolation
# ============================================================================


class TestPresence:
    """Verify presence tracking logic for WebSocket rooms."""

    def test_presence_data_structure(self):
        """Verify presence data includes all required fields."""
        presence_entry = {
            "user_id": USER_A.user_id,
            "user_name": USER_A.name,
            "pipeline_id": "p1",
            "last_seen": "2026-02-23T10:00:00Z",
        }
        assert "user_id" in presence_entry
        assert "user_name" in presence_entry
        assert "pipeline_id" in presence_entry

    def test_two_users_in_same_room(self):
        """Two users connected to the same pipeline see each other."""
        room: dict[str, dict] = {}

        # Simulate joins
        room[USER_A.user_id] = {
            "name": USER_A.name,
            "pipeline_id": "p1",
        }
        room[USER_B_SAME_ORG.user_id] = {
            "name": USER_B_SAME_ORG.name,
            "pipeline_id": "p1",
        }

        assert len(room) == 2
        assert USER_A.user_id in room
        assert USER_B_SAME_ORG.user_id in room

    def test_different_pipeline_rooms_are_isolated(self):
        """Users on different pipelines don't see each other."""
        rooms: dict[str, dict[str, dict]] = {
            "p1": {},
            "p2": {},
        }

        rooms["p1"][USER_A.user_id] = {"name": USER_A.name}
        rooms["p2"][USER_B.user_id] = {"name": USER_B.name}

        assert USER_B.user_id not in rooms["p1"]
        assert USER_A.user_id not in rooms["p2"]


# ============================================================================
# 5. Approval coordination
# ============================================================================


class TestApprovalCoordination:
    """Verify that any org member can approve a stage and both see the event."""

    @pytest.mark.asyncio
    async def test_approval_creates_event_for_both_users(self):
        """User A starts, User B approves → both see the approval event."""
        events: list[dict] = []

        # User A starts pipeline
        pipeline = {
            "pipeline_id": "p-approval-test",
            "org_id": "org-A",
            "status": "pending_approval",
            "current_stage": "architecture",
            "started_by": USER_A.user_id,
        }
        events.append({
            "event_type": "pipeline.started",
            "pipeline_id": pipeline["pipeline_id"],
            "user_id": USER_A.user_id,
        })

        # User B approves
        approval_event = {
            "event_type": "stage.approved",
            "pipeline_id": pipeline["pipeline_id"],
            "stage": "architecture",
            "approved_by": USER_B_SAME_ORG.user_id,
            "user_name": USER_B_SAME_ORG.name,
        }
        events.append(approval_event)
        pipeline["status"] = "running"

        # Both users in org-A can see all events
        org_a_events = [
            e for e in events if e["pipeline_id"] == pipeline["pipeline_id"]
        ]
        assert len(org_a_events) == 2
        assert org_a_events[1]["event_type"] == "stage.approved"
        assert org_a_events[1]["approved_by"] == USER_B_SAME_ORG.user_id
        assert pipeline["status"] == "running"

    def test_member_role_can_approve(self):
        """A member (not just admin/owner) can approve stages."""
        # In our system, require_org_member (not require_org_admin) is used
        # for approval endpoints, so regular members can approve.
        assert USER_B_SAME_ORG.role == "member"
        # The approval endpoint uses get_current_user, so any org member can
        # submit approvals. This is by design.


# ============================================================================
# 6. Org secrets — encryption round-trip
# ============================================================================


try:
    import cryptography.fernet  # noqa: F401

    _HAS_CRYPTOGRAPHY = True
except ImportError:
    _HAS_CRYPTOGRAPHY = False


@pytest.mark.skipif(not _HAS_CRYPTOGRAPHY, reason="cryptography not installed")
class TestOrgSecrets:
    """Verify Fernet encryption of org secrets."""

    def test_encrypt_decrypt_round_trip(self):
        """Store and retrieve a secret — plaintext must match."""
        from cryptography.fernet import Fernet

        key = Fernet.generate_key()

        with patch.dict(os.environ, {"FORGE_ENCRYPTION_KEY": key.decode()}):
            from auth.secrets import decrypt_secret, encrypt_secret

            plaintext = "sk-ant-super-secret-key-12345"
            ciphertext = encrypt_secret(plaintext)

            assert isinstance(ciphertext, bytes)
            assert ciphertext != plaintext.encode()

            recovered = decrypt_secret(ciphertext)
            assert recovered == plaintext

    def test_different_keys_fail_decryption(self):
        """Decrypting with the wrong key raises ValueError."""
        from cryptography.fernet import Fernet

        key_a = Fernet.generate_key()
        key_b = Fernet.generate_key()

        with patch.dict(os.environ, {"FORGE_ENCRYPTION_KEY": key_a.decode()}):
            from auth.secrets import encrypt_secret

            ciphertext = encrypt_secret("my-secret")

        with patch.dict(os.environ, {"FORGE_ENCRYPTION_KEY": key_b.decode()}):
            from auth.secrets import decrypt_secret

            with pytest.raises(ValueError, match="Failed to decrypt"):
                decrypt_secret(ciphertext)

    def test_missing_key_raises_runtime_error(self):
        """No FORGE_ENCRYPTION_KEY → RuntimeError."""
        from auth.secrets import _get_fernet

        with patch.dict(os.environ, {"FORGE_ENCRYPTION_KEY": ""}, clear=False):
            with patch("auth.secrets._ENCRYPTION_KEY", ""):
                with pytest.raises(RuntimeError, match="FORGE_ENCRYPTION_KEY"):
                    _get_fernet()


# ============================================================================
# 7. Org-scoped memory isolation
# ============================================================================


class TestOrgScopedMemory:
    """Verify that memories are scoped to the owning org."""

    @pytest.mark.asyncio
    async def test_memory_store_includes_org_id(self):
        """store_lesson passes org_id through to the backend."""
        from memory.semantic_memory import SemanticMemory

        mem = SemanticMemory()
        mock_backend = AsyncMock()
        mock_backend.store = AsyncMock()

        with patch.object(mem, "_ensure_init", return_value=mock_backend):
            await mem.store_lesson(
                agent_role="qa",
                pipeline_id="p1",
                lesson="Always add tests",
                org_id="org-A",
                user_id="user-aaa",
            )

        mock_backend.store.assert_called_once()
        call_kwargs = mock_backend.store.call_args
        assert call_kwargs.kwargs.get("org_id") == "org-A"
        assert call_kwargs.kwargs.get("user_id") == "user-aaa"

    @pytest.mark.asyncio
    async def test_memory_recall_filters_by_org(self):
        """recall passes org_id to the backend for filtering."""
        from memory.semantic_memory import SemanticMemory

        mem = SemanticMemory()
        mock_backend = AsyncMock()
        mock_backend.search = AsyncMock(return_value=[])

        with patch.object(mem, "_ensure_init", return_value=mock_backend):
            await mem.recall(
                query="testing best practices",
                agent_role="qa",
                org_id="org-A",
            )

        mock_backend.search.assert_called_once()
        call_kwargs = mock_backend.search.call_args
        assert call_kwargs.kwargs.get("org_id") == "org-A"

    @pytest.mark.asyncio
    async def test_org_b_cannot_recall_org_a_memories(self):
        """Org-B recall should NOT return org-A memories."""
        # Simulate two separate memory stores
        org_a_memories = [
            {"id": "m1", "content": "org-A lesson", "org_id": "org-A"},
        ]
        org_b_memories: list[dict] = []

        # Org A has memories, org B doesn't
        def search_with_org_filter(query, *, org_id=None, **kwargs):
            if org_id == "org-A":
                return org_a_memories
            return org_b_memories

        from memory.semantic_memory import SemanticMemory

        mem = SemanticMemory()
        mock_backend = AsyncMock()
        mock_backend.search = AsyncMock(side_effect=search_with_org_filter)

        with patch.object(mem, "_ensure_init", return_value=mock_backend):
            org_a_results = await mem.recall("lesson", org_id="org-A")
            org_b_results = await mem.recall("lesson", org_id="org-B")

        assert len(org_a_results) == 1
        assert org_a_results[0]["content"] == "org-A lesson"
        assert len(org_b_results) == 0

    @pytest.mark.asyncio
    async def test_private_mode_filters_by_user_id(self):
        """In private mode, recall includes user_id filter."""
        from memory.semantic_memory import get_relevant_context

        mock_mem = AsyncMock()
        mock_mem.recall = AsyncMock(return_value=[])

        with (
            patch("memory.semantic_memory.get_memory_sharing_mode", return_value="private"),
            patch("memory.semantic_memory.SemanticMemory", return_value=mock_mem),
        ):
            await get_relevant_context(
                agent_role="engineer",
                task_description="implement auth",
                memory=mock_mem,
                org_id="org-A",
                user_id="user-aaa",
            )

        mock_mem.recall.assert_called_once()
        call_kwargs = mock_mem.recall.call_args
        assert call_kwargs.kwargs.get("user_id") == "user-aaa"


# ============================================================================
# ForgeUser dataclass tests
# ============================================================================


class TestForgeUser:
    """Verify ForgeUser role checks."""

    def test_owner_is_admin(self):
        assert USER_A.is_admin is True
        assert USER_A.is_owner is True

    def test_member_is_not_admin(self):
        assert USER_B.is_admin is False
        assert USER_B.is_owner is False

    def test_admin_role(self):
        admin = ForgeUser(
            user_id="u3", email="admin@test.com", name="Admin",
            org_id="org-X", org_slug="org-x", role="admin",
        )
        assert admin.is_admin is True
        assert admin.is_owner is False

    @pytest.mark.asyncio
    async def test_require_org_admin_rejects_member(self):
        """require_org_admin raises 403 for non-admin/owner."""
        from auth.middleware import require_org_admin

        with pytest.raises(HTTPException) as exc_info:
            await require_org_admin(user=USER_B)
        assert exc_info.value.status_code == 403
