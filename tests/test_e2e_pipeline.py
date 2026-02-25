"""End-to-end integration test for the full Forge pipeline.

Flow tested:
  1. Index a sample repo → extract chunks
  2. Run a pipeline → verify codebase context assembled
  3. Reject output → verify lesson extracted and stored
  4. Re-run → verify lesson injected into prompt
  5. Check metrics → verify evaluation recorded

All external services (DB, LLM, Redis) are mocked so this test runs
without infrastructure.  Marked ``@pytest.mark.e2e`` for optional
filtering, but designed to always run.
"""

from __future__ import annotations

import json
import textwrap
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.codebase.indexer import CodeChunk, RepoIndexer, _extract_chunks_from_tree, _get_parser
from agents.codebase.embedder import ChunkEmbedder, EmbeddedChunk, describe_chunk
from agents.communication.agent_bus import AgentBus
from agents.communication.types import AgentResponse
from agents.learning.feedback_processor import FeedbackProcessor, get_lessons_for_prompt
from agents.learning.lesson_store import LessonStore
from agents.learning.types import Lesson
from agents.prompts.registry import PromptRegistry
from agents.prompts.types import PromptVersion
from contracts.schemas import AgentRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _AsyncCtx:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


def _mock_model_router(content="Generated output", cost=0.05):
    router = MagicMock()
    router.route_request = AsyncMock(return_value="claude-sonnet-4-5")
    router.complete = AsyncMock(return_value={
        "content": content,
        "model_used": "claude-sonnet-4-5",
        "input_tokens": 500,
        "output_tokens": 200,
        "cost_usd": cost,
        "latency_ms": 300,
    })
    return router


# ---------------------------------------------------------------------------
# Step 1: Index a sample repo → extract chunks
# ---------------------------------------------------------------------------


@pytest.mark.e2e
class TestE2EPipelineFlow:

    @pytest.mark.asyncio
    async def test_step1_index_repo(self, tmp_path):
        """Index a sample repo and extract meaningful code chunks."""
        import subprocess
        import os

        git_env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "E2E",
            "GIT_AUTHOR_EMAIL": "e2e@test.com",
            "GIT_COMMITTER_NAME": "E2E",
            "GIT_COMMITTER_EMAIL": "e2e@test.com",
        }

        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)

        # Create a Python file with functions and classes
        (tmp_path / "auth.py").write_text(textwrap.dedent("""\
            class AuthService:
                \"\"\"Handles user authentication.\"\"\"

                def login(self, email: str, password: str) -> bool:
                    \"\"\"Authenticate a user by email and password.\"\"\"
                    return True

                def logout(self, session_id: str) -> None:
                    pass

            def validate_token(token: str) -> dict:
                \"\"\"Validate a JWT token and return claims.\"\"\"
                return {}
        """))

        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "initial"],
            cwd=tmp_path, capture_output=True, env=git_env,
        )

        # Full index
        indexer = RepoIndexer(tmp_path)
        parser = _get_parser("python")
        if parser is None:
            pytest.skip("tree-sitter-python not installed")

        chunks = await indexer.index()

        # Verify chunks extracted
        names = {c.qualified_name for c in chunks}
        assert "AuthService" in names
        assert "AuthService.login" in names
        assert "AuthService.logout" in names
        assert "validate_token" in names

        # Verify chunk metadata
        login = next(c for c in chunks if c.name == "login")
        assert login.chunk_type == "method"
        assert login.parent_name == "AuthService"
        assert "Authenticate" in login.docstring

        return chunks

    @pytest.mark.asyncio
    async def test_step2_embed_chunks(self):
        """Embed extracted chunks and verify dual vectors produced."""
        import numpy as np

        chunks = [
            CodeChunk(
                file_path="auth.py",
                language="python",
                chunk_type="class",
                name="AuthService",
                qualified_name="AuthService",
                body="class AuthService: ...",
                start_line=1,
                end_line=10,
                docstring="Handles user authentication.",
            ),
            CodeChunk(
                file_path="auth.py",
                language="python",
                chunk_type="method",
                name="login",
                qualified_name="AuthService.login",
                body="def login(self, email, password): ...",
                start_line=4,
                end_line=6,
                signature="def login(self, email: str, password: str) -> bool",
                docstring="Authenticate a user by email and password.",
                parent_name="AuthService",
            ),
        ]

        mock_model = MagicMock()
        mock_model.encode = MagicMock(
            side_effect=lambda texts, **kw: np.random.rand(len(texts), 384).astype(np.float32)
        )

        embedder = ChunkEmbedder()
        embedder._model = mock_model

        embedded = await embedder.embed_chunks(chunks)

        assert len(embedded) == 2
        for ec in embedded:
            assert len(ec.code_embedding) == 384
            assert len(ec.description_embedding) == 384

        # Descriptions should mention language and type
        desc = describe_chunk(chunks[1])
        assert "Python" in desc
        assert "method" in desc
        assert "AuthService" in desc

    @pytest.mark.asyncio
    async def test_step3_agent_communication(self):
        """Agents can ask each other questions during pipeline execution."""
        router = _mock_model_router(content="Use the AuthService for all auth operations.")
        p_router = patch("config.model_router.get_model_router", return_value=router)
        p_log = patch("memory.agent_log.stream_agent_log", new_callable=AsyncMock)

        with p_router, p_log:
            bus = AgentBus("e2e-pipe-1")

            # Developer asks Architect about auth pattern
            resp = await bus.ask(
                AgentRole.DEVELOPER,
                AgentRole.ARCHITECT,
                "Should I use the existing AuthService or create a new one?",
            )

            assert not resp.timed_out
            assert "AuthService" in resp.response
            assert resp.cost_usd > 0

            # Verify exchange is recorded
            assert len(bus.exchanges) == 1
            assert bus.exchanges[0]["from_role"] == AgentRole.DEVELOPER

    @pytest.mark.asyncio
    async def test_step4_reject_and_learn(self):
        """Reject output → lesson extracted → stored for future use."""
        extraction = {
            "lesson_type": "code_pattern",
            "trigger_context": "Authentication implementations",
            "lesson_text": "Always hash passwords with bcrypt before storing",
            "is_generalizable": True,
            "confidence": 0.9,
        }

        router = MagicMock()
        router.route_request = AsyncMock(return_value="claude-haiku-3-5")
        router.complete = AsyncMock(return_value={
            "content": json.dumps(extraction),
            "cost_usd": 0.001,
        })

        store = MagicMock(spec=LessonStore)
        store.find_duplicate = AsyncMock(return_value=None)
        store.store_lesson = AsyncMock(return_value="lesson-e2e-1")
        store.get_lesson = AsyncMock(return_value=Lesson(
            id="lesson-e2e-1",
            org_id="org-e2e",
            agent_role="developer",
            lesson_type="code_pattern",
            trigger_context="Authentication implementations",
            lesson="Always hash passwords with bcrypt before storing",
            confidence=0.9,
        ))

        with patch("config.model_router.get_model_router", return_value=router):
            processor = FeedbackProcessor(lesson_store=store)
            lesson = await processor.process_rejection(
                pipeline_id="e2e-pipe-1",
                stage="coding",
                user_comment="You need to hash passwords with bcrypt, not store them as plain text!",
                original_output={"files_created": ["src/auth.py"]},
                org_id="org-e2e",
                agent_role="developer",
            )

        assert lesson is not None
        assert lesson.id == "lesson-e2e-1"
        store.store_lesson.assert_called_once()
        stored = store.store_lesson.call_args[0][0]
        assert "bcrypt" in stored.lesson

    @pytest.mark.asyncio
    async def test_step5_lesson_injected_on_rerun(self):
        """On re-run, stored lessons are injected into the agent prompt."""
        store = MagicMock(spec=LessonStore)
        store.search = AsyncMock(return_value=[
            {
                "id": "lesson-e2e-1",
                "agent_role": "developer",
                "lesson_type": "code_pattern",
                "trigger_context": "Authentication implementations",
                "lesson": "Always hash passwords with bcrypt before storing",
                "confidence": 0.9,
                "times_applied": 0,
                "times_reinforced": 1,
                "score": 0.88,
            },
        ])
        store.record_application = AsyncMock()

        result = await get_lessons_for_prompt(
            "Implement user authentication with login and signup",
            org_id="org-e2e",
            agent_role="developer",
            store=store,
        )

        assert "Lessons from Previous Work" in result
        assert "bcrypt" in result
        assert "confidence: high" in result
        store.record_application.assert_called_once()

    @pytest.mark.asyncio
    async def test_step6_evaluation_recorded(self):
        """After pipeline completion, evaluation metrics are tracked."""
        registry = PromptRegistry(dsn="postgresql://test:test@localhost/test")
        registry._pool = MagicMock()

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={"id": "eval-e2e-1"})
        registry._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

        eval_id = await registry.record_evaluation(
            org_id="org-e2e",
            prompt_version_id="ver-e2e-1",
            pipeline_id="e2e-pipe-1",
            stage=5,
            agent_role="developer",
            verdict="approved",
            cost_usd=0.12,
            duration_seconds=45.0,
        )

        assert eval_id == "eval-e2e-1"
        conn.fetchrow.assert_called_once()

    @pytest.mark.asyncio
    async def test_step7_stats_aggregation(self):
        """After multiple evaluations, stats are correctly aggregated."""
        registry = PromptRegistry(dsn="postgresql://test:test@localhost/test")
        registry._pool = MagicMock()

        conn = AsyncMock()
        conn.fetchrow = AsyncMock(return_value={
            "total_runs": 3,
            "approved_count": 2,
            "avg_cost": 0.10,
            "avg_duration": 30.0,
            "avg_attempts": 1.33,
            "error_count": 0,
        })
        registry._pool.acquire = MagicMock(return_value=_AsyncCtx(conn))

        stats = await registry.get_version_stats("ver-e2e-1", org_id="org-e2e")

        assert stats is not None
        assert stats.total_runs == 3
        assert stats.approval_rate == pytest.approx(2 / 3, rel=0.01)
        assert stats.avg_cost_usd == 0.10

    @pytest.mark.asyncio
    async def test_full_flow_integration(self, tmp_path):
        """Abbreviated full flow: index → context → reject → learn → verify."""
        import os
        import subprocess
        import numpy as np

        git_env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "E2E",
            "GIT_AUTHOR_EMAIL": "e2e@test.com",
            "GIT_COMMITTER_NAME": "E2E",
            "GIT_COMMITTER_EMAIL": "e2e@test.com",
        }

        # 1. Create and index a mini repo
        subprocess.run(["git", "init"], cwd=tmp_path, capture_output=True)
        (tmp_path / "main.py").write_text("def handler(request): return {}\n")
        subprocess.run(["git", "add", "."], cwd=tmp_path, capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", "init"],
            cwd=tmp_path, capture_output=True, env=git_env,
        )

        parser = _get_parser("python")
        if parser is None:
            pytest.skip("tree-sitter-python not installed")

        indexer = RepoIndexer(tmp_path)
        chunks = await indexer.index()
        assert len(chunks) >= 1
        assert chunks[0].name == "handler"

        # 2. Embed chunks (mocked)
        mock_model = MagicMock()
        mock_model.encode = MagicMock(
            side_effect=lambda texts, **kw: np.random.rand(len(texts), 384).astype(np.float32)
        )
        embedder = ChunkEmbedder()
        embedder._model = mock_model
        embedded = await embedder.embed_chunks(chunks)
        assert len(embedded) == len(chunks)

        # 3. Simulate rejection → lesson extraction
        extraction = {
            "lesson_type": "code_pattern",
            "trigger_context": "Request handlers",
            "lesson_text": "Always validate request body before processing",
            "is_generalizable": True,
            "confidence": 0.85,
        }

        router = MagicMock()
        router.route_request = AsyncMock(return_value="claude-haiku-3-5")
        router.complete = AsyncMock(return_value={
            "content": json.dumps(extraction),
            "cost_usd": 0.001,
        })

        store = MagicMock(spec=LessonStore)
        store.find_duplicate = AsyncMock(return_value=None)
        store.store_lesson = AsyncMock(return_value="lesson-flow-1")
        store.get_lesson = AsyncMock(return_value=Lesson(
            id="lesson-flow-1",
            org_id="org-flow",
            agent_role="developer",
            lesson_type="code_pattern",
            trigger_context="Request handlers",
            lesson="Always validate request body before processing",
            confidence=0.85,
        ))

        with patch("config.model_router.get_model_router", return_value=router):
            processor = FeedbackProcessor(lesson_store=store)
            lesson = await processor.process_rejection(
                pipeline_id="flow-pipe",
                stage="coding",
                user_comment="Validate the request body!",
                original_output={},
                org_id="org-flow",
                agent_role="developer",
            )

        assert lesson is not None
        assert "validate" in lesson.lesson.lower()

        # 4. Verify lesson would be injected on re-run
        store.search = AsyncMock(return_value=[{
            "id": "lesson-flow-1",
            "agent_role": "developer",
            "lesson_type": "code_pattern",
            "trigger_context": "Request handlers",
            "lesson": "Always validate request body before processing",
            "confidence": 0.85,
            "times_applied": 0,
            "times_reinforced": 0,
            "score": 0.90,
        }])
        store.record_application = AsyncMock()

        prompt_section = await get_lessons_for_prompt(
            "Implement request handler",
            org_id="org-flow",
            agent_role="developer",
            store=store,
        )

        assert "validate request body" in prompt_section.lower()
        store.record_application.assert_called_once()
