"""OAuth flow management for MCP service connections.

Handles the OAuth authorization code flow for services that support it
(Notion, Linear, Figma, Google Drive).  Jira uses token-based auth.

The flow:
1. ``start_oauth()`` builds an authorize URL with a CSRF state token
2. User is redirected to the service's authorization page
3. Service redirects back to our callback URL with an auth code
4. ``exchange_oauth_code()`` exchanges the code for access/refresh tokens
5. Tokens are encrypted and stored in ``org_secrets``

Usage::

    from connections.oauth import OAuthManager

    mgr = OAuthManager()
    url = await mgr.start_oauth("org-123", ServiceType.NOTION, "https://forge.dev/api/...")
    # ... user completes OAuth ...
    tokens = await mgr.exchange_oauth_code(ServiceType.NOTION, code, redirect_uri)
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from typing import Any
from urllib.parse import urlencode

import structlog

from connections.models import OAUTH_CONFIGS, ServiceType

log = structlog.get_logger().bind(component="connections.oauth")

# State tokens are cached in Redis with a short TTL
_STATE_TTL = 600  # 10 minutes


class OAuthManager:
    """Manages OAuth authorization flows for MCP service connections."""

    def __init__(self) -> None:
        self._redis: Any = None

    def _get_redis(self) -> Any:
        if self._redis is None:
            try:
                from api.server import _redis
                self._redis = _redis
            except (ImportError, AttributeError):
                raise RuntimeError("Redis not available for OAuth state management")
        return self._redis

    # ── Start flow ─────────────────────────────────────────

    async def start_oauth(
        self,
        org_id: str,
        service: ServiceType,
        redirect_uri: str,
        *,
        user_id: str = "",
        connection_id: str | None = None,
    ) -> dict:
        """Build an authorization URL and store the state token.

        Returns ``{"authorize_url": "...", "state": "..."}``.
        """
        oauth_config = OAUTH_CONFIGS.get(service)
        if oauth_config is None:
            raise ValueError(f"OAuth not supported for {service.value}")

        client_id = os.environ.get(oauth_config["env_client_id"])
        if not client_id:
            raise ValueError(
                f"Missing {oauth_config['env_client_id']} environment variable. "
                f"{oauth_config.get('setup_instructions', '')}"
            )

        # Generate CSRF state token
        state = secrets.token_urlsafe(32)

        # Store state -> metadata mapping in Redis
        state_data = {
            "org_id": org_id,
            "service": service.value,
            "user_id": user_id,
            "connection_id": connection_id,
            "redirect_uri": redirect_uri,
            "created_at": time.time(),
        }
        redis = self._get_redis()
        await redis.setex(
            f"forge:oauth_state:{state}",
            _STATE_TTL,
            json.dumps(state_data),
        )

        # Build authorize URL
        params: dict[str, str] = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "state": state,
        }
        scopes = oauth_config.get("scopes", [])
        if scopes:
            params["scope"] = " ".join(scopes)

        # Service-specific extra params (e.g. Google's access_type=offline)
        extra = oauth_config.get("extra_params", {})
        params.update(extra)

        # Notion uses "owner" param for the owner type
        if service == ServiceType.NOTION:
            params["owner"] = "user"

        authorize_url = f"{oauth_config['authorize_url']}?{urlencode(params)}"

        log.info(
            "OAuth flow started",
            service=service.value,
            org_id=org_id,
        )

        return {
            "authorize_url": authorize_url,
            "state": state,
        }

    # ── Validate state ─────────────────────────────────────

    async def validate_state(self, state: str) -> dict:
        """Validate and consume the OAuth state token.

        Returns the metadata dict stored during ``start_oauth()``.
        Raises ``ValueError`` if the state is invalid or expired.
        """
        redis = self._get_redis()
        key = f"forge:oauth_state:{state}"
        raw = await redis.get(key)
        if raw is None:
            raise ValueError("Invalid or expired OAuth state token")

        # Consume the state (one-time use)
        await redis.delete(key)
        return json.loads(raw)

    # ── Exchange code for tokens ───────────────────────────

    async def exchange_oauth_code(
        self,
        service: ServiceType,
        code: str,
        redirect_uri: str,
    ) -> dict:
        """Exchange an authorization code for access and refresh tokens.

        Returns ``{"access_token": "...", "refresh_token": "...", ...}``.
        """
        import httpx

        oauth_config = OAUTH_CONFIGS.get(service)
        if oauth_config is None:
            raise ValueError(f"OAuth not supported for {service.value}")

        client_id = os.environ.get(oauth_config["env_client_id"], "")
        client_secret = os.environ.get(oauth_config["env_client_secret"], "")
        if not client_id or not client_secret:
            raise ValueError(
                f"Missing OAuth credentials for {service.value}. "
                f"Set {oauth_config['env_client_id']} and "
                f"{oauth_config['env_client_secret']}."
            )

        token_url = oauth_config["token_url"]
        token_auth = oauth_config.get("token_auth", "post_body")

        body: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }

        headers: dict[str, str] = {
            "Accept": "application/json",
        }
        auth = None

        if token_auth == "basic":
            # Notion-style: client credentials in Basic auth header
            import base64
            creds = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
            headers["Authorization"] = f"Basic {creds}"
        else:
            # Most services: client credentials in POST body
            body["client_id"] = client_id
            body["client_secret"] = client_secret

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                token_url,
                data=body,
                headers=headers,
            )

        if resp.status_code != 200:
            log.error(
                "OAuth token exchange failed",
                service=service.value,
                status=resp.status_code,
                body=resp.text[:500],
            )
            raise RuntimeError(
                f"OAuth token exchange failed for {service.value}: "
                f"{resp.status_code} {resp.text[:200]}"
            )

        token_data = resp.json()

        log.info(
            "OAuth token exchange succeeded",
            service=service.value,
            has_refresh=bool(token_data.get("refresh_token")),
        )

        return token_data

    # ── Store tokens ───────────────────────────────────────

    async def store_oauth_tokens(
        self,
        org_id: str,
        service: ServiceType,
        token_data: dict,
        *,
        connection_id: str | None = None,
        display_name: str = "",
    ) -> str:
        """Encrypt and store OAuth tokens in org_secrets.

        Returns the credential secret key used for storage.
        """
        from auth.secrets import set_org_secret

        # Build the token payload to store
        # Keep the full response (access_token, refresh_token, expires_in, etc.)
        credential_value = json.dumps({
            "access_token": token_data.get("access_token", ""),
            "refresh_token": token_data.get("refresh_token"),
            "token_type": token_data.get("token_type", "Bearer"),
            "expires_in": token_data.get("expires_in"),
            "scope": token_data.get("scope"),
        })

        label = display_name or service.value
        secret_key = f"mcp_{service.value}_{label.lower().replace(' ', '_')}"

        await set_org_secret(org_id, secret_key, credential_value, "oauth")

        log.info(
            "OAuth tokens stored",
            service=service.value,
            org_id=org_id,
            secret_key=secret_key,
        )

        return secret_key


# Module-level singleton
_oauth_manager: OAuthManager | None = None


def get_oauth_manager() -> OAuthManager:
    global _oauth_manager  # noqa: PLW0603
    if _oauth_manager is None:
        _oauth_manager = OAuthManager()
    return _oauth_manager
