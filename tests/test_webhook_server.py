"""Tests for integrations/webhook_server.py — GitHub webhook receiver."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from integrations.webhook_server import (
    _COMMENT_ABORT_RE,
    _COMMENT_APPROVE_RE,
    _COMMENT_STATUS_RE,
    _has_forge_label,
    _issue_key,
    _issue_pipeline_map,
    _verify_signature,
    get_pipeline_for_issue,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_signature(payload: bytes, secret: str) -> str:
    """Compute the sha256 HMAC signature GitHub would send."""
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _repo_payload(
    owner: str = "acme",
    name: str = "widgets",
) -> dict[str, Any]:
    return {
        "owner": {"login": owner},
        "name": name,
        "clone_url": f"https://github.com/{owner}/{name}.git",
        "html_url": f"https://github.com/{owner}/{name}",
    }


def _issue_payload(
    number: int = 42,
    title: str = "Add user auth",
    body: str = "We need OAuth support",
    labels: list[dict] | None = None,
) -> dict[str, Any]:
    return {
        "number": number,
        "title": title,
        "body": body,
        "labels": labels or [],
        "user": {"login": "octocat"},
    }


# ---------------------------------------------------------------------------
# Signature verification
# ---------------------------------------------------------------------------


class TestVerifySignature:
    """Tests for HMAC-SHA256 signature verification."""

    def test_skips_when_no_secret(self):
        """Should silently pass if GITHUB_WEBHOOK_SECRET is not set."""
        with patch("integrations.webhook_server.WEBHOOK_SECRET", ""):
            _verify_signature(b"anything", None)  # no exception

    def test_rejects_missing_header(self):
        with patch("integrations.webhook_server.WEBHOOK_SECRET", "s3cret"):
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                _verify_signature(b"payload", None)
            assert exc_info.value.status_code == 403
            assert "Missing" in exc_info.value.detail

    def test_rejects_malformed_header(self):
        with patch("integrations.webhook_server.WEBHOOK_SECRET", "s3cret"):
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                _verify_signature(b"payload", "md5=abc")
            assert exc_info.value.status_code == 403
            assert "Malformed" in exc_info.value.detail

    def test_rejects_wrong_signature(self):
        with patch("integrations.webhook_server.WEBHOOK_SECRET", "s3cret"):
            from fastapi import HTTPException

            with pytest.raises(HTTPException) as exc_info:
                _verify_signature(b"payload", "sha256=0000bad")
            assert exc_info.value.status_code == 403
            assert "Invalid" in exc_info.value.detail

    def test_accepts_valid_signature(self):
        secret = "s3cret"
        payload = b'{"action": "opened"}'
        sig = _make_signature(payload, secret)
        with patch("integrations.webhook_server.WEBHOOK_SECRET", secret):
            _verify_signature(payload, sig)  # no exception


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


class TestPureHelpers:
    """Tests for label matching, issue key, regex patterns."""

    def test_issue_key(self):
        assert _issue_key("acme", "widgets", 7) == "acme/widgets#7"

    def test_has_forge_label_present(self):
        assert _has_forge_label([{"name": "forge"}, {"name": "bug"}])

    def test_has_forge_label_absent(self):
        assert not _has_forge_label([{"name": "bug"}, {"name": "enhancement"}])

    def test_has_forge_label_case_insensitive(self):
        assert _has_forge_label([{"name": "Forge"}])

    def test_has_forge_label_empty(self):
        assert not _has_forge_label([])

    def test_get_pipeline_for_issue_not_found(self):
        assert get_pipeline_for_issue("x", "y", 999) is None

    def test_get_pipeline_for_issue_found(self):
        key = _issue_key("owner", "repo", 10)
        _issue_pipeline_map[key] = "abc123"
        try:
            assert get_pipeline_for_issue("owner", "repo", 10) == "abc123"
        finally:
            _issue_pipeline_map.pop(key, None)

    # Regex patterns
    def test_approve_regex(self):
        m = _COMMENT_APPROVE_RE.search("/forge approve business_analysis")
        assert m is not None
        assert m.group(1) == "business_analysis"

    def test_approve_regex_case_insensitive(self):
        m = _COMMENT_APPROVE_RE.search("/Forge Approve architecture")
        assert m is not None
        assert m.group(1) == "architecture"

    def test_approve_regex_no_match(self):
        assert _COMMENT_APPROVE_RE.search("forge approve something") is None

    def test_abort_regex(self):
        assert _COMMENT_ABORT_RE.search("/forge abort") is not None

    def test_abort_regex_with_context(self):
        assert _COMMENT_ABORT_RE.search("Please /forge abort this pipeline") is not None

    def test_status_regex(self):
        assert _COMMENT_STATUS_RE.search("/forge status") is not None

    def test_status_regex_no_match(self):
        assert _COMMENT_STATUS_RE.search("check the forge status page") is None


# ---------------------------------------------------------------------------
# Full endpoint tests via FastAPI TestClient
# ---------------------------------------------------------------------------


@pytest.fixture()
def client():
    """Create a FastAPI TestClient with the webhook router mounted."""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from integrations.webhook_server import webhook_router

    test_app = FastAPI()
    test_app.include_router(webhook_router)
    return TestClient(test_app)


def _post_webhook(
    client,
    event: str,
    payload: dict[str, Any],
    *,
    secret: str = "",
    delivery: str = "test-delivery-1",
) -> Any:
    """Send a webhook POST with correct headers and optional signature."""
    body = json.dumps(payload).encode()
    headers = {
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery,
        "Content-Type": "application/json",
    }
    if secret:
        headers["X-Hub-Signature-256"] = _make_signature(body, secret)
    return client.post("/webhooks/github", content=body, headers=headers)


class TestWebhookEndpoint:
    """Tests for the POST /webhooks/github endpoint."""

    def test_unknown_event_ignored(self, client):
        resp = _post_webhook(client, "ping", {"zen": "keep it simple"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ignored"

    def test_signature_required_when_secret_set(self, client):
        with patch("integrations.webhook_server.WEBHOOK_SECRET", "s3cret"):
            resp = _post_webhook(client, "issues", {"action": "opened"})
        assert resp.status_code == 403

    def test_signature_accepted(self, client):
        secret = "s3cret"
        payload = {"action": "opened", "issue": {"labels": []}}
        with patch("integrations.webhook_server.WEBHOOK_SECRET", secret):
            resp = _post_webhook(client, "issues", payload, secret=secret)
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Issue event handling
# ---------------------------------------------------------------------------


class TestIssuesEvent:
    """Tests for the issues event handler."""

    def test_ignores_non_forge_issue_opened(self, client):
        payload = {
            "action": "opened",
            "issue": _issue_payload(labels=[{"name": "bug"}]),
            "repository": _repo_payload(),
        }
        resp = _post_webhook(client, "issues", payload)
        assert resp.status_code == 200
        assert resp.json()["action"] == "ignored"

    @patch("integrations.webhook_server._get_temporal")
    @patch("integrations.webhook_server._get_db")
    def test_starts_pipeline_on_forge_label_opened(
        self, mock_db, mock_temporal, client,
    ):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock(return_value=None)
        mock_temporal.return_value = mock_client

        mock_pool = AsyncMock()
        mock_db.return_value = mock_pool

        payload = {
            "action": "opened",
            "issue": _issue_payload(labels=[{"name": "forge"}]),
            "repository": _repo_payload(),
        }
        resp = _post_webhook(client, "issues", payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "pipeline_started"
        assert "pipeline_id" in data

        # Verify Temporal was called
        mock_client.start_workflow.assert_called_once()

        # Clean up tracking map
        _issue_pipeline_map.clear()

    @patch("integrations.webhook_server._get_temporal")
    @patch("integrations.webhook_server._get_db")
    def test_starts_pipeline_on_labeled_action(
        self, mock_db, mock_temporal, client,
    ):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock(return_value=None)
        mock_temporal.return_value = mock_client

        mock_pool = AsyncMock()
        mock_db.return_value = mock_pool

        payload = {
            "action": "labeled",
            "label": {"name": "forge"},
            "issue": _issue_payload(
                number=99,
                labels=[{"name": "forge"}, {"name": "feature"}],
            ),
            "repository": _repo_payload(),
        }
        resp = _post_webhook(client, "issues", payload)
        assert resp.status_code == 200
        assert resp.json()["action"] == "pipeline_started"

        _issue_pipeline_map.clear()

    @patch("integrations.webhook_server._get_temporal")
    @patch("integrations.webhook_server._get_db")
    def test_skips_duplicate_issue(self, mock_db, mock_temporal, client):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock(return_value=None)
        mock_temporal.return_value = mock_client

        mock_pool = AsyncMock()
        mock_db.return_value = mock_pool

        # Pre-register issue
        _issue_pipeline_map["acme/widgets#42"] = "existing123"

        payload = {
            "action": "opened",
            "issue": _issue_payload(labels=[{"name": "forge"}]),
            "repository": _repo_payload(),
        }
        resp = _post_webhook(client, "issues", payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "skipped"
        assert data["pipeline_id"] == "existing123"

        # Temporal should NOT have been called
        mock_client.start_workflow.assert_not_called()

        _issue_pipeline_map.clear()

    def test_ignores_labeled_with_non_forge_label(self, client):
        payload = {
            "action": "labeled",
            "label": {"name": "bug"},
            "issue": _issue_payload(labels=[{"name": "bug"}]),
            "repository": _repo_payload(),
        }
        resp = _post_webhook(client, "issues", payload)
        assert resp.status_code == 200
        assert resp.json()["action"] == "ignored"

    def test_ignores_closed_action(self, client):
        payload = {
            "action": "closed",
            "issue": _issue_payload(labels=[{"name": "forge"}]),
            "repository": _repo_payload(),
        }
        resp = _post_webhook(client, "issues", payload)
        assert resp.status_code == 200
        assert resp.json()["action"] == "ignored"


# ---------------------------------------------------------------------------
# Issue comment event handling
# ---------------------------------------------------------------------------


class TestIssueCommentEvent:
    """Tests for /forge slash commands in issue comments."""

    def test_ignores_edited_comment(self, client):
        payload = {
            "action": "edited",
            "comment": {"body": "/forge status", "user": {"login": "dev"}},
            "issue": _issue_payload(),
            "repository": _repo_payload(),
        }
        resp = _post_webhook(client, "issue_comment", payload)
        assert resp.status_code == 200
        assert resp.json()["action"] == "ignored"

    def test_ignores_comment_without_command(self, client):
        payload = {
            "action": "created",
            "comment": {"body": "Looks good!", "user": {"login": "dev"}},
            "issue": _issue_payload(),
            "repository": _repo_payload(),
        }
        resp = _post_webhook(client, "issue_comment", payload)
        assert resp.status_code == 200
        assert resp.json()["action"] == "ignored"

    def test_approve_no_tracked_pipeline(self, client):
        payload = {
            "action": "created",
            "comment": {
                "body": "/forge approve architecture",
                "user": {"login": "dev"},
            },
            "issue": _issue_payload(number=888),
            "repository": _repo_payload(),
        }
        resp = _post_webhook(client, "issue_comment", payload)
        assert resp.status_code == 200
        assert resp.json()["action"] == "ignored"
        assert "no tracked pipeline" in resp.json()["reason"]

    @patch("integrations.webhook_server._get_temporal")
    def test_approve_sends_signal(self, mock_temporal, client):
        mock_client = MagicMock()
        mock_handle = MagicMock()
        mock_handle.signal = AsyncMock()
        mock_client.get_workflow_handle.return_value = mock_handle
        mock_temporal.return_value = mock_client

        # Register pipeline for issue
        _issue_pipeline_map["acme/widgets#42"] = "pipe-abc"

        payload = {
            "action": "created",
            "comment": {
                "body": "/forge approve business_analysis",
                "user": {"login": "pm-user"},
            },
            "issue": _issue_payload(),
            "repository": _repo_payload(),
        }
        resp = _post_webhook(client, "issue_comment", payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "approved"
        assert data["stage"] == "business_analysis"

        mock_handle.signal.assert_called_once()

        _issue_pipeline_map.clear()

    @patch("integrations.webhook_server._get_temporal")
    def test_approve_invalid_stage(self, mock_temporal, client):
        mock_temporal.return_value = MagicMock()
        _issue_pipeline_map["acme/widgets#42"] = "pipe-abc"

        payload = {
            "action": "created",
            "comment": {
                "body": "/forge approve nonexistent_stage",
                "user": {"login": "dev"},
            },
            "issue": _issue_payload(),
            "repository": _repo_payload(),
        }
        resp = _post_webhook(client, "issue_comment", payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "error"
        assert "invalid stage" in data["reason"]

        _issue_pipeline_map.clear()

    @patch("integrations.webhook_server._get_temporal")
    def test_abort_sends_signal(self, mock_temporal, client):
        mock_client = MagicMock()
        mock_handle = MagicMock()
        mock_handle.signal = AsyncMock()
        mock_client.get_workflow_handle.return_value = mock_handle
        mock_temporal.return_value = mock_client

        _issue_pipeline_map["acme/widgets#42"] = "pipe-xyz"

        payload = {
            "action": "created",
            "comment": {"body": "/forge abort", "user": {"login": "pm-user"}},
            "issue": _issue_payload(),
            "repository": _repo_payload(),
        }
        resp = _post_webhook(client, "issue_comment", payload)
        assert resp.status_code == 200
        assert resp.json()["action"] == "aborted"

        mock_handle.signal.assert_called_once()
        _issue_pipeline_map.clear()

    def test_abort_no_tracked_pipeline(self, client):
        payload = {
            "action": "created",
            "comment": {"body": "/forge abort", "user": {"login": "dev"}},
            "issue": _issue_payload(number=777),
            "repository": _repo_payload(),
        }
        resp = _post_webhook(client, "issue_comment", payload)
        assert resp.status_code == 200
        assert resp.json()["action"] == "ignored"

    @patch("integrations.webhook_server._get_temporal")
    def test_status_queries_and_replies(self, mock_temporal, client):
        mock_client = MagicMock()
        mock_handle = MagicMock()
        mock_handle.query = AsyncMock(
            return_value={
                "current_stage": "coding",
                "total_cost_usd": 1.23,
                "aborted": False,
                "pending_approval": None,
            },
        )
        mock_client.get_workflow_handle.return_value = mock_handle
        mock_temporal.return_value = mock_client

        _issue_pipeline_map["acme/widgets#42"] = "pipe-st"

        payload = {
            "action": "created",
            "comment": {"body": "/forge status", "user": {"login": "dev"}},
            "issue": _issue_payload(),
            "repository": _repo_payload(),
        }
        resp = _post_webhook(client, "issue_comment", payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "status"
        assert data["state"]["current_stage"] == "coding"

        _issue_pipeline_map.clear()

    def test_status_no_tracked_pipeline(self, client):
        payload = {
            "action": "created",
            "comment": {"body": "/forge status", "user": {"login": "dev"}},
            "issue": _issue_payload(number=666),
            "repository": _repo_payload(),
        }
        resp = _post_webhook(client, "issue_comment", payload)
        assert resp.status_code == 200
        assert resp.json()["action"] == "ignored"


# ---------------------------------------------------------------------------
# PR review event (stub)
# ---------------------------------------------------------------------------


class TestPRReviewEvent:
    """Tests for pull_request_review events (currently a no-op)."""

    def test_pr_review_ignored(self, client):
        payload = {
            "action": "submitted",
            "review": {"state": "changes_requested"},
            "pull_request": {"number": 5},
            "repository": _repo_payload(),
        }
        resp = _post_webhook(client, "pull_request_review", payload)
        assert resp.status_code == 200
        assert resp.json()["action"] == "ignored"


# ---------------------------------------------------------------------------
# Business spec construction
# ---------------------------------------------------------------------------


class TestBusinessSpec:
    """Verify the business spec is correctly built from issue content."""

    @patch("integrations.webhook_server._get_temporal")
    @patch("integrations.webhook_server._get_db")
    def test_spec_includes_title_and_body(self, mock_db, mock_temporal, client):
        mock_client = MagicMock()
        mock_client.start_workflow = AsyncMock(return_value=None)
        mock_temporal.return_value = mock_client
        mock_db.return_value = AsyncMock()

        payload = {
            "action": "opened",
            "issue": _issue_payload(
                title="Implement SSO",
                body="Support SAML and OIDC",
                labels=[{"name": "forge"}],
            ),
            "repository": _repo_payload(owner="myorg", name="platform"),
        }
        resp = _post_webhook(client, "issues", payload)
        assert resp.status_code == 200

        # Inspect what was passed to start_workflow
        call_args = mock_client.start_workflow.call_args
        pipeline_input = call_args[0][1]  # second positional arg
        assert "Implement SSO" in pipeline_input.business_spec
        assert "Support SAML and OIDC" in pipeline_input.business_spec
        assert "myorg/platform#42" in pipeline_input.business_spec
        assert pipeline_input.repo_owner == "myorg"
        assert pipeline_input.repo_name == "platform"
        assert pipeline_input.issue_number == 42

        _issue_pipeline_map.clear()
