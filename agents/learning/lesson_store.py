"""pgvector-backed lesson storage.

Manages the ``lessons`` table — CRUD operations plus semantic search
for injecting relevant lessons into agent prompts.

Follows the same asyncpg connection-pool pattern as
:class:`agents.codebase.store.CodeChunkStore`.
"""

from __future__ import annotations

import os
from typing import Any

import structlog

from agents.learning.types import Lesson

log = structlog.get_logger().bind(component="lesson_store")

_EMBEDDING_MODEL = "multi-qa-MiniLM-L6-cos-v1"
_EMBEDDING_DIMS = 384


def _dsn() -> str:
    return os.environ.get(
        "DATABASE_URL",
        "postgresql://forge:forge_dev_password@localhost:5432/forge_app",
    )


def _vec_literal(vec: list[float]) -> str:
    """Convert a float list to a pgvector literal string."""
    return f"[{','.join(str(v) for v in vec)}]"


_CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS lessons (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id            TEXT NOT NULL,
    agent_role        TEXT NOT NULL,
    lesson_type       TEXT NOT NULL,
    trigger_context   TEXT NOT NULL,
    lesson            TEXT NOT NULL,
    evidence          TEXT,
    pipeline_id       TEXT,
    confidence        FLOAT NOT NULL DEFAULT 0.8,
    times_applied     INT NOT NULL DEFAULT 0,
    times_reinforced  INT NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    embedding         vector(384)
);
"""


class LessonStore:
    """Async pgvector store for agent lessons learned from user feedback.

    Usage::

        store = LessonStore()
        lesson_id = await store.store_lesson(lesson, embedding)
        results = await store.search("async database calls", org_id="org-1")
    """

    def __init__(self, dsn: str | None = None) -> None:
        self._dsn = dsn or _dsn()
        self._pool = None
        self._embedder = None

    async def _ensure_pool(self):
        if self._pool is not None:
            return self._pool

        import asyncpg

        self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)

        async with self._pool.acquire() as conn:
            await conn.execute(_CREATE_TABLE_SQL)

        log.info("lesson store pool created")
        return self._pool

    def _get_embedder(self):
        """Lazy-load sentence-transformers model."""
        if self._embedder is not None:
            return self._embedder
        try:
            from sentence_transformers import SentenceTransformer

            self._embedder = SentenceTransformer(_EMBEDDING_MODEL)
            log.info("lesson embedder loaded", model=_EMBEDDING_MODEL)
        except Exception as exc:
            log.warning("sentence-transformers unavailable", error=str(exc))
        return self._embedder

    def _embed(self, text: str) -> str | None:
        """Return a pgvector-compatible literal, or None."""
        embedder = self._get_embedder()
        if embedder is None:
            return None
        vec = embedder.encode(text).tolist()
        return _vec_literal(vec)

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    async def store_lesson(
        self,
        lesson: Lesson,
        embedding: list[float] | None = None,
    ) -> str:
        """Insert a lesson and return its UUID.

        If *embedding* is not provided, one is generated from the lesson
        text using the sentence-transformers model.
        """
        pool = await self._ensure_pool()

        if embedding is not None:
            vec_str = _vec_literal(embedding)
        else:
            vec_str = self._embed(
                f"{lesson.trigger_context} {lesson.lesson}"
            )

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO lessons (
                    org_id, agent_role, lesson_type, trigger_context,
                    lesson, evidence, pipeline_id, confidence, embedding
                ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::vector)
                RETURNING id
                """,
                lesson.org_id,
                lesson.agent_role,
                lesson.lesson_type,
                lesson.trigger_context,
                lesson.lesson,
                lesson.evidence,
                lesson.pipeline_id,
                lesson.confidence,
                vec_str,
            )

        lesson_id = str(row["id"])
        log.info(
            "lesson stored",
            lesson_id=lesson_id,
            org_id=lesson.org_id,
            agent_role=lesson.agent_role,
            lesson_type=lesson.lesson_type,
        )
        return lesson_id

    async def update_lesson(
        self,
        lesson_id: str,
        *,
        org_id: str,
        lesson_text: str | None = None,
        trigger_context: str | None = None,
        lesson_type: str | None = None,
        confidence: float | None = None,
    ) -> bool:
        """Update a lesson's mutable fields. Returns True if a row was updated."""
        pool = await self._ensure_pool()

        sets: list[str] = ["updated_at = now()"]
        params: list[Any] = []
        idx = 1

        if lesson_text is not None:
            sets.append(f"lesson = ${idx}")
            params.append(lesson_text)
            idx += 1
            # Re-embed when text changes
            vec_str = self._embed(
                f"{trigger_context or ''} {lesson_text}"
            )
            if vec_str:
                sets.append(f"embedding = ${idx}::vector")
                params.append(vec_str)
                idx += 1

        if trigger_context is not None:
            sets.append(f"trigger_context = ${idx}")
            params.append(trigger_context)
            idx += 1

        if lesson_type is not None:
            sets.append(f"lesson_type = ${idx}")
            params.append(lesson_type)
            idx += 1

        if confidence is not None:
            sets.append(f"confidence = ${idx}")
            params.append(confidence)
            idx += 1

        params.extend([lesson_id, org_id])

        async with pool.acquire() as conn:
            result = await conn.execute(
                f"""
                UPDATE lessons SET {', '.join(sets)}
                WHERE id = ${idx}::uuid AND org_id = ${idx + 1}
                """,
                *params,
            )

        return result.endswith("1")

    async def delete_lesson(self, lesson_id: str, *, org_id: str) -> bool:
        """Delete a lesson. Returns True if deleted."""
        pool = await self._ensure_pool()

        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM lessons WHERE id = $1::uuid AND org_id = $2",
                lesson_id,
                org_id,
            )

        return result.endswith("1")

    async def reinforce(self, lesson_id: str, *, org_id: str) -> bool:
        """Increment ``times_reinforced`` and boost confidence.

        Confidence asymptotically approaches 1.0:
        new_confidence = old + (1.0 - old) * 0.1
        """
        pool = await self._ensure_pool()

        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE lessons SET
                    times_reinforced = times_reinforced + 1,
                    confidence = confidence + (1.0 - confidence) * 0.1,
                    updated_at = now()
                WHERE id = $1::uuid AND org_id = $2
                """,
                lesson_id,
                org_id,
            )

        return result.endswith("1")

    async def record_application(self, lesson_id: str) -> None:
        """Increment ``times_applied`` (called when a lesson is injected into a prompt)."""
        pool = await self._ensure_pool()

        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE lessons SET times_applied = times_applied + 1,
                                   updated_at = now()
                WHERE id = $1::uuid
                """,
                lesson_id,
            )

    # ------------------------------------------------------------------
    # Read / search operations
    # ------------------------------------------------------------------

    async def get_lesson(self, lesson_id: str, *, org_id: str) -> Lesson | None:
        """Fetch a single lesson by ID, scoped to org."""
        pool = await self._ensure_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, org_id, agent_role, lesson_type, trigger_context,
                       lesson, evidence, pipeline_id, confidence,
                       times_applied, times_reinforced, created_at, updated_at
                FROM lessons WHERE id = $1::uuid AND org_id = $2
                """,
                lesson_id,
                org_id,
            )

        if row is None:
            return None
        return self._row_to_lesson(row)

    async def list_lessons(
        self,
        *,
        org_id: str,
        agent_role: str | None = None,
        lesson_type: str | None = None,
        min_confidence: float = 0.0,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Lesson]:
        """List lessons for an org with optional filters."""
        pool = await self._ensure_pool()

        conditions = ["org_id = $1", "confidence >= $2"]
        params: list[Any] = [org_id, min_confidence]
        idx = 3

        if agent_role:
            conditions.append(f"agent_role = ${idx}")
            params.append(agent_role)
            idx += 1

        if lesson_type:
            conditions.append(f"lesson_type = ${idx}")
            params.append(lesson_type)
            idx += 1

        where = " AND ".join(conditions)
        params.extend([limit, offset])

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, org_id, agent_role, lesson_type, trigger_context,
                       lesson, evidence, pipeline_id, confidence,
                       times_applied, times_reinforced, created_at, updated_at
                FROM lessons
                WHERE {where}
                ORDER BY confidence DESC, times_applied DESC
                LIMIT ${idx} OFFSET ${idx + 1}
                """,
                *params,
            )

        return [self._row_to_lesson(r) for r in rows]

    async def search(
        self,
        query: str,
        *,
        org_id: str,
        agent_role: str | None = None,
        min_confidence: float = 0.6,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """Semantic search for lessons relevant to a task description.

        Returns dicts with ``lesson``, ``score``, and metadata.
        """
        pool = await self._ensure_pool()
        embedding = self._embed(query)

        if embedding is not None:
            conditions = [
                "org_id = $1",
                "confidence >= $2",
                "embedding IS NOT NULL",
            ]
            params: list[Any] = [org_id, min_confidence]
            idx = 3

            if agent_role:
                conditions.append(f"agent_role = ${idx}")
                params.append(agent_role)
                idx += 1

            where = " AND ".join(conditions)
            params.append(limit)

            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    f"""
                    SELECT id, agent_role, lesson_type, trigger_context,
                           lesson, confidence, times_applied, times_reinforced,
                           1 - (embedding <=> $3::vector) AS score
                    FROM lessons
                    WHERE {where}
                    ORDER BY embedding <=> $3::vector
                    LIMIT ${idx}
                    """,
                    org_id, min_confidence, embedding, *params[2:],
                )
        else:
            # No embedder — fall back to recency
            conditions = ["org_id = $1", "confidence >= $2"]
            params = [org_id, min_confidence]
            idx = 3

            if agent_role:
                conditions.append(f"agent_role = ${idx}")
                params.append(agent_role)
                idx += 1

            where = " AND ".join(conditions)
            params.append(limit)

            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    f"""
                    SELECT id, agent_role, lesson_type, trigger_context,
                           lesson, confidence, times_applied, times_reinforced,
                           0.0 AS score
                    FROM lessons
                    WHERE {where}
                    ORDER BY confidence DESC, times_applied DESC
                    LIMIT ${idx}
                    """,
                    *params,
                )

        return [
            {
                "id": str(r["id"]),
                "agent_role": r["agent_role"],
                "lesson_type": r["lesson_type"],
                "trigger_context": r["trigger_context"],
                "lesson": r["lesson"],
                "confidence": float(r["confidence"]),
                "times_applied": r["times_applied"],
                "times_reinforced": r["times_reinforced"],
                "score": float(r["score"]),
            }
            for r in rows
        ]

    async def find_duplicate(
        self,
        lesson_text: str,
        *,
        org_id: str,
        agent_role: str,
        threshold: float = 0.85,
    ) -> dict[str, Any] | None:
        """Find an existing lesson that is semantically similar.

        Returns the closest match above *threshold*, or ``None``.
        Used before storing to detect reinforcement opportunities.
        """
        results = await self.search(
            lesson_text,
            org_id=org_id,
            agent_role=agent_role,
            min_confidence=0.0,
            limit=1,
        )
        if results and results[0]["score"] >= threshold:
            return results[0]
        return None

    async def close(self) -> None:
        """Close the connection pool."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_lesson(row) -> Lesson:
        return Lesson(
            id=str(row["id"]),
            org_id=row["org_id"],
            agent_role=row["agent_role"],
            lesson_type=row["lesson_type"],
            trigger_context=row["trigger_context"],
            lesson=row["lesson"],
            evidence=row.get("evidence", ""),
            pipeline_id=row.get("pipeline_id", ""),
            confidence=float(row["confidence"]),
            times_applied=row["times_applied"],
            times_reinforced=row["times_reinforced"],
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )
