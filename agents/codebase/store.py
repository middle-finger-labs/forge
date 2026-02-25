"""pgvector-backed storage for code chunks.

Manages the ``code_chunks`` and ``code_index_state`` tables, providing:

- **Upsert** — insert or update chunks with their dual embeddings
- **Hybrid search** — combine code-similarity and description-similarity
  scores with configurable weights
- **Incremental re-index** — delete stale chunks for changed files, then
  insert fresh ones
- **Repo stats** — chunk counts, language breakdown, freshness

Follows the same asyncpg connection-pool pattern as
:class:`memory.state_store.StateStore`.
"""

from __future__ import annotations

import json
import os
from typing import Any

import structlog

from agents.codebase.embedder import EmbeddedChunk

log = structlog.get_logger().bind(component="code_chunk_store")


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://forge:forge_dev_password@localhost:5432/forge_app",
    )


def _vec_literal(vec: list[float]) -> str:
    """Convert a float list to a pgvector literal string."""
    return f"[{','.join(str(v) for v in vec)}]"


class CodeChunkStore:
    """Async pgvector store for AST-parsed code chunks.

    Usage::

        store = CodeChunkStore()
        await store.upsert_chunks(embedded_chunks, org_id="org-1",
                                   repo_url="https://github.com/org/repo",
                                   commit_sha="abc123")

        results = await store.search("validate email input",
                                      org_id="org-1", repo_url="...", limit=10)
    """

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or _dsn()
        self._pool = None

    async def _ensure_pool(self):
        if self._pool is not None:
            return self._pool

        import asyncpg

        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
        log.info("code chunk store pool created")

        # Ensure tables exist (idempotent)
        async with self._pool.acquire() as conn:
            await conn.execute(_CREATE_TABLES_SQL)

        return self._pool

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def upsert_chunks(
        self,
        chunks: list[EmbeddedChunk],
        *,
        org_id: str,
        repo_url: str,
        commit_sha: str,
    ) -> int:
        """Insert or update code chunks with their embeddings.

        Uses ON CONFLICT to update existing chunks (matched by org, repo,
        file path, qualified name, and chunk type).

        Returns the number of rows upserted.
        """
        if not chunks:
            return 0

        pool = await self._ensure_pool()
        count = 0

        async with pool.acquire() as conn:
            # Use a prepared statement for bulk inserts
            stmt = await conn.prepare("""
                INSERT INTO code_chunks (
                    org_id, repo_url, commit_sha, file_path, language,
                    chunk_type, name, qualified_name, signature, docstring,
                    body, start_line, end_line, parent_name, metadata,
                    code_embedding, description_embedding, updated_at
                ) VALUES (
                    $1, $2, $3, $4, $5,
                    $6, $7, $8, $9, $10,
                    $11, $12, $13, $14, $15::jsonb,
                    $16::vector, $17::vector, now()
                )
                ON CONFLICT (org_id, repo_url, file_path, qualified_name, chunk_type)
                DO UPDATE SET
                    commit_sha = EXCLUDED.commit_sha,
                    language = EXCLUDED.language,
                    name = EXCLUDED.name,
                    signature = EXCLUDED.signature,
                    docstring = EXCLUDED.docstring,
                    body = EXCLUDED.body,
                    start_line = EXCLUDED.start_line,
                    end_line = EXCLUDED.end_line,
                    parent_name = EXCLUDED.parent_name,
                    metadata = EXCLUDED.metadata,
                    code_embedding = EXCLUDED.code_embedding,
                    description_embedding = EXCLUDED.description_embedding,
                    updated_at = now()
            """)

            for ec in chunks:
                c = ec.chunk
                await stmt.fetch(
                    org_id,
                    repo_url,
                    commit_sha,
                    c.file_path,
                    c.language,
                    c.chunk_type,
                    c.name,
                    c.qualified_name,
                    c.signature,
                    c.docstring,
                    c.body,
                    c.start_line,
                    c.end_line,
                    c.parent_name,
                    json.dumps(c.metadata, default=str),
                    _vec_literal(ec.code_embedding),
                    _vec_literal(ec.description_embedding),
                )
                count += 1

        log.info("chunks upserted", count=count, repo=repo_url)
        return count

    async def delete_file_chunks(
        self,
        *,
        org_id: str,
        repo_url: str,
        file_paths: list[str],
    ) -> int:
        """Delete all chunks for the given files (used before incremental re-index)."""
        if not file_paths:
            return 0

        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM code_chunks
                WHERE org_id = $1 AND repo_url = $2 AND file_path = ANY($3::text[])
                """,
                org_id,
                repo_url,
                file_paths,
            )
            deleted = int(result.split()[-1])
            log.info("file chunks deleted", files=len(file_paths), deleted=deleted)
            return deleted

    async def delete_repo(self, *, org_id: str, repo_url: str) -> int:
        """Delete all chunks and index state for a repository."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM code_chunks WHERE org_id = $1 AND repo_url = $2",
                org_id,
                repo_url,
            )
            await conn.execute(
                "DELETE FROM code_index_state WHERE org_id = $1 AND repo_url = $2",
                org_id,
                repo_url,
            )
            deleted = int(result.split()[-1])
            log.info("repo deleted from index", repo=repo_url, deleted=deleted)
            return deleted

    # ------------------------------------------------------------------
    # Index state tracking
    # ------------------------------------------------------------------

    async def get_last_commit(self, *, org_id: str, repo_url: str) -> str | None:
        """Return the last indexed commit SHA, or None if never indexed."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            return await conn.fetchval(
                "SELECT last_commit FROM code_index_state WHERE org_id = $1 AND repo_url = $2",
                org_id,
                repo_url,
            )

    async def update_index_state(
        self,
        *,
        org_id: str,
        repo_url: str,
        commit_sha: str,
        file_count: int,
        chunk_count: int,
    ) -> None:
        """Record the latest indexed commit for a repo."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                INSERT INTO code_index_state
                    (org_id, repo_url, last_commit, file_count, chunk_count, indexed_at)
                VALUES ($1, $2, $3, $4, $5, now())
                ON CONFLICT (org_id, repo_url)
                DO UPDATE SET
                    last_commit = EXCLUDED.last_commit,
                    file_count = EXCLUDED.file_count,
                    chunk_count = EXCLUDED.chunk_count,
                    indexed_at = now()
                """,
                org_id,
                repo_url,
                commit_sha,
                file_count,
                chunk_count,
            )

    # ------------------------------------------------------------------
    # Search operations
    # ------------------------------------------------------------------

    async def search(
        self,
        query_embedding: list[float],
        *,
        org_id: str,
        repo_url: str | None = None,
        limit: int = 10,
        language: str | None = None,
        chunk_types: list[str] | None = None,
        mode: str = "description",
    ) -> list[dict]:
        """Search code chunks by embedding similarity.

        Args:
            query_embedding: The query vector (384-dim).
            org_id: Required org scope.
            repo_url: Optional repo filter.
            limit: Max results.
            language: Optional language filter.
            chunk_types: Optional filter on chunk_type (e.g. ["function", "method"]).
            mode: Which embedding to search against:
                  "description" (default) — NL query against description embeddings
                  "code" — code-to-code similarity
                  "hybrid" — weighted combination of both

        Returns:
            List of dicts with chunk data + similarity score.
        """
        pool = await self._ensure_pool()
        vec_str = _vec_literal(query_embedding)

        # Build WHERE clause
        conditions = ["org_id = $1"]
        params: list[Any] = [org_id]
        idx = 2

        if repo_url:
            conditions.append(f"repo_url = ${idx}")
            params.append(repo_url)
            idx += 1

        if language:
            conditions.append(f"language = ${idx}")
            params.append(language)
            idx += 1

        if chunk_types:
            conditions.append(f"chunk_type = ANY(${idx}::text[])")
            params.append(chunk_types)
            idx += 1

        where = " AND ".join(conditions)
        params.append(limit)
        limit_idx = idx

        # Select the ordering based on mode
        if mode == "code":
            null_filter = "code_embedding IS NOT NULL"
            score_expr = f"1 - (code_embedding <=> '{vec_str}'::vector)"
            order_expr = f"code_embedding <=> '{vec_str}'::vector"
        elif mode == "hybrid":
            null_filter = "code_embedding IS NOT NULL AND description_embedding IS NOT NULL"
            # Weighted average: 0.3 code + 0.7 description
            score_expr = (
                f"0.3 * (1 - (code_embedding <=> '{vec_str}'::vector)) + "
                f"0.7 * (1 - (description_embedding <=> '{vec_str}'::vector))"
            )
            order_expr = score_expr + " DESC"
            # For hybrid, we order by the combined score descending
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    f"""
                    SELECT id, file_path, language, chunk_type, name, qualified_name,
                           signature, docstring, body, start_line, end_line,
                           parent_name, metadata, commit_sha,
                           {score_expr} AS score
                    FROM code_chunks
                    WHERE {where} AND {null_filter}
                    ORDER BY score DESC
                    LIMIT ${limit_idx}
                    """,
                    *params,
                )
            return self._rows_to_results(rows)
        else:
            # Default: description
            null_filter = "description_embedding IS NOT NULL"
            score_expr = f"1 - (description_embedding <=> '{vec_str}'::vector)"
            order_expr = f"description_embedding <=> '{vec_str}'::vector"

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, file_path, language, chunk_type, name, qualified_name,
                       signature, docstring, body, start_line, end_line,
                       parent_name, metadata, commit_sha,
                       {score_expr} AS score
                FROM code_chunks
                WHERE {where} AND {null_filter}
                ORDER BY {order_expr}
                LIMIT ${limit_idx}
                """,
                *params,
            )

        return self._rows_to_results(rows)

    async def search_by_name(
        self,
        name_pattern: str,
        *,
        org_id: str,
        repo_url: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """Search chunks by name using ILIKE pattern matching."""
        pool = await self._ensure_pool()

        conditions = ["org_id = $1", "qualified_name ILIKE $2"]
        params: list[Any] = [org_id, f"%{name_pattern}%"]
        idx = 3

        if repo_url:
            conditions.append(f"repo_url = ${idx}")
            params.append(repo_url)
            idx += 1

        where = " AND ".join(conditions)
        params.append(limit)

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, file_path, language, chunk_type, name, qualified_name,
                       signature, docstring, body, start_line, end_line,
                       parent_name, metadata, commit_sha,
                       1.0 AS score
                FROM code_chunks
                WHERE {where}
                ORDER BY qualified_name
                LIMIT ${idx}
                """,
                *params,
            )

        return self._rows_to_results(rows)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    async def get_repo_stats(self, *, org_id: str, repo_url: str) -> dict:
        """Return indexing statistics for a repository."""
        pool = await self._ensure_pool()
        async with pool.acquire() as conn:
            total = await conn.fetchval(
                "SELECT COUNT(*) FROM code_chunks WHERE org_id = $1 AND repo_url = $2",
                org_id,
                repo_url,
            ) or 0

            lang_rows = await conn.fetch(
                """
                SELECT language, COUNT(*) AS count
                FROM code_chunks
                WHERE org_id = $1 AND repo_url = $2
                GROUP BY language ORDER BY count DESC
                """,
                org_id,
                repo_url,
            )

            type_rows = await conn.fetch(
                """
                SELECT chunk_type, COUNT(*) AS count
                FROM code_chunks
                WHERE org_id = $1 AND repo_url = $2
                GROUP BY chunk_type ORDER BY count DESC
                """,
                org_id,
                repo_url,
            )

            state = await conn.fetchrow(
                "SELECT last_commit, file_count, chunk_count, indexed_at "
                "FROM code_index_state WHERE org_id = $1 AND repo_url = $2",
                org_id,
                repo_url,
            )

            return {
                "total_chunks": total,
                "by_language": {r["language"]: r["count"] for r in lang_rows},
                "by_type": {r["chunk_type"]: r["count"] for r in type_rows},
                "last_commit": state["last_commit"] if state else None,
                "file_count": state["file_count"] if state else 0,
                "indexed_at": (
                    state["indexed_at"].isoformat()
                    if state and state["indexed_at"]
                    else None
                ),
            }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _rows_to_results(rows) -> list[dict]:
        results = []
        for r in rows:
            meta = r["metadata"]
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (json.JSONDecodeError, TypeError):
                    meta = {}

            results.append({
                "id": str(r["id"]),
                "file_path": r["file_path"],
                "language": r["language"],
                "chunk_type": r["chunk_type"],
                "name": r["name"],
                "qualified_name": r["qualified_name"],
                "signature": r["signature"],
                "docstring": r["docstring"],
                "body": r["body"],
                "start_line": r["start_line"],
                "end_line": r["end_line"],
                "parent_name": r["parent_name"],
                "metadata": meta,
                "commit_sha": r["commit_sha"],
                "score": float(r.get("score", 0)),
            })
        return results

    async def close(self):
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None


# ---------------------------------------------------------------------------
# Table creation SQL (idempotent)
# ---------------------------------------------------------------------------

_CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS code_chunks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          TEXT NOT NULL,
    repo_url        TEXT NOT NULL,
    commit_sha      TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    language        TEXT NOT NULL,
    chunk_type      TEXT NOT NULL,
    name            TEXT NOT NULL,
    qualified_name  TEXT NOT NULL,
    signature       TEXT NOT NULL DEFAULT '',
    docstring       TEXT NOT NULL DEFAULT '',
    body            TEXT NOT NULL,
    start_line      INT NOT NULL,
    end_line        INT NOT NULL,
    parent_name     TEXT,
    metadata        JSONB NOT NULL DEFAULT '{}',
    code_embedding      vector(384),
    description_embedding vector(384),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_code_chunks_identity
    ON code_chunks (org_id, repo_url, file_path, qualified_name, chunk_type);

CREATE INDEX IF NOT EXISTS idx_code_chunks_org_repo
    ON code_chunks (org_id, repo_url);

CREATE INDEX IF NOT EXISTS idx_code_chunks_file
    ON code_chunks (org_id, repo_url, file_path);

CREATE INDEX IF NOT EXISTS idx_code_chunks_language
    ON code_chunks (language);

CREATE TABLE IF NOT EXISTS code_index_state (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      TEXT NOT NULL,
    repo_url    TEXT NOT NULL,
    last_commit TEXT NOT NULL,
    file_count  INT NOT NULL DEFAULT 0,
    chunk_count INT NOT NULL DEFAULT 0,
    indexed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, repo_url)
);
"""
