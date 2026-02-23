"""Per-org secrets management with Fernet symmetric encryption.

Secrets are stored encrypted in PostgreSQL (``org_secrets`` table) using a
master key from the ``FORGE_ENCRYPTION_KEY`` environment variable.

Generate a key::

    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

Usage::

    from auth.secrets import get_org_secret, set_org_secret

    key = await get_org_secret("org-123", "ANTHROPIC_API_KEY")
    await set_org_secret("org-123", "ANTHROPIC_API_KEY", "sk-ant-...", "user-456")
"""

from __future__ import annotations

import os

import asyncpg
import structlog
from cryptography.fernet import Fernet, InvalidToken

log = structlog.get_logger().bind(component="secrets")

# ---------------------------------------------------------------------------
# Encryption key
# ---------------------------------------------------------------------------

_ENCRYPTION_KEY = os.environ.get("FORGE_ENCRYPTION_KEY", "")


def _get_fernet() -> Fernet:
    """Return a Fernet instance using the master key.

    Raises ``RuntimeError`` if ``FORGE_ENCRYPTION_KEY`` is not set.
    """
    key = _ENCRYPTION_KEY or os.environ.get("FORGE_ENCRYPTION_KEY", "")
    if not key:
        raise RuntimeError(
            "FORGE_ENCRYPTION_KEY is not set. Generate one with:\n"
            "  python -c \"from cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())\""
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


# ---------------------------------------------------------------------------
# Low-level encrypt / decrypt
# ---------------------------------------------------------------------------


def encrypt_secret(plaintext: str) -> bytes:
    """Encrypt a plaintext string and return ciphertext bytes."""
    f = _get_fernet()
    return f.encrypt(plaintext.encode("utf-8"))


def decrypt_secret(ciphertext: bytes) -> str:
    """Decrypt ciphertext bytes and return the original plaintext string.

    Raises ``ValueError`` if the ciphertext is invalid or the key is wrong.
    """
    f = _get_fernet()
    try:
        return f.decrypt(ciphertext).decode("utf-8")
    except InvalidToken as exc:
        raise ValueError("Failed to decrypt secret — wrong key or corrupted data") from exc


# ---------------------------------------------------------------------------
# Database helpers (require an asyncpg pool)
# ---------------------------------------------------------------------------

# Lazy pool reference — set by the API server lifespan
_db_pool: asyncpg.Pool | None = None


def set_db_pool(pool: asyncpg.Pool) -> None:
    """Inject the database pool (called once during app startup)."""
    global _db_pool  # noqa: PLW0603
    _db_pool = pool


def _get_pool() -> asyncpg.Pool:
    assert _db_pool is not None, "Secrets DB pool not initialised — call set_db_pool() first"
    return _db_pool


async def get_org_secret(org_id: str, key: str) -> str | None:
    """Fetch and decrypt a single org secret. Returns ``None`` if not found."""
    pool = _get_pool()
    row = await pool.fetchrow(
        "SELECT encrypted_value FROM org_secrets WHERE org_id = $1 AND key = $2",
        org_id,
        key,
    )
    if row is None:
        return None
    try:
        return decrypt_secret(bytes(row["encrypted_value"]))
    except ValueError:
        log.error("failed to decrypt secret", org_id=org_id, key=key)
        return None


async def set_org_secret(org_id: str, key: str, value: str, user_id: str) -> None:
    """Encrypt and store (upsert) an org secret."""
    pool = _get_pool()
    encrypted = encrypt_secret(value)
    await pool.execute(
        """
        INSERT INTO org_secrets (org_id, key, encrypted_value, created_by, updated_at)
        VALUES ($1, $2, $3, $4, NOW())
        ON CONFLICT (org_id, key)
        DO UPDATE SET encrypted_value = EXCLUDED.encrypted_value,
                      created_by = EXCLUDED.created_by,
                      updated_at = NOW()
        """,
        org_id,
        key,
        encrypted,
        user_id,
    )
    log.info("secret stored", org_id=org_id, key=key, user_id=user_id)


async def delete_org_secret(org_id: str, key: str) -> bool:
    """Delete an org secret. Returns ``True`` if a row was deleted."""
    pool = _get_pool()
    result = await pool.execute(
        "DELETE FROM org_secrets WHERE org_id = $1 AND key = $2",
        org_id,
        key,
    )
    deleted = result != "DELETE 0"
    if deleted:
        log.info("secret deleted", org_id=org_id, key=key)
    return deleted


async def list_org_secret_keys(org_id: str) -> list[str]:
    """List all secret key names for an org (no values returned)."""
    pool = _get_pool()
    rows = await pool.fetch(
        "SELECT key FROM org_secrets WHERE org_id = $1 ORDER BY key",
        org_id,
    )
    return [r["key"] for r in rows]


# ---------------------------------------------------------------------------
# Org settings helpers
# ---------------------------------------------------------------------------


async def get_org_settings(org_id: str) -> dict | None:
    """Fetch org settings, returning ``None`` if no row exists."""
    pool = _get_pool()
    row = await pool.fetchrow(
        "SELECT * FROM org_settings WHERE org_id = $1",
        org_id,
    )
    if row is None:
        return None
    d = dict(row)
    d["auto_approve_stages"] = list(d.get("auto_approve_stages") or [])
    d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
    d["updated_at"] = d["updated_at"].isoformat() if d.get("updated_at") else None
    return d


async def upsert_org_settings(org_id: str, updates: dict) -> dict:
    """Create or update org settings. Returns the full settings row."""
    pool = _get_pool()

    # Build SET clause dynamically from allowed fields
    allowed = {
        "max_pipeline_cost_usd", "max_concurrent_pipelines",
        "auto_approve_stages", "default_model_tier", "pr_strategy",
    }
    set_parts = []
    values = [org_id]
    idx = 2

    for field_name, value in updates.items():
        if field_name not in allowed:
            continue
        set_parts.append(f"{field_name} = ${idx}")
        values.append(value)
        idx += 1

    if not set_parts:
        # No valid fields — just ensure the row exists with defaults
        await pool.execute(
            "INSERT INTO org_settings (org_id) VALUES ($1) ON CONFLICT DO NOTHING",
            org_id,
        )
    else:
        set_clause = ", ".join(set_parts)
        await pool.execute(
            f"""
            INSERT INTO org_settings (org_id, {', '.join(f for f in updates if f in allowed)})
            VALUES ($1, {', '.join(f'${i+2}' for i in range(len(set_parts)))})
            ON CONFLICT (org_id)
            DO UPDATE SET {set_clause}, updated_at = NOW()
            """,
            *values,
        )

    return await get_org_settings(org_id) or {"org_id": org_id}


# ---------------------------------------------------------------------------
# Org identities helpers
# ---------------------------------------------------------------------------


async def list_org_identities(org_id: str) -> list[dict]:
    """List all GitHub identities for an org (tokens/keys are NOT decrypted)."""
    pool = _get_pool()
    rows = await pool.fetch(
        """
        SELECT id, org_id, name, github_username, email, github_org,
               is_default, created_at,
               (ssh_key_encrypted IS NOT NULL) AS has_ssh_key,
               (github_token_encrypted IS NOT NULL) AS has_github_token
        FROM org_identities
        WHERE org_id = $1
        ORDER BY is_default DESC, name
        """,
        org_id,
    )
    result = []
    for r in rows:
        d = dict(r)
        d["id"] = str(d["id"])
        d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
        result.append(d)
    return result


async def get_org_identity(org_id: str, identity_id: str) -> dict | None:
    """Fetch a single identity by ID (tokens/keys NOT decrypted)."""
    pool = _get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, org_id, name, github_username, email, github_org,
               is_default, created_at,
               (ssh_key_encrypted IS NOT NULL) AS has_ssh_key,
               (github_token_encrypted IS NOT NULL) AS has_github_token
        FROM org_identities
        WHERE org_id = $1 AND id = $2::uuid
        """,
        org_id,
        identity_id,
    )
    if row is None:
        return None
    d = dict(row)
    d["id"] = str(d["id"])
    d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
    return d


async def create_org_identity(
    org_id: str,
    name: str,
    github_username: str,
    email: str,
    github_org: str | None = None,
    ssh_key: str | None = None,
    github_token: str | None = None,
    is_default: bool = False,
) -> dict:
    """Create a new GitHub identity for an org."""
    pool = _get_pool()

    ssh_encrypted = encrypt_secret(ssh_key) if ssh_key else None
    token_encrypted = encrypt_secret(github_token) if github_token else None

    # If marking as default, unset other defaults first
    if is_default:
        await pool.execute(
            "UPDATE org_identities SET is_default = FALSE WHERE org_id = $1",
            org_id,
        )

    row = await pool.fetchrow(
        """
        INSERT INTO org_identities
            (org_id, name, github_username, email, github_org,
             ssh_key_encrypted, github_token_encrypted, is_default)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id, org_id, name, github_username, email, github_org,
                  is_default, created_at,
                  (ssh_key_encrypted IS NOT NULL) AS has_ssh_key,
                  (github_token_encrypted IS NOT NULL) AS has_github_token
        """,
        org_id, name, github_username, email, github_org,
        ssh_encrypted, token_encrypted, is_default,
    )
    d = dict(row)
    d["id"] = str(d["id"])
    d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
    log.info("identity created", org_id=org_id, name=name)
    return d


async def delete_org_identity(org_id: str, identity_id: str) -> bool:
    """Delete an identity. Returns ``True`` if a row was deleted."""
    pool = _get_pool()
    result = await pool.execute(
        "DELETE FROM org_identities WHERE org_id = $1 AND id = $2::uuid",
        org_id,
        identity_id,
    )
    return result != "DELETE 0"


async def get_org_identity_token(org_id: str, identity_id: str) -> str | None:
    """Fetch and decrypt the GitHub token for an identity."""
    pool = _get_pool()
    row = await pool.fetchrow(
        "SELECT github_token_encrypted FROM org_identities WHERE org_id = $1 AND id = $2::uuid",
        org_id,
        identity_id,
    )
    if row is None or row["github_token_encrypted"] is None:
        return None
    try:
        return decrypt_secret(bytes(row["github_token_encrypted"]))
    except ValueError:
        log.error("failed to decrypt identity token", org_id=org_id, identity_id=identity_id)
        return None


async def get_default_identity_for_org(org_id: str) -> dict | None:
    """Return the default identity for an org, or the first one."""
    pool = _get_pool()
    row = await pool.fetchrow(
        """
        SELECT id, org_id, name, github_username, email, github_org,
               is_default, created_at,
               (ssh_key_encrypted IS NOT NULL) AS has_ssh_key,
               (github_token_encrypted IS NOT NULL) AS has_github_token
        FROM org_identities
        WHERE org_id = $1
        ORDER BY is_default DESC, created_at ASC
        LIMIT 1
        """,
        org_id,
    )
    if row is None:
        return None
    d = dict(row)
    d["id"] = str(d["id"])
    d["created_at"] = d["created_at"].isoformat() if d.get("created_at") else None
    return d
