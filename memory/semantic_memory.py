"""Semantic agent memory for cross-pipeline learning.

Uses `Mem0 <https://docs.mem0.ai>`_ with pgvector as the primary backend.
Falls back to a raw asyncpg + pgvector + sentence-transformers implementation
if Mem0 cannot be configured.

All memory operations are org-scoped. When ``memory_sharing_mode`` is
``"private"`` in org_settings, memories are additionally filtered by
``user_id`` so each team member has their own recall context.

Usage::

    from memory.semantic_memory import SemanticMemory, get_relevant_context

    mem = SemanticMemory()
    await mem.store_lesson("developer", "pipe-1", "Always add NOT NULL constraints",
                           org_id="org-abc", user_id="user-1")
    results = await mem.recall("database schema best practices",
                               agent_role="developer", org_id="org-abc")
    context = await get_relevant_context("architect", "design a REST API",
                                          org_id="org-abc")
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlparse

import structlog

log = structlog.get_logger().bind(component="semantic_memory")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EMBEDDING_MODEL = "multi-qa-MiniLM-L6-cos-v1"
_EMBEDDING_DIMS = 384


# ---------------------------------------------------------------------------
# Config builder
# ---------------------------------------------------------------------------


def _parse_dsn() -> tuple[str, dict[str, str]]:
    """Return (dsn, parsed_components) from DATABASE_URL."""
    dsn = os.environ.get(
        "DATABASE_URL",
        "postgresql://forge:forge_dev_password@localhost:5432/forge_app",
    )
    parsed = urlparse(dsn)
    return dsn, {
        "dbname": (parsed.path or "/forge_app").lstrip("/"),
        "user": parsed.username or "forge",
        "password": parsed.password or "forge_dev_password",
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
    }


def _default_config() -> dict:
    """Build Mem0 configuration from environment."""
    _, pg = _parse_dsn()
    model = os.environ.get("FORGE_MODEL", "claude-sonnet-4-5-20250929")

    return {
        "llm": {
            "provider": "anthropic",
            "config": {
                "model": model,
                "temperature": 0.1,
                "max_tokens": 2000,
            },
        },
        "embedder": {
            "provider": "huggingface",
            "config": {
                "model": _EMBEDDING_MODEL,
                "embedding_dims": _EMBEDDING_DIMS,
            },
        },
        "vector_store": {
            "provider": "pgvector",
            "config": {
                **pg,
                "collection_name": "forge_memories",
                "embedding_model_dims": _EMBEDDING_DIMS,
                "hnsw": True,
                "diskann": False,
            },
        },
    }


# ---------------------------------------------------------------------------
# Mem0 backend
# ---------------------------------------------------------------------------


class _Mem0Backend:
    """Wraps Mem0 AsyncMemory."""

    def __init__(self, mem: Any) -> None:
        self._mem = mem

    @classmethod
    async def create(cls, config: dict) -> _Mem0Backend:
        """Create a _Mem0Backend from the given configuration dict."""
        from mem0 import AsyncMemory  # type: ignore[import-untyped]

        mem = AsyncMemory.from_config(config)
        log.info("Mem0 backend created")
        return cls(mem)

    async def store(
        self,
        content: str,
        *,
        agent_role: str | None = None,
        pipeline_id: str | None = None,
        memory_type: str = "lesson",
        metadata: dict | None = None,
        org_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        """Store a memory entry via Mem0 with optional agent and pipeline tags."""
        meta = dict(metadata or {})
        meta["memory_type"] = memory_type
        if pipeline_id:
            meta["pipeline_id"] = pipeline_id
        if org_id:
            meta["org_id"] = org_id
        if user_id:
            meta["user_id"] = user_id

        await self._mem.add(
            content,
            agent_id=agent_role,
            run_id=pipeline_id,
            metadata=meta,
        )

    async def search(
        self,
        query: str,
        *,
        agent_role: str | None = None,
        limit: int = 5,
        org_id: str | None = None,
        user_id: str | None = None,
    ) -> list[dict]:
        """Search memories by semantic similarity, optionally filtered by agent role."""
        kwargs: dict[str, Any] = {"query": query, "limit": limit}
        if agent_role:
            kwargs["agent_id"] = agent_role

        # Mem0 metadata filtering for org_id
        filters: dict[str, Any] = {}
        if org_id:
            filters["org_id"] = org_id
        if user_id:
            filters["user_id"] = user_id
        if filters:
            kwargs["filters"] = filters

        result = await self._mem.search(**kwargs)
        entries = result.get("results", result) if isinstance(result, dict) else result
        return [
            {
                "id": str(e.get("id", "")),
                "content": e.get("memory", e.get("content", "")),
                "score": e.get("score", 0.0),
                "metadata": e.get("metadata", {}),
            }
            for e in entries
        ]

    async def get_all(
        self,
        *,
        pipeline_id: str | None = None,
        limit: int = 20,
        org_id: str | None = None,
        user_id: str | None = None,
    ) -> list[dict]:
        """Return all memories, optionally filtered by pipeline ID."""
        kwargs: dict[str, Any] = {"limit": limit}
        if pipeline_id:
            kwargs["run_id"] = pipeline_id

        filters: dict[str, Any] = {}
        if org_id:
            filters["org_id"] = org_id
        if user_id:
            filters["user_id"] = user_id
        if filters:
            kwargs["filters"] = filters

        result = await self._mem.get_all(**kwargs)
        entries = result.get("results", result) if isinstance(result, dict) else result
        return [
            {
                "id": str(e.get("id", "")),
                "content": e.get("memory", e.get("content", "")),
                "metadata": e.get("metadata", {}),
            }
            for e in entries
        ]


# ---------------------------------------------------------------------------
# Fallback backend (raw asyncpg + sentence-transformers + pgvector)
# ---------------------------------------------------------------------------


class _FallbackBackend:
    """Direct PostgreSQL + pgvector implementation."""

    def __init__(self, pool: Any, embedder: Any) -> None:
        self._pool = pool
        self._embedder = embedder

    @classmethod
    async def create(cls, dsn: str) -> _FallbackBackend:
        """Create a fallback backend with asyncpg pool and sentence-transformers embedder."""
        import asyncpg

        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)
        log.info("fallback pool created")

        # Ensure table exists (includes org_id and user_id columns)
        async with pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS memory_store (
                    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    agent_role  TEXT,
                    pipeline_id TEXT,
                    org_id      TEXT,
                    user_id     TEXT,
                    content     TEXT NOT NULL,
                    memory_type TEXT NOT NULL DEFAULT 'lesson',
                    metadata    JSONB NOT NULL DEFAULT '{}',
                    embedding   vector(384),
                    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
                )
            """)

        # Load sentence-transformers embedder
        embedder = None
        try:
            from sentence_transformers import SentenceTransformer

            embedder = SentenceTransformer(_EMBEDDING_MODEL)
            log.info("sentence-transformers embedder loaded", model=_EMBEDDING_MODEL)
        except Exception as exc:
            log.warning(
                "sentence-transformers not available, similarity search disabled",
                error=str(exc),
            )

        return cls(pool, embedder)

    def _embed(self, text: str) -> str | None:
        """Return a pgvector-compatible string, or None."""
        if self._embedder is None:
            return None
        vec = self._embedder.encode(text).tolist()
        return f"[{','.join(str(v) for v in vec)}]"

    @staticmethod
    def _org_filter(
        org_id: str | None,
        user_id: str | None,
        param_offset: int,
    ) -> tuple[str, list[Any]]:
        """Build SQL WHERE clauses and params for org/user filtering.

        Returns (sql_fragment, params) where sql_fragment is empty string
        or starts with "AND ...".
        """
        clauses: list[str] = []
        params: list[Any] = []
        if org_id:
            clauses.append(f"(org_id = ${param_offset} OR org_id IS NULL)")
            params.append(org_id)
            param_offset += 1
        if user_id:
            clauses.append(f"(user_id = ${param_offset} OR user_id IS NULL)")
            params.append(user_id)
            param_offset += 1
        sql = ""
        if clauses:
            sql = " AND " + " AND ".join(clauses)
        return sql, params

    async def store(
        self,
        content: str,
        *,
        agent_role: str | None = None,
        pipeline_id: str | None = None,
        memory_type: str = "lesson",
        metadata: dict | None = None,
        org_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        """Insert a memory entry into PostgreSQL with its embedding vector."""
        embedding = self._embed(content)
        meta_json = json.dumps(metadata or {}, default=str)

        await self._pool.execute(
            """
            INSERT INTO memory_store
                (agent_role, pipeline_id, org_id, user_id,
                 content, memory_type, metadata, embedding)
            VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb, $8::vector)
            """,
            agent_role,
            pipeline_id,
            org_id,
            user_id,
            content,
            memory_type,
            meta_json,
            embedding,
        )

    async def search(
        self,
        query: str,
        *,
        agent_role: str | None = None,
        limit: int = 5,
        org_id: str | None = None,
        user_id: str | None = None,
    ) -> list[dict]:
        """Search by cosine similarity if embedder is available, else by recency."""
        embedding = self._embed(query)

        if embedding is not None:
            # Base params: $1=embedding, $2 depends on agent_role
            if agent_role:
                base_where = "WHERE embedding IS NOT NULL AND agent_role = $2"
                base_params: list[Any] = [embedding, agent_role]
                offset = 3
            else:
                base_where = "WHERE embedding IS NOT NULL"
                base_params = [embedding]
                offset = 2

            org_sql, org_params = self._org_filter(org_id, user_id, offset)
            offset += len(org_params)
            all_params = base_params + org_params + [limit]

            rows = await self._pool.fetch(
                f"""
                SELECT id, content, metadata, memory_type, agent_role, pipeline_id,
                       user_id, 1 - (embedding <=> $1::vector) AS score
                FROM memory_store
                {base_where}{org_sql}
                ORDER BY embedding <=> $1::vector
                LIMIT ${offset}
                """,
                *all_params,
            )
        else:
            # No embedder — fall back to recency
            if agent_role:
                base_where = "WHERE agent_role = $1"
                base_params = [agent_role]
                offset = 2
            else:
                base_where = "WHERE TRUE"
                base_params = []
                offset = 1

            org_sql, org_params = self._org_filter(org_id, user_id, offset)
            offset += len(org_params)
            all_params = base_params + org_params + [limit]

            rows = await self._pool.fetch(
                f"""
                SELECT id, content, metadata, memory_type, agent_role, pipeline_id,
                       user_id, 0.0 AS score
                FROM memory_store
                {base_where}{org_sql}
                ORDER BY created_at DESC
                LIMIT ${offset}
                """,
                *all_params,
            )

        return self._rows_to_results(rows)

    async def get_all(
        self,
        *,
        pipeline_id: str | None = None,
        limit: int = 20,
        org_id: str | None = None,
        user_id: str | None = None,
    ) -> list[dict]:
        """Return all memories ordered by recency, optionally filtered by pipeline ID."""
        if pipeline_id:
            base_where = "WHERE pipeline_id = $1"
            base_params: list[Any] = [pipeline_id]
            offset = 2
        else:
            base_where = "WHERE TRUE"
            base_params = []
            offset = 1

        org_sql, org_params = self._org_filter(org_id, user_id, offset)
        offset += len(org_params)
        all_params = base_params + org_params + [limit]

        rows = await self._pool.fetch(
            f"""
            SELECT id, content, metadata, memory_type, agent_role, pipeline_id, user_id
            FROM memory_store
            {base_where}{org_sql}
            ORDER BY created_at DESC
            LIMIT ${offset}
            """,
            *all_params,
        )

        return self._rows_to_results(rows)

    async def get_org_stats(self, org_id: str) -> dict:
        """Return org-level memory statistics."""
        org_filter = "(org_id = $1 OR org_id IS NULL)"

        total_lessons = await self._pool.fetchval(
            f"SELECT COUNT(*) FROM memory_store WHERE memory_type = 'lesson' AND {org_filter}",
            org_id,
        ) or 0

        total_decisions = await self._pool.fetchval(
            f"SELECT COUNT(*) FROM memory_store WHERE memory_type = 'decision' AND {org_filter}",
            org_id,
        ) or 0

        role_rows = await self._pool.fetch(
            f"""
            SELECT agent_role, COUNT(*) AS count
            FROM memory_store
            WHERE memory_type = 'lesson' AND agent_role IS NOT NULL AND {org_filter}
            GROUP BY agent_role
            ORDER BY count DESC
            """,
            org_id,
        )

        contributor_rows = await self._pool.fetch(
            f"""
            SELECT user_id, COUNT(*) AS count
            FROM memory_store
            WHERE user_id IS NOT NULL AND {org_filter}
            GROUP BY user_id
            ORDER BY count DESC
            LIMIT 20
            """,
            org_id,
        )

        recent_rows = await self._pool.fetch(
            f"""
            SELECT id, content, agent_role, user_id, created_at
            FROM memory_store
            WHERE memory_type = 'lesson' AND {org_filter}
            ORDER BY created_at DESC
            LIMIT 10
            """,
            org_id,
        )

        return {
            "total_lessons": total_lessons,
            "total_decisions": total_decisions,
            "lessons_per_role": {r["agent_role"]: r["count"] for r in role_rows},
            "contributions_per_user": {
                r["user_id"]: r["count"] for r in contributor_rows
            },
            "recent_lessons": [
                {
                    "id": str(r["id"]),
                    "content": r["content"][:200],
                    "agent_role": r["agent_role"],
                    "user_id": r["user_id"],
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in recent_rows
            ],
        }

    @staticmethod
    def _rows_to_results(rows: list) -> list[dict]:
        """Convert asyncpg rows to result dicts."""
        results = []
        for r in rows:
            meta = r["metadata"]
            if isinstance(meta, str):
                try:
                    meta = json.loads(meta)
                except (json.JSONDecodeError, TypeError):
                    meta = {}
            results.append(
                {
                    "id": str(r["id"]),
                    "content": r["content"],
                    "score": float(r.get("score", 0)),
                    "metadata": {
                        **(meta if isinstance(meta, dict) else {}),
                        "memory_type": r["memory_type"],
                        "agent_role": r["agent_role"],
                        "pipeline_id": r["pipeline_id"],
                        "user_id": r.get("user_id"),
                    },
                }
            )
        return results


# ---------------------------------------------------------------------------
# SemanticMemory — public API
# ---------------------------------------------------------------------------


class SemanticMemory:
    """Semantic agent memory with cross-pipeline learning.

    Tries Mem0 with pgvector first; falls back to raw asyncpg + pgvector +
    sentence-transformers if Mem0 cannot be initialised.

    All operations accept optional ``org_id`` and ``user_id`` parameters
    for multi-tenant isolation. When the org's ``memory_sharing_mode``
    is ``"private"``, callers should pass ``user_id`` to both store and
    recall so that each user's context is isolated.
    """

    def __init__(self, config: dict | None = None) -> None:
        self._config = config or _default_config()
        self._backend: _Mem0Backend | _FallbackBackend | None = None
        self._initialized = False

    async def _ensure_init(self) -> _Mem0Backend | _FallbackBackend:
        if self._backend is not None:
            return self._backend

        # Try Mem0 first
        try:
            self._backend = await _Mem0Backend.create(self._config)
            log.info("semantic memory: using Mem0 backend")
        except Exception as exc:
            log.warning("Mem0 init failed, using pgvector fallback", error=str(exc))
            dsn, _ = _parse_dsn()
            self._backend = await _FallbackBackend.create(dsn)
            log.info("semantic memory: using pgvector fallback backend")

        return self._backend

    # -- Public API ----------------------------------------------------------

    async def store_lesson(
        self,
        agent_role: str,
        pipeline_id: str,
        lesson: str,
        metadata: dict | None = None,
        *,
        org_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        """Store a learning from an agent's experience."""
        backend = await self._ensure_init()
        meta = dict(metadata or {})
        meta["agent_role"] = agent_role
        await backend.store(
            lesson,
            agent_role=agent_role,
            pipeline_id=pipeline_id,
            memory_type="lesson",
            metadata=meta,
            org_id=org_id,
            user_id=user_id,
        )
        log.info(
            "lesson stored",
            agent_role=agent_role,
            pipeline_id=pipeline_id,
            org_id=org_id,
            preview=lesson[:80],
        )

    async def store_decision(
        self,
        pipeline_id: str,
        decision_type: str,
        decision: str,
        rationale: str,
        context: dict | None = None,
        *,
        org_id: str | None = None,
        user_id: str | None = None,
    ) -> None:
        """Store an architectural or process decision for future reference."""
        backend = await self._ensure_init()
        content = f"[{decision_type}] {decision} — Rationale: {rationale}"
        meta = dict(context or {})
        meta["decision_type"] = decision_type
        meta["rationale"] = rationale
        await backend.store(
            content,
            pipeline_id=pipeline_id,
            memory_type="decision",
            metadata=meta,
            org_id=org_id,
            user_id=user_id,
        )
        log.info(
            "decision stored",
            pipeline_id=pipeline_id,
            decision_type=decision_type,
            org_id=org_id,
        )

    async def recall(
        self,
        query: str,
        agent_role: str | None = None,
        limit: int = 5,
        *,
        org_id: str | None = None,
        user_id: str | None = None,
    ) -> list[dict]:
        """Retrieve relevant memories via semantic similarity."""
        backend = await self._ensure_init()
        return await backend.search(
            query,
            agent_role=agent_role,
            limit=limit,
            org_id=org_id,
            user_id=user_id,
        )

    async def recall_for_pipeline(
        self,
        pipeline_id: str,
        limit: int = 20,
        *,
        org_id: str | None = None,
        user_id: str | None = None,
    ) -> list[dict]:
        """Get all memories associated with a pipeline."""
        backend = await self._ensure_init()
        return await backend.get_all(
            pipeline_id=pipeline_id,
            limit=limit,
            org_id=org_id,
            user_id=user_id,
        )

    async def extract_lessons_from_pipeline(
        self,
        pipeline_id: str,
        pipeline_result: dict,
        *,
        org_id: str | None = None,
        user_id: str | None = None,
    ) -> list[str]:
        """Analyse a completed pipeline run and extract 3-5 lessons.

        Examines ticket revisions, CTO interventions, cost vs budget,
        tech stack choices, and QA patterns. Uses the LLM to synthesise
        concise, reusable lessons.
        """
        prompt = _build_lesson_extraction_prompt(pipeline_id, pipeline_result)
        lessons = await _call_llm_for_lessons(prompt)

        # Store each lesson
        for lesson in lessons:
            await self.store_lesson(
                agent_role="system",
                pipeline_id=pipeline_id,
                lesson=lesson,
                metadata={"source": "post_pipeline_analysis"},
                org_id=org_id,
                user_id=user_id,
            )

        log.info(
            "lessons extracted",
            pipeline_id=pipeline_id,
            org_id=org_id,
            count=len(lessons),
        )
        return lessons

    async def get_org_memory_stats(self, org_id: str) -> dict:
        """Return org-level memory statistics.

        Returns::

            {
                "total_lessons": int,
                "total_decisions": int,
                "lessons_per_role": {"developer": 5, "architect": 3, ...},
                "contributions_per_user": {"user-id-1": 8, ...},
                "recent_lessons": [{id, content, agent_role, user_id, created_at}, ...],
            }
        """
        backend = await self._ensure_init()
        if isinstance(backend, _FallbackBackend):
            return await backend.get_org_stats(org_id)

        # Mem0 backend doesn't support aggregation queries natively;
        # fall through to a basic response
        return {
            "total_lessons": 0,
            "total_decisions": 0,
            "lessons_per_role": {},
            "contributions_per_user": {},
            "recent_lessons": [],
        }


# ---------------------------------------------------------------------------
# Lesson extraction helpers
# ---------------------------------------------------------------------------


def _build_lesson_extraction_prompt(pipeline_id: str, result: dict) -> str:
    """Build the LLM prompt for lesson extraction."""

    # Summarise key data points from the pipeline result
    parts: list[str] = [f"Pipeline: {pipeline_id}"]

    status = result.get("status", "unknown")
    parts.append(f"Outcome: {status}")

    cost = result.get("total_cost_usd", 0)
    max_cost = result.get("max_cost_usd", 0)
    if cost or max_cost:
        parts.append(f"Cost: ${cost:.4f} / ${max_cost:.2f} budget")

    tech_spec = result.get("tech_spec")
    if isinstance(tech_spec, dict):
        stack = tech_spec.get("tech_stack", {})
        if stack:
            parts.append(f"Tech stack: {json.dumps(stack)}")

    # Ticket analysis
    code_artifacts = result.get("code_artifacts", [])
    qa_reviews = result.get("qa_reviews", [])
    skipped = [a for a in code_artifacts if a.get("skipped")]
    revisions = [r for r in qa_reviews if r.get("verdict") == "needs_revision"]
    rejected = [r for r in qa_reviews if r.get("verdict") == "rejected"]

    parts.append(f"Tickets completed: {len(code_artifacts)}")
    if skipped:
        parts.append(f"Tickets skipped: {len(skipped)}")
    if revisions:
        parts.append(f"QA revision requests: {len(revisions)}")
    if rejected:
        parts.append(f"QA rejections: {len(rejected)}")

    # Include sample revision instructions for context
    for rev in revisions[:3]:
        instructions = rev.get("revision_instructions", [])
        if instructions:
            parts.append(f"Revision reason: {'; '.join(instructions[:2])}")

    summary = "\n".join(parts)

    return f"""Analyse this completed software pipeline run and extract 3-5 concise,
actionable lessons that would improve future runs.

Focus on:
- What caused QA revisions or rejections? What pattern should agents avoid?
- Were there cost efficiency issues?
- What tech stack or architectural decisions worked well or poorly?
- What would you tell the agents differently next time?

Each lesson should be one sentence, written as an instruction.
Return ONLY a JSON array of strings, e.g. ["lesson 1", "lesson 2", ...].

Pipeline data:
{summary}"""


async def _call_llm_for_lessons(prompt: str) -> list[str]:
    """Call Anthropic to extract lessons."""
    try:
        from config.agent_config import get_anthropic_client

        client = get_anthropic_client()
        model = os.environ.get("FORGE_MODEL", "claude-sonnet-4-5-20250929")

        response = await client.messages.create(
            model=model,
            max_tokens=1024,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}],
        )

        text = response.content[0].text.strip()
        # Extract JSON array from the response
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])

        # Fallback: split by newlines
        return [line.strip("- ").strip() for line in text.splitlines() if line.strip()]

    except Exception as exc:
        log.warning("lesson extraction LLM call failed", error=str(exc))
        return ["Pipeline completed — review logs for improvement opportunities."]


# ---------------------------------------------------------------------------
# Memory sharing mode helper
# ---------------------------------------------------------------------------


async def get_memory_sharing_mode(org_id: str) -> str:
    """Look up the org's memory_sharing_mode from org_settings.

    Returns ``"shared"`` (default) or ``"private"``.
    """
    try:
        import asyncpg

        dsn, _ = _parse_dsn()
        conn = await asyncpg.connect(dsn)
        try:
            row = await conn.fetchval(
                "SELECT memory_sharing_mode FROM org_settings WHERE org_id = $1",
                org_id,
            )
            return row or "shared"
        finally:
            await conn.close()
    except Exception:
        return "shared"


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


async def get_relevant_context(
    agent_role: str,
    task_description: str,
    *,
    memory: SemanticMemory | None = None,
    limit: int = 5,
    org_id: str | None = None,
    user_id: str | None = None,
) -> str:
    """Recall relevant memories and format as a context block for agent prompts.

    If no SemanticMemory instance is provided, one is created with default config.

    In "private" memory mode, pass ``user_id`` to restrict recall to the
    user's own memories within the org.
    """
    mem = memory or SemanticMemory()

    # Resolve private mode: if org_id is set, check sharing mode
    effective_user_id = user_id
    if org_id and not user_id:
        # In shared mode, don't filter by user
        effective_user_id = None
    elif org_id and user_id:
        # Check if the org uses private mode
        mode = await get_memory_sharing_mode(org_id)
        if mode != "private":
            effective_user_id = None  # shared mode — recall from all users

    try:
        results = await mem.recall(
            task_description,
            agent_role=agent_role,
            limit=limit,
            org_id=org_id,
            user_id=effective_user_id,
        )
    except Exception as exc:
        log.warning("memory recall failed", error=str(exc))
        return ""

    if not results:
        return ""

    lines = ["<relevant_memories>"]
    for entry in results:
        content = entry.get("content", "")
        score = entry.get("score", 0)
        if content:
            lines.append(f"- [{score:.2f}] {content}")
    lines.append("</relevant_memories>")

    return "\n".join(lines)
